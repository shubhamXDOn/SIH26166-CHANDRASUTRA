"""M9 REGISTRATION — independent transform validation, diagnostics and acceptance.

MODEL ACCEPTANCE is deliberately separate from MODEL FIT. Residuals are computed
from scratch here (independent re-implementation), expressed in px of the
effective matcher plane, and annotated as geometric measurements — never
physical accuracy. All checks are engineering criteria from the configuration
snapshot; acceptance never tunes thresholds against a benchmark.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .config import RegistrationM9Config
from . import states


def apply_matrix(matrix: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Forward-map ``pts`` (N,2) by a 3x3 matrix with guarded homogeneous divide."""
    n = len(pts)
    h = np.ones((n, 3), dtype=np.float64)
    h[:, :2] = pts
    proj = (matrix @ h.T).T
    denom = proj[:, 2:3]
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    return proj[:, :2] / denom


def residual_vector_lengths(pts_a: np.ndarray, pts_b: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    mapped = apply_matrix(matrix, pts_a)
    return np.sqrt(np.sum((mapped - pts_b) ** 2, axis=1))


def residual_statistics(pts_a: np.ndarray, pts_b: np.ndarray, matrix: np.ndarray) -> dict[str, Any]:
    residuals = residual_vector_lengths(pts_a, pts_b, matrix)
    finite = residuals[np.isfinite(residuals)]
    stats: dict[str, Any] = {
        "count": int(len(residuals)),
        "finite_count": int(len(finite)),
        "unit": "px",
        "frame": "EFFECTIVE_MATCHER_PLANE",
    }
    if len(finite):
        stats.update({
            "mean": round(float(np.mean(finite)), 6),
            "median": round(float(np.median(finite)), 6),
            "rmse": round(float(np.sqrt(np.mean(finite ** 2))), 6),
            "p90": round(float(np.percentile(finite, 90)), 6),
            "p95": round(float(np.percentile(finite, 95)), 6),
            "max": round(float(np.max(finite)), 6),
            "min": round(float(np.min(finite)), 6),
        })
    else:
        stats.update({"mean": None, "median": None, "rmse": None,
                      "p90": None, "p95": None, "max": None, "min": None})
    if int(len(finite)) != int(len(residuals)):
        stats["note"] = "Some residuals were non-finite; statistics computed on the finite subset only."
    return stats


def _linear_part(matrix: np.ndarray) -> np.ndarray:
    return np.asarray(matrix)[:2, :2]


def _sv_of(matrix: np.ndarray) -> np.ndarray:
    return np.linalg.svd(_linear_part(matrix), compute_uv=False)


def transform_corner_extent(matrix: np.ndarray, dims: dict[str, Any]) -> dict[str, Any]:
    """Map the source frame corners forward and report the extent (diagnostic)."""
    height = float(dims.get("height") or 0)
    width = float(dims.get("width") or 0)
    corners = np.asarray([
        [0.0, 0.0], [width, 0.0], [width, height], [0.0, height],
    ], dtype=np.float64)
    mapped = apply_matrix(matrix, corners)
    return {
        "source_corners": corners.round(6).tolist(),
        "transformed_extent": {
            "min_x": round(float(np.min(mapped[:, 0])), 6),
            "max_x": round(float(np.max(mapped[:, 0])), 6),
            "min_y": round(float(np.min(mapped[:, 1])), 6),
            "max_y": round(float(np.max(mapped[:, 1])), 6),
        },
        "finite": bool(np.all(np.isfinite(mapped))),
        "note": "Geometric extent diagnostic in the effective matcher plane; not physical accuracy.",
    }


@dataclass
class ValidationOutcome:
    transform_valid: bool
    accepted: bool
    model_type: str
    matrix: np.ndarray
    residual_statistics: dict[str, Any] = field(default_factory=dict)
    reverse_statistics: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_registration_block(self) -> dict[str, Any]:
        checks = {k: bool(v) for k, v in self.checks.items()}
        return {
            "model_type": self.model_type,
            "algorithm": self.diagnostics.get("algorithm"),
            "transform_valid": bool(self.transform_valid),
            "accepted": bool(self.accepted),
            "selected_count": int(self.residual_statistics.get("count") or self.diagnostics.get("source_point_count") or 0),
            "transform_matrix": self.matrix.round(9).tolist(),
            "residual_statistics": self.residual_statistics,
            "reverse_residual_statistics": self.reverse_statistics,
            "checks": checks,
            "issues": list(self.issues),
            "diagnostics": self.diagnostics,
            "warnings": list(self.warnings),
        }


def check_transform(
    matrix: np.ndarray,
    model_type: str,
    cfg: RegistrationM9Config,
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    dims_a: dict[str, Any],
    dims_b: dict[str, Any],
) -> tuple[dict[str, bool], list[str], dict[str, Any]]:
    """Validate the transform matrix numerically. Returns (checks, issues, diagnostics)."""
    vc = cfg.validation
    checks: dict[str, bool] = {}
    issues: list[str] = []
    diag: dict[str, Any] = {"model_type": model_type}

    finite = bool(np.all(np.isfinite(matrix)))
    checks["matrix_finite"] = finite
    if not finite:
        issues.append("NON_FINITE_MATRIX")

    lin = _linear_part(matrix)
    det = float(np.linalg.det(lin)) if finite else None
    diag["determinant_linear_part"] = det
    det_ok = finite and det is not None and abs(det) >= vc.min_abs_determinant
    checks["determinant_threshold"] = bool(det_ok)
    if not det_ok:
        if det is None:
            issues.append("SINGULAR_OR_TINY_DETERMINANT: determinant not computable")
        else:
            issues.append(f"SINGULAR_OR_TINY_DETERMINANT: |det|={abs(det):.2e} < {vc.min_abs_determinant}")

    cond = None
    if finite:
        try:
            cond = float(np.linalg.cond(lin))
        except np.linalg.LinAlgError:
            cond = None
    diag["condition_number"] = cond
    checks["condition_threshold"] = bool(cond is not None and cond <= vc.max_transform_condition)
    if cond is None:
        issues.append("HIGH_TRANSFORM_CONDITION: condition not computable")
    elif cond > vc.max_transform_condition:
        issues.append(f"HIGH_TRANSFORM_CONDITION: {cond:.2e} > {vc.max_transform_condition}")

    sv = _sv_of(matrix) if finite else np.array([])
    diag["singular_values_linear_part"] = [float(v) for v in sv.tolist()] if sv.size else None
    if sv.size == 2:
        sv_min = float(sv[-1])
        sv_max = float(sv[0])
        diag["scale_range"] = {"min": sv_min, "max": sv_max}
        diag["anisotropy_ratio"] = float(sv_max / max(sv_min, 1e-12))
        if sv_min < vc.min_scale_factor:
            issues.append(f"SCALE_TOO_SMALL: min singular value {sv_min:.2e} < {vc.min_scale_factor}")
        if sv_max / max(sv_min, 1e-12) > vc.max_scale_change:
            diag["scale_change_exceeded"] = True
        else:
            diag["scale_change_exceeded"] = False
        if diag.get("anisotropy_ratio", 0.0) > 10.0:
            diag["shear_anisotropy"] = True
        else:
            diag["shear_anisotropy"] = False

    coef_max = float(np.max(np.abs(matrix))) if finite and matrix.size else None
    diag["max_abs_coefficient"] = coef_max
    checks["coefficient_magnitude"] = bool(coef_max is not None and coef_max <= vc.max_abs_coefficient)
    if coef_max is not None and coef_max > vc.max_abs_coefficient:
        issues.append(f"EXTREME_COEFFICIENT_MAGNITUDE: {coef_max:.2e} > {vc.max_abs_coefficient}")

    if model_type == states.HOMOGRAPHY and finite:
        src_corners = np.asarray([
            [0.0, 0.0], [float(dims_a.get("width") or 0), 0.0],
            [0.0, float(dims_a.get("height") or 0)],
            [float(dims_a.get("width") or 0), float(dims_a.get("height") or 0)],
        ], dtype=np.float64)
        denom_pts = np.vstack([pts_a, src_corners]) if len(pts_a) else src_corners
        h = np.ones((len(denom_pts), 3), dtype=np.float64)
        h[:, :2] = denom_pts
        proj = (matrix @ h.T).T
        denoms = np.abs(proj[:, 2])
        min_denom = float(np.min(denoms))
        diag["min_homography_denominator"] = min_denom
        checks["homography_denominator"] = bool(min_denom >= vc.min_homography_denominator)
        if min_denom < vc.min_homography_denominator:
            issues.append(f"HOMOGRAPHY_DENOMINATOR_UNSTABLE: min|denom|={min_denom:.2e}")

    extent = transform_corner_extent(matrix, dims_b)
    diag["transformed_source_extent"] = extent
    if not extent["finite"]:
        issues.append("TRANSFORM_EXPLODES_OUT_OF_FRAME")

    return checks, issues, diag


def validate_transform(
    matrix: np.ndarray,
    model_type: str,
    algorithm: str,
    cfg: RegistrationM9Config,
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    dims_a: dict[str, Any],
    dims_b: dict[str, Any],
) -> ValidationOutcome:
    """Independently validate the fit and judge acceptance."""
    warnings: list[str] = []
    checks, issues, diag = check_transform(matrix, model_type, cfg, pts_a, pts_b, dims_a, dims_b)
    diag = dict(diag)
    diag["algorithm"] = algorithm

    stats = residual_statistics(pts_a, pts_b, matrix)

    rev = np.full(len(pts_b), np.inf, dtype=np.float64)
    try:
        inv = np.linalg.inv(matrix)
        rev = residual_vector_lengths(pts_b, pts_a, inv)
    except np.linalg.LinAlgError:
        issues.append("INVERSE_TRANSFORM_FAILED")
    finite_rev = rev[np.isfinite(rev)]
    reverse_stats: dict[str, Any] = {
        "count": int(len(rev)), "finite_count": int(len(finite_rev)),
        "unit": "px", "frame": "EFFECTIVE_MATCHER_PLANE",
    }
    if len(finite_rev):
        reverse_stats.update({
            "mean": round(float(np.mean(finite_rev)), 6),
            "median": round(float(np.median(finite_rev)), 6),
            "rmse": round(float(np.sqrt(np.mean(finite_rev ** 2))), 6),
            "p95": round(float(np.percentile(finite_rev, 95)), 6),
            "max": round(float(np.max(finite_rev)), 6),
            "min": round(float(np.min(finite_rev)), 6),
        })

    checks["rmse_threshold"] = bool(stats.get("rmse") is not None and stats["rmse"] <= cfg.validation.max_rmse_px)
    if not checks["rmse_threshold"]:
        issues.append(f"RMSE_HIGH: {stats.get('rmse')} > {cfg.validation.max_rmse_px} px")
    checks["p95_threshold"] = bool(stats.get("p95") is not None and stats["p95"] <= cfg.validation.max_p95_px)
    if not checks["p95_threshold"]:
        issues.append(f"P95_HIGH: {stats.get('p95')} > {cfg.validation.max_p95_px} px")
    checks["max_threshold"] = bool(stats.get("max") is not None and stats["max"] <= cfg.validation.max_residual_max_px)
    if not checks["max_threshold"]:
        issues.append(f"RESIDUAL_MAX_HIGH: {stats.get('max')} > {cfg.validation.max_residual_max_px} px")
    checks["residuals_finite"] = stats.get("finite_count") == stats.get("count")

    if diag.get("scale_change_exceeded"):
        warnings.append(states.SCALE_CHANGE_LARGE)
    if diag.get("shear_anisotropy"):
        warnings.append(states.SHEAR_ANISOTROPY)

    transform_valid = bool(all(checks.values()))
    accepted = bool(transform_valid and not issues)
    return ValidationOutcome(
        transform_valid=transform_valid,
        accepted=accepted,
        model_type=model_type,
        matrix=matrix,
        residual_statistics=stats,
        reverse_statistics=reverse_stats,
        checks=checks,
        issues=list(issues),
        diagnostics=diag,
        warnings=warnings,
    )


__all__ = [
    "ValidationOutcome",
    "apply_matrix",
    "check_transform",
    "residual_statistics",
    "validate_transform",
]