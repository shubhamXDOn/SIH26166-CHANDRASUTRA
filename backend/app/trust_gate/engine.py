"""M7 TRUST GATE — pure geometric verification engine.

Deterministic by construction:
- coordinates are verified to be finite and in the declared matcher plane;
- exact duplicate mappings are counted (never silently destroyed);
- source/target degeneracy is checked BEFORE any fit;
- the smallest technically defensible model from the configured hierarchy is
  fitted with seeded RANSAC over numpy DLT (reusing trust/geometry.py);
- a valid technical fit is NEVER promoted merely because the smaller model
  fails an acceptance threshold (no threshold-tuned model shopping);
- residual statistics are computed in pixels, in the effective matcher plane.

Output is a JSON-safe evidence + decision dict. No I/O, no M8 selection, no M9
registration semantics.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from backend.app.trust.config import RansacConfig
from backend.app.trust.geometry import (
    _check_degeneracy,
    _compute_residuals_forward,
    estimate_affine,
    estimate_homography,
)

from . import states
from .config import TrustGateConfig


def _fmt(value: float) -> float:
    return round(float(value), 9)


def _residual_statistics(residuals: np.ndarray, units: str) -> dict[str, Any]:
    if residuals is None or len(residuals) == 0:
        return {
            "count": 0, "mean": None, "median": None, "rmse": None,
            "p90": None, "p95": None, "max": None, "min": None,
            "units": units,
        }
    r = np.asarray(residuals, dtype=np.float64)
    rmse = float(np.sqrt(np.mean(r ** 2)))
    d: dict[str, Any] = {
        "count": int(len(r)),
        "mean": _fmt(float(np.mean(r))),
        "median": _fmt(float(np.median(r))),
        "rmse": _fmt(rmse),
        "p90": _fmt(float(np.percentile(r, 90))),
        "p95": _fmt(float(np.percentile(r, 95))),
        "max": _fmt(float(np.max(r))),
        "min": _fmt(float(np.min(r))),
        "units": units,
    }
    return d


def _deduplicate(coords: np.ndarray) -> tuple[np.ndarray, dict[str, int]]:
    """Drop exact duplicate (a->b) mappings, counting them (never silent)."""
    n = len(coords)
    seen: dict[tuple, int] = {}
    first_idx: list[int] = []
    for i in range(n):
        key = (
            round(float(coords[i, 0]), 6), round(float(coords[i, 1]), 6),
            round(float(coords[i, 2]), 6), round(float(coords[i, 3]), 6),
        )
        if key not in seen:
            seen[key] = i
            first_idx.append(i)
    source_counts: dict[tuple, int] = {}
    target_counts: dict[tuple, int] = {}
    for i in range(n):
        key_a = (round(float(coords[i, 0]), 6), round(float(coords[i, 1]), 6))
        key_b = (round(float(coords[i, 2]), 6), round(float(coords[i, 3]), 6))
        source_counts[key_a] = source_counts.get(key_a, 0) + 1
        target_counts[key_b] = target_counts.get(key_b, 0) + 1
    source_sharing = sum(1 for c in source_counts.values() if c > 1)
    target_sharing = sum(1 for c in target_counts.values() if c > 1)
    return coords[first_idx], {
        "candidate_count": n,
        "deduplicated_candidate_count": int(len(first_idx)),
        "exact_duplicate_count": int(n - len(first_idx)),
        "source_sharing_points": source_sharing,
        "target_sharing_points": target_sharing,
    }


def _spatial_sanity(
    inlier_a: np.ndarray,
    inlier_b: np.ndarray,
    cfg: TrustGateConfig,
) -> dict[str, Any]:
    if inlier_a is None or len(inlier_a) == 0:
        return {
            "state": states.SPATIAL_FAIL,
            "reasons": ["NO_INLIERS"],
            "bbox_a": None, "bbox_b": None,
        }

    def extent(pts: np.ndarray, label: str) -> dict[str, Any]:
        xs = pts[:, 0]
        ys = pts[:, 1]
        span_x = float(np.max(xs) - np.min(xs))
        span_y = float(np.max(ys) - np.min(ys))
        diag = math.hypot(span_x, span_y)
        return {
            label: {
                "bbox_x": [_fmt(float(np.min(xs))), _fmt(float(np.max(xs)))],
                "bbox_y": [_fmt(float(np.min(ys))), _fmt(float(np.max(ys)))],
                "span_x_px": _fmt(span_x),
                "span_y_px": _fmt(span_y),
                "extent_diag_px": _fmt(diag),
            }
        }

    ext_a = extent(inlier_a, "a")
    ext_b = extent(inlier_b, "b")
    min_extent = float(cfg.spatial_sanity.min_extent_px)
    strip_ratio = float(cfg.spatial_sanity.strip_ratio_warn)
    reasons: list[str] = []
    state = states.SPATIAL_PASS

    for block in (ext_a["a"], ext_b["b"]):
        diag = float(block["extent_diag_px"])
        span_x = float(block["span_x_px"])
        span_y = float(block["span_y_px"])
        if diag < min_extent:
            state = states.SPATIAL_FAIL
            reasons.append("INSUFFICIENT_SPATIAL_EXTENT")
            break
        larger = max(span_x, span_y)
        if larger > 1e-9 and min(span_x, span_y) < strip_ratio * larger:
            if "CONCENTRATED_STRIP" not in reasons:
                reasons.append("CONCENTRATED_STRIP")
                state = states.SPATIAL_WARN
    return {"state": state, "reasons": reasons, **ext_a, **ext_b}


def _degeneracy(pts_a: np.ndarray, pts_b: np.ndarray, cfg: TrustGateConfig) -> tuple[bool, list[str]]:
    flags: list[str] = []
    flags += [f"SOURCE_{f}" for f in _check_degeneracy(
        pts_a, min_unique=cfg.degeneracy.min_unique_points,
        max_cond=cfg.degeneracy.max_condition_number,
    )]
    flags += [f"TARGET_{f}" for f in _check_degeneracy(
        pts_b, min_unique=cfg.degeneracy.min_unique_points,
        max_cond=cfg.degeneracy.max_condition_number,
    )]
    return len(flags) > 0, flags


def _fit_once(
    model_type: str,
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    cfg: TrustGateConfig,
) -> dict[str, Any]:
    ransac = RansacConfig(
        max_iterations=cfg.geometry.ransac.max_iterations,
        inlier_threshold_px=cfg.geometry.ransac.inlier_threshold_px,
        confidence=cfg.geometry.ransac.confidence_parameter,
        seed=cfg.geometry.ransac.seed,
    )
    if model_type == "homography":
        result = estimate_homography(pts_a, pts_b, ransac)
    else:
        result = estimate_affine(pts_a, pts_b, ransac)

    matrix: np.ndarray | None = result.matrix
    valid = matrix is not None and _matrix_valid(matrix)
    inlier_res = np.array([])
    if valid and matrix is not None and result.inlier_count > 0:
        residuals_all = _compute_residuals_forward(pts_a, pts_b, matrix)
        inlier_res = residuals_all[result.inlier_mask]
    stats = _residual_statistics(inlier_res, "px in effective matcher plane")
    return {
        "model_type": model_type,
        "algorithm": "DLT_RANSAC_NUMPY_SEEDED",
        "matrix": _matrix_list(matrix),
        "model_valid": valid,
        "inlier_count": int(result.inlier_count),
        "outlier_count": int(result.outlier_count),
        "inlier_ratio": _fmt(result.inlier_ratio),
        "iterations_used": int(result.iterations_used),
        "seed_used": int(result.seed_used),
        "degeneracy_flags": list(result.degeneracy_flags),
        "residual_statistics": stats,
        "confidence_parameter": float(cfg.geometry.ransac.confidence_parameter),
        "inlier_threshold_px": float(cfg.geometry.ransac.inlier_threshold_px),
        "max_iterations": int(cfg.geometry.ransac.max_iterations),
    }


def _matrix_valid(matrix: np.ndarray | None) -> bool:
    if matrix is None:
        return False
    if np.any(np.isnan(matrix)) or np.any(np.isinf(matrix)):
        return False
    lin = matrix[:2, :2]
    if abs(np.linalg.det(lin)) < 1e-8:
        return False
    try:
        if float(np.linalg.cond(lin)) > 1e10:
            return False
    except np.linalg.LinAlgError:
        return False
    return True


def _matrix_list(matrix: np.ndarray | None) -> list[list[float]] | None:
    if matrix is None:
        return None
    return [[_fmt(float(v)) for v in row] for row in matrix]


def _choose_model(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    cfg: TrustGateConfig,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Fit the hierarchy; keep the FIRST technically valid model (smallest first)."""
    preferred = cfg.geometry.preferred_model
    models = list(cfg.geometry.models)
    if preferred in models and models[0] != preferred:
        models = [preferred] + [m for m in models if m != preferred]

    attempts: list[dict[str, Any]] = []
    for model_type in models:
        fit = _fit_once(model_type, pts_a, pts_b, cfg)
        attempts.append(fit)
        if fit["model_valid"]:
            # first technically valid model wins (smallest first). A valid
            # smaller model is never promoted because it fails acceptance.
            return fit, attempts
        if fit["degeneracy_flags"] and fit["matrix"] is None:
            continue
        if not cfg.geometry.attempt_hierarchy:
            break
    return None, attempts


