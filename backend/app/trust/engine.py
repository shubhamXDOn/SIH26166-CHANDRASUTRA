from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend.app.trust.config import TrustConfig
from backend.app.trust.geometry import (
    ModelResult,
    compute_symmetric_transfer,
    estimate_affine,
    estimate_homography,
    validate_model_matrix,
)
from backend.app.trust.spatial import SpatialDiagnostics, compute_spatial_diagnostics
from backend.app.trust.states import TileTrustState, TrustReasonCode


@dataclass
class TileTrustResult:
    tile_id: str
    trust_state: TileTrustState
    reasons: list[str] = field(default_factory=list)
    block_code: str | None = None
    model_result: ModelResult | None = None
    spatial_diagnostics: SpatialDiagnostics | None = None
    cross_check_result: dict | None = None
    runtime_seconds: float = 0.0
    error: str | None = None


def _to_dict(result: TileTrustResult) -> dict:
    d: dict = {
        "tile_id": result.tile_id,
        "trust_state": result.trust_state.value,
        "reasons": list(result.reasons),
        "block_code": result.block_code,
        "runtime_seconds": round(result.runtime_seconds, 4),
        "error": result.error,
    }
    if result.model_result is not None:
        mr = result.model_result
        d["model"] = {
            "type": mr.model_type,
            "inlier_count": mr.inlier_count,
            "outlier_count": mr.outlier_count,
            "total_usable": mr.total_usable,
            "inlier_ratio": round(mr.inlier_ratio, 6),
            "residual_stats": mr.residual_stats,
            "iterations_used": mr.iterations_used,
            "seed_used": mr.seed_used,
            "degeneracy_flags": list(mr.degeneracy_flags),
            "model_valid": mr.matrix is not None,
        }
    if result.spatial_diagnostics is not None:
        sd = result.spatial_diagnostics
        d["spatial"] = {
            "grid_cells_occupied": sd.grid_cells_occupied,
            "total_cells": sd.total_cells,
            "occupancy_ratio": round(sd.occupancy_ratio, 6),
            "concentration_ratio": round(sd.concentration_ratio, 6),
            "spatial_extent_diag": round(sd.spatial_extent_diag, 4),
            "coordinate_spread_x": round(sd.coordinate_spread_x, 4),
            "coordinate_spread_y": round(sd.coordinate_spread_y, 4),
        }
    if result.cross_check_result is not None:
        d["cross_check"] = result.cross_check_result
    return d


def evaluate_tile(
    tile_candidates_path: Path,
    trust_config: TrustConfig,
    tile_id: str = "",
) -> TileTrustResult:
    t0 = time.time()
    try:
        return _evaluate_tile_inner(tile_candidates_path, trust_config, tile_id, t0)
    except Exception as exc:
        elapsed = time.time() - t0
        return TileTrustResult(
            tile_id=tile_id,
            trust_state=TileTrustState.FAILED,
            reasons=[TrustReasonCode.TG_NOT_RUN.value],
            runtime_seconds=elapsed,
            error=str(exc),
        )


