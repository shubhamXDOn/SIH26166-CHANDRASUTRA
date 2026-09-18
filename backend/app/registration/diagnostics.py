"""M6 diagnostics: JSON-safe serialization of the registration result."""

from __future__ import annotations

import numpy as np

from backend.app.registration.engine import RegistrationResult, TransformDiagnostics
from backend.app.trust.geometry import (
    _compute_residuals_forward,
    compute_symmetric_transfer,
)


def diagnostics_to_dict(
    result: RegistrationResult,
    n_finite_correspondences: int,
    n_total_correspondences: int,
) -> dict:
    diag: TransformDiagnostics = result.transform_diagnostics
    return {
        "transform_type": result.transform_type.value,
        "selection_reason": result.selection_reason.value,
        "correspondences": {
            "selected_total": n_total_correspondences,
            "finite_usable": n_finite_correspondences,
            "valid_for_fit": diag.total_correspondences,
            "inliers": diag.inlier_count,
            "outliers": diag.outlier_count,
            "inlier_ratio": round(diag.inlier_ratio, 6),
        },
        "residuals": {
            "mean_px": round(diag.residual_mean, 6),
            "median_px": round(diag.residual_median, 6),
            "p95_px": round(diag.residual_p95, 6),
            "max_px": round(diag.residual_max, 6),
        },
        "symmetric_transfer": {
            "mean_px": round(diag.symmetric_transfer_mean, 6),
            "max_px": round(diag.symmetric_transfer_max, 6),
            "passed": bool(result.validation.checks.get("symmetric_transfer", None)),
        },
        "numerics": {
            "determinant": diag.determinant,
            "condition_number": diag.condition_number,
            "degeneracy_flags": list(diag.degeneracy_flags),
            "iterations_used": diag.iterations_used,
            "seed_used": diag.seed_used,
        },
        "matrix": _matrix_safe(diag.matrix),
        "runtime_seconds": round(result.runtime_seconds, 4),
        "error": result.error,
    }


def _matrix_safe(matrix) -> list[list[float]] | None:
    import numpy as np

    if matrix is None:
        return None
    m = np.asarray(matrix, dtype=np.float64)
    return [[round(float(v), 10) for v in row] for row in m.tolist()]


def validation_to_dict(result: RegistrationResult) -> dict:
    v = result.validation
    return {
        "verdict": v.verdict.value,
        "checks": v.checks,
        "issues": list(v.issues),
    }


def build_independent_check(result: RegistrationResult) -> dict:
    """Recompute residuals and symmetric transfer on the fitted matrix.

    Deliberately recomputes from the trusted M4 primitives instead of trusting
    the fit package's own error metric, so the validation JSON can truthfully
    report that checks were re-derived rather than copied.
    """
    matrix = result.transform_matrix
    pts_a = np.asarray(result.pts_a_sensor)
    pts_b = np.asarray(result.pts_b_sensor)
    if matrix is None or len(pts_a) == 0:
        return {
            "recomputed": False,
            "status": "NOT_APPLICABLE",
            "reason": result.error or "no fitted matrix or no correspondence points",
            "residual_mean_px": None,
            "residual_median_px": None,
            "residual_p95_px": None,
            "symmetric_transfer_max_px": None,
            "consistent_with_fit": None,
        }

    res = _compute_residuals_forward(pts_a, pts_b, matrix)
    sym = compute_symmetric_transfer(pts_a, pts_b, matrix)
    inlier_local = np.asarray(result.transform_diagnostics.inlier_mask, dtype=bool)
    finite = np.isfinite(res)

    def _stat(values):
        vals = values[finite]
        if vals.size == 0:
            return None
        return round(float(np.mean(vals)), 6), round(float(np.median(vals)), 6), round(float(np.percentile(vals, 95)), 6)

    inlier_stats = _stat(res[inlier_local]) if np.any(inlier_local) else None
    sym_max = float(np.max(sym)) if np.isfinite(sym).any() else None

    diag = result.transform_diagnostics
    tol = 1e-3
    consistent = (
        inlier_stats is not None
        and np.isfinite(diag.residual_mean)
        and abs(inlier_stats[0] - abs(diag.residual_mean)) <= tol * max(1.0, abs(diag.residual_mean))
    )
    return {
        "recomputed": True,
        "status": "COMPUTED",
        "method": "recompute on fitted matrix using M4 trust primitives",
        "residual_mean_px": inlier_stats[0] if inlier_stats else None,
        "residual_median_px": inlier_stats[1] if inlier_stats else None,
        "residual_p95_px": inlier_stats[2] if inlier_stats else None,
        "residual_all_point_count": int(np.sum(inlier_local)),
        "symmetric_transfer_max_px": sym_max,
        "consistent_with_fit": bool(consistent),
        "note": "Independent recomputation of the fitted-matrix error; not a physical truth claim.",
    }