def verify(
    coords: np.ndarray | None,
    cfg: TrustGateConfig,
) -> dict[str, Any]:
    """Run the geometric verification gate. Returns the evidence + decision.

    ``coords`` is an (N,4) array of finite [x_a, y_a, x_b, y_b] in the declared
    effective matcher plane, or None when the run carried no correspondences.
    """
    units = "px in effective matcher plane"

    if coords is None or len(coords) == 0:
        return _decision_out(
            states.ABSTAIN,
            states.ZERO_CANDIDATES,
            "No candidate correspondences were present to verify.",
            _empty_evidence(),
        )

    total = int(len(coords))
    finite = int(np.isfinite(coords).all(axis=1).sum())
    if finite != total:
        bad = total - finite
        return _decision_out(
            states.BLOCKED,
            states.INVALID_INPUT,
            f"{bad} of {total} candidate coordinates were NaN/Inf; refusing to verify.",
            _empty_evidence() | {"candidate_count": total, "verified_count": finite,
                                  "non_finite_count": bad, "residual_units": units},
        )

    if total > cfg.resource.max_candidates:
        return _decision_out(
            states.ABSTAIN,
            states.RESOURCE_LIMIT,
            f"Candidate count {total} exceeds the declared resource cap "
            f"{cfg.resource.max_candidates}; refusing (recorded, not silently truncated).",
            {
                **_base_evidence(total, total, _DUP_UNKNOWN, units),
                "inlier_count": 0, "outlier_count": total, "inlier_ratio": 0.0,
                "degeneracy": {"detected": None, "flags": []},
            },
        )

    dedup, dup_counts = _deduplicate(coords)
    verified = len(dedup)

    if verified < cfg.decision.min_candidates:
        return _decision_out(
            states.ABSTAIN,
            states.INSUFFICIENT_CANDIDATES,
            f"Only {verified} usable candidate correspondences after deduplication "
            f"(minimum {cfg.decision.min_candidates}).",
            _base_evidence(total, verified, dup_counts, units),
        )

    pts_a = dedup[:, :2]
    pts_b = dedup[:, 2:]

    degeneracy_detected, degeneracy_flags = _degeneracy(pts_a, pts_b, cfg)
    if degeneracy_detected:
        return _decision_out(
            states.ABSTAIN,
            states.DEGENERATE_GEOMETRY,
            f"Degenerate geometry detected: {', '.join(degeneracy_flags)}.",
            {
                **_base_evidence(total, verified, dup_counts, units),
                "inlier_count": 0, "outlier_count": verified, "inlier_ratio": 0.0,
                "model": None, "model_attempts": [],
                "residual_statistics": _residual_statistics(np.array([]), units),
                "spatial_sanity": None,
                "degeneracy": {"detected": True, "flags": degeneracy_flags,
                               "reason": "collinear or insufficiently distinct points"},
            },
        )

    final_model, attempts = _choose_model(pts_a, pts_b, cfg)

    if final_model is None:
        det_flags = de_flags_final(
            [f for a in attempts for f in a.get("degeneracy_flags", [])]
        )
        return _decision_out(
            states.ABSTAIN,
            states.NO_VALID_MODEL,
            "No geometrically valid model could be fitted from the candidate set.",
            {
                **_base_evidence(total, verified, dup_counts, units),
                "inlier_count": 0, "outlier_count": verified, "inlier_ratio": 0.0,
                "model": None, "model_attempts": attempts,
                "residual_statistics": _residual_statistics(np.array([]), units),
                "spatial_sanity": None,
                "degeneracy": {"detected": len(det_flags) > 0, "flags": det_flags,
                               "reason": "model fitting failed"},
            },
        )

    matrix = _to_np(final_model.get("matrix"))
    residuals_all = _compute_residuals_forward(pts_a, pts_b, matrix)
    mask = residuals_all < float(cfg.geometry.ransac.inlier_threshold_px)
    inlier_a = pts_a[mask]
    inlier_b = pts_b[mask]
    inlier_count = int(np.sum(mask))
    outlier_count = verified - inlier_count
    inlier_ratio = (inlier_count / verified) if verified > 0 else 0.0

    model_evidence = {
        "model_type": final_model["model_type"],
        "model_algorithm": final_model.get("algorithm"),
        "model_parameters": {
            "models": list(cfg.geometry.models),
            "preferred_model": cfg.geometry.preferred_model,
            "inlier_threshold_px": final_model.get("inlier_threshold_px"),
            "max_iterations": final_model.get("max_iterations"),
            "confidence_parameter": final_model.get("confidence_parameter"),
            "seed_used": final_model.get("seed_used"),
            "iterations_used": final_model.get("iterations_used"),
        },
        "model_matrix": final_model.get("matrix"),
        "model_valid": final_model.get("model_valid"),
        "determinant_linear_part": _fmt(float(np.linalg.det(matrix[:2, :2]))),
    }

    stats = _residual_statistics(residuals_all[mask], units)
    spatial = _spatial_sanity(inlier_a, inlier_b, cfg)

    dec_cfg = cfg.decision
    reasons: list[str] = []
    accept = True
    if inlier_count < dec_cfg.min_inliers:
        accept = False
        reasons.append(states.INSUFFICIENT_INLIERS)
    if inlier_ratio < dec_cfg.min_inlier_ratio:
        accept = False
        reasons.append(states.LOW_INLIER_RATIO)
    if not (stats.get("rmse") is not None and float(stats["rmse"]) <= dec_cfg.max_residual_rmse_px
            and float(stats["median"]) <= dec_cfg.max_residual_median_px
            and float(stats["p95"]) <= dec_cfg.max_residual_p95_px):
        accept = False
        reasons.append(states.RESIDUAL_EXCEEDED)
    if spatial.get("state") == states.SPATIAL_FAIL:
        accept = False
        reasons.append(states.SPATIAL_SANITY_FAILED)

    if accept:
        reasons = ["CANDIDATE_COUNT_OK", "DEGENERACY_OK", "MODEL_VALID",
                   "INLIER_MIN_OK", "INLIER_RATIO_OK", "RESIDUAL_OK",
                   "SPATIAL_SANITY_OK"]
        state = states.ACCEPT
    else:
        state = states.REJECT

    explanation = _explanation(
        state, reasons, total, verified, inlier_count, inlier_ratio,
        stats, final_model.get("model_type"), spatial.get("state"),
        degeneracy_detected and degeneracy_flags or [],
    )

    evidence = {
        **_base_evidence(total, verified, dup_counts, units),
        "inlier_count": int(inlier_count),
        "outlier_count": int(outlier_count),
        "inlier_ratio": _fmt(inlier_ratio),
        "model": model_evidence,
        "model_attempts": attempts,
        "residual_statistics": stats,
        "spatial_sanity": spatial,
        "degeneracy": {"detected": False, "flags": [], "reason": None},
    }
    return {"decision": {
        "state": state,
        "reasons": reasons,
        "explanation": explanation,
        "block_code": None,
        "abstain_code": None,
    }, "evidence": evidence, "decision_hash": None}