def _evaluate_tile_inner(
    tile_candidates_path: Path,
    trust_config: TrustConfig,
    tile_id: str,
    t0: float,
) -> TileTrustResult:
    data = np.load(str(tile_candidates_path), allow_pickle=False)
    required_keys = {"x_a", "y_a", "x_b", "y_b"}
    if not required_keys.issubset(set(data.files)):
        return TileTrustResult(
            tile_id=tile_id,
            trust_state=TileTrustState.FAILED,
            reasons=[TrustReasonCode.TG_NOT_RUN.value],
            block_code="INVALID_ARTIFACT",
            runtime_seconds=time.time() - t0,
            error=f"Missing keys: {required_keys - set(data.files)}",
        )
    x_a = np.asarray(data["x_a"], dtype=np.float64).ravel()
    y_a = np.asarray(data["y_a"], dtype=np.float64).ravel()
    x_b = np.asarray(data["x_b"], dtype=np.float64).ravel()
    y_b = np.asarray(data["y_b"], dtype=np.float64).ravel()
    n = len(x_a)
    finite_mask = np.isfinite(x_a) & np.isfinite(y_a) & np.isfinite(x_b) & np.isfinite(y_b)
    usable_count = int(np.sum(finite_mask))
    min_usable = trust_config.candidate_integrity.min_usable_candidates
    if usable_count < min_usable:
        return TileTrustResult(
            tile_id=tile_id,
            trust_state=TileTrustState.INSUFFICIENT,
            reasons=[TrustReasonCode.TG_BLOCK_INSUFFICIENT_USABLE.value],
            block_code="INSUFFICIENT_USABLE_CANDIDATES",
            runtime_seconds=time.time() - t0,
        )
    pts_a = np.column_stack([x_a[finite_mask], y_a[finite_mask]])
    pts_b = np.column_stack([x_b[finite_mask], y_b[finite_mask]])
    model_type = trust_config.geometric_model.type
    ransac_cfg = trust_config.geometric_model.ransac
    if model_type == "affine":
        model_result = estimate_affine(pts_a, pts_b, ransac_cfg)
    else:
        model_result = estimate_homography(pts_a, pts_b, ransac_cfg)
    if model_result.matrix is None:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_MODEL_FIT_FAILED.value],
        )
    valid, issues = validate_model_matrix(model_result.matrix, model_type)
    if not valid:
        model_result.degeneracy_flags.extend(issues)
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_MODEL_INVALID.value],
        )
    if model_result.degeneracy_flags:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_DEGENERATE_GEOMETRY.value],
        )
    acc = trust_config.acceptance
    if model_result.inlier_count < acc.min_inliers:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_INSUFFICIENT_INLIERS.value],
        )
    if model_result.inlier_ratio < acc.min_inlier_ratio:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_LOW_INLIER_RATIO.value],
        )
    if model_result.residual_stats.get("mean", 0) > acc.max_residual_mean:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_EXCESSIVE_RESIDUAL.value],
        )
    if model_result.residual_stats.get("median", 0) > acc.max_residual_median:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_EXCESSIVE_RESIDUAL.value],
        )
    if model_result.residual_stats.get("p95", 0) > acc.max_residual_p95:
        return _fail_result(
            tile_id, t0, model_result,
            [TrustReasonCode.TG_FAIL_EXCESSIVE_RESIDUAL.value],
        )
    sp = trust_config.spatial
    spatial_diag = compute_spatial_diagnostics(
        pts_a, pts_b, model_result.inlier_mask, sp.grid_cells,
    )
    if spatial_diag.grid_cells_occupied < sp.min_occupied_cells:
        return TileTrustResult(
            tile_id=tile_id,
            trust_state=TileTrustState.REJECTED,
            reasons=[TrustReasonCode.TG_FAIL_LOW_SPATIAL_SUPPORT.value],
            model_result=model_result,
            spatial_diagnostics=spatial_diag,
            runtime_seconds=time.time() - t0,
        )
    if spatial_diag.concentration_ratio > sp.max_concentration_ratio:
        return TileTrustResult(
            tile_id=tile_id,
            trust_state=TileTrustState.REJECTED,
            reasons=[TrustReasonCode.TG_FAIL_LOW_SPATIAL_SUPPORT.value],
            model_result=model_result,
            spatial_diagnostics=spatial_diag,
            runtime_seconds=time.time() - t0,
        )
    cc_result = None
    if trust_config.cross_check.enabled:
        sym_errors = compute_symmetric_transfer(
            pts_a[model_result.inlier_mask],
            pts_b[model_result.inlier_mask],
            model_result.matrix,
        )
        max_sym = float(np.max(sym_errors))
        mean_sym = float(np.mean(sym_errors))
        cc_result = {
            "max_symmetric_transfer_px": round(max_sym, 4),
            "mean_symmetric_transfer_px": round(mean_sym, 4),
            "threshold_px": trust_config.cross_check.max_symmetric_transfer_px,
            "passed": max_sym <= trust_config.cross_check.max_symmetric_transfer_px,
        }
        if max_sym > trust_config.cross_check.max_symmetric_transfer_px:
            return TileTrustResult(
                tile_id=tile_id,
                trust_state=TileTrustState.REJECTED,
                reasons=[TrustReasonCode.TG_FAIL_CROSS_CHECK.value],
                model_result=model_result,
                spatial_diagnostics=spatial_diag,
                cross_check_result=cc_result,
                runtime_seconds=time.time() - t0,
            )
    reasons = [
        TrustReasonCode.TG_PASS_CANDIDATE_INTEGRITY.value,
        TrustReasonCode.TG_PASS_GEOMETRY.value,
        TrustReasonCode.TG_PASS_INLIERS.value,
        TrustReasonCode.TG_PASS_RESIDUAL_POLICY.value,
        TrustReasonCode.TG_PASS_SPATIAL_SUPPORT.value,
        TrustReasonCode.TG_PASS_DEGENERACY_CHECKS.value,
    ]
    if trust_config.cross_check.enabled:
        reasons.append(TrustReasonCode.TG_PASS_CROSS_CHECK.value)
    return TileTrustResult(
        tile_id=tile_id,
        trust_state=TileTrustState.TRUSTED,
        reasons=reasons,
        model_result=model_result,
        spatial_diagnostics=spatial_diag,
        cross_check_result=cc_result,
        runtime_seconds=time.time() - t0,
    )


def _fail_result(
    tile_id: str, t0: float, model_result: ModelResult, reasons: list[str],
) -> TileTrustResult:
    return TileTrustResult(
        tile_id=tile_id,
        trust_state=TileTrustState.REJECTED,
        reasons=reasons,
        model_result=model_result,
        runtime_seconds=time.time() - t0,
    )


def tile_to_dict(result: TileTrustResult) -> dict:
    return _to_dict(result)