def de_flags_final(flags: list[str]) -> list[str]:
    return list(dict.fromkeys(flags))


def _to_np(m: list[list[float]] | None) -> np.ndarray:
    if m is None:
        raise ValueError("model matrix unavailable")
    return np.asarray(m, dtype=np.float64)


def _base_evidence(total: int, verified: int, dup_counts: dict[str, int], units: str) -> dict[str, Any]:
    return {
        "candidate_count": int(total),
        "verified_count": int(verified),
        **dup_counts,
        "inlier_count": None,
        "outlier_count": None,
        "inlier_ratio": None,
        "model": None,
        "model_attempts": [],
        "residual_statistics": _residual_statistics(np.array([]), units),
        "spatial_sanity": None,
        "degeneracy": {"detected": None, "flags": []},
    }


def _empty_evidence() -> dict[str, Any]:
    return _base_evidence(0, 0, _DUP_ZEROS, "px in effective matcher plane")


_DUP_ZEROS: dict[str, int] = {
    "deduplicated_candidate_count": 0,
    "exact_duplicate_count": 0,
    "source_sharing_points": 0,
    "target_sharing_points": 0,
}

_DUP_UNKNOWN: dict[str, Any] = {
    "deduplicated_candidate_count": None,
    "exact_duplicate_count": None,
    "source_sharing_points": None,
    "target_sharing_points": None,
}


def _decision_out(
    state: str,
    code: str | None,
    explanation: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "decision": {
            "state": state,
            "reasons": [code] if code else [],
            "explanation": explanation,
            "block_code": code if state == states.BLOCKED else None,
            "abstain_code": code if state == states.ABSTAIN else None,
        },
        "evidence": evidence,
        "decision_hash": None,
    }


def _explanation(
    state: str,
    reasons: list[str],
    candidate_count: int,
    verified_count: int,
    inlier_count: int,
    inlier_ratio: float,
    stats: dict[str, Any],
    model_type: str | None,
    spatial_state: str | None,
    degeneracy_flags: list[str],
) -> str:
    if state == states.ACCEPT:
        med = stats.get("median")
        p95 = stats.get("p95")
        rmse = stats.get("rmse")
        return (
            f"ACCEPT because: candidate_count={candidate_count}, "
            f"inlier_count={inlier_count}, inlier_ratio={inlier_ratio:.3f}, "
            f"median residual={med} px, p95 residual={p95} px, rmse={rmse} px, "
            f"model={model_type}, degeneracy=false, spatial_sanity={spatial_state}."
        )
    if state == states.REJECT:
        return (
            f"REJECT because: candidate_count={candidate_count}, "
            f"inlier_count={inlier_count}, inlier_ratio={inlier_ratio:.3f}, "
            f"model={model_type}, failed gates: {', '.join(reasons)}."
        )
    if state == states.ABSTAIN:
        return f"ABSTAIN because: {', '.join(reasons)}."
    return f"BLOCKED because: {', '.join(reasons)}."