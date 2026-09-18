"""M6 registration engine: transform fitting + validation.

Fits homography (preferred) or affine (fallback) from selected correspondences,
validates the result, and returns a RegistrationResult with full diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.app.registration.config import RegistrationConfig
from backend.app.registration.states import (
    RegistrationValidationVerdict,
    TransformSelectionReason,
    TransformType,
)
from backend.app.trust.config import RansacConfig
from backend.app.trust.geometry import (
    _compute_residuals_forward,
    compute_symmetric_transfer,
    estimate_affine,
    estimate_homography,
    validate_model_matrix,
)


@dataclass
class TransformDiagnostics:
    matrix_type: str
    matrix: np.ndarray | None
    inlier_mask: np.ndarray
    inlier_count: int
    outlier_count: int
    total_correspondences: int
    inlier_ratio: float
    residual_mean: float
    residual_median: float
    residual_p95: float
    residual_max: float
    symmetric_transfer_mean: float
    symmetric_transfer_max: float
    condition_number: float | None
    determinant: float | None
    degeneracy_flags: list[str]
    iterations_used: int
    seed_used: int


@dataclass
class ValidationResult:
    verdict: RegistrationValidationVerdict
    checks: dict[str, bool]
    issues: list[str]


@dataclass
class RegistrationResult:
    transform_type: TransformType
    selection_reason: TransformSelectionReason
    transform_matrix: np.ndarray | None
    transform_diagnostics: TransformDiagnostics
    validation: ValidationResult
    pts_a_sensor: np.ndarray
    pts_b_sensor: np.ndarray
    valid_mask: np.ndarray
    runtime_seconds: float = 0.0
    error: str | None = None


def fit_and_validate(
    pts_a_x: np.ndarray,
    pts_a_y: np.ndarray,
    pts_b_x: np.ndarray,
    pts_b_y: np.ndarray,
    valid_mask: np.ndarray,
    cfg: RegistrationConfig,
    t_start: float = 0.0,
    max_runtime: float = 120.0,
) -> RegistrationResult:
    import time

    valid_idx = np.where(valid_mask)[0]
    n_valid = len(valid_idx)
    pts_a = np.column_stack([pts_a_x[valid_mask], pts_a_y[valid_mask]])
    pts_b = np.column_stack([pts_b_x[valid_mask], pts_b_y[valid_mask]])

    if n_valid < 4:
        return _error_result(
            "INSUFFICIENT_EVIDENCE",
            pts_a_x, pts_a_y, pts_b_x, pts_b_y, valid_mask, t_start,
            "Need at least 4 valid correspondences for homography.",
        )

    ransac_cfg = RansacConfig(
        max_iterations=cfg.transform.ransac_max_iterations,
        inlier_threshold_px=cfg.transform.ransac_inlier_threshold_px,
        seed=cfg.transform.ransac_seed,
    )

    homography_result = estimate_homography(pts_a, pts_b, ransac_cfg)
    use_homography = True
    fallback_reason = TransformSelectionReason.PREFERRED
    model_type_str = "homography"

    if homography_result.matrix is None:
        if cfg.transform.affine_fallback:
            use_homography = False
            fallback_reason = TransformSelectionReason.FALLBACK_DEGENERATE
            model_type_str = "affine"
        else:
            return _error_result(
                "HOMOGRAPHY_FIT_FAILED",
                pts_a_x, pts_a_y, pts_b_x, pts_b_y, valid_mask, t_start,
                "Homography fit failed and affine fallback disabled.",
            )
    elif (homography_result.inlier_count < cfg.transform.min_inliers_for_homography or
          homography_result.inlier_ratio < cfg.transform.min_inlier_ratio_for_homography):
        if cfg.transform.affine_fallback:
            use_homography = False
            fallback_reason = TransformSelectionReason.FALLBACK_INSUFFICIENT_INLIERS
            model_type_str = "affine"
        else:
            return _error_result(
                "HOMOGRAPHY_INSUFFICIENT_INLIERS",
                pts_a_x, pts_a_y, pts_b_x, pts_b_y, valid_mask, t_start,
                f"Homography inliers={homography_result.inlier_count} below threshold.",
            )

    if use_homography:
        chosen = homography_result
    else:
        if t_start > 0 and time.time() - t_start >= max_runtime:
            return _error_result(
                "TIMEOUT",
                pts_a_x, pts_a_y, pts_b_x, pts_b_y, valid_mask, t_start,
                "Runtime limit reached before affine fitting.",
            )
        chosen = estimate_affine(pts_a, pts_b, ransac_cfg)

    if chosen.matrix is None:
        return _error_result(
            f"{model_type_str.upper()}_FIT_FAILED",
            pts_a_x, pts_a_y, pts_b_x, pts_b_y, valid_mask, t_start,
            f"Both preferred and fallback model fitting failed.",
        )

    valid_model, model_issues = validate_model_matrix(chosen.matrix, model_type_str)
    if not valid_model:
        return _error_result(
            "MODEL_INVALID",
            pts_a_x, pts_a_y, pts_b_x, pts_b_y, valid_mask, t_start,
            f"Model validation failed: {model_issues}",
        )

    res = _compute_residuals_forward(pts_a, pts_b, chosen.matrix)
    inlier_mask_local = np.asarray(chosen.inlier_mask, dtype=bool)

    sym = compute_symmetric_transfer(pts_a, pts_b, chosen.matrix)

    det_val = None
    cond_val = None
    if chosen.matrix is not None:
        lin = chosen.matrix[:2, :2]
        try:
            det_val = float(np.linalg.det(lin))
        except np.linalg.LinAlgError:
            det_val = None
        try:
            cond_val = float(np.linalg.cond(lin))
        except np.linalg.LinAlgError:
            cond_val = None

    residual_mean = float(np.mean(res[inlier_mask_local])) if np.any(inlier_mask_local) else float("inf")
    residual_median = float(np.median(res[inlier_mask_local])) if np.any(inlier_mask_local) else float("inf")
    residual_p95 = float(np.percentile(res[inlier_mask_local], 95)) if np.any(inlier_mask_local) else float("inf")
    residual_max = float(np.max(res[inlier_mask_local])) if np.any(inlier_mask_local) else float("inf")

    diagnostics = TransformDiagnostics(
        matrix_type=model_type_str,
        matrix=chosen.matrix,
        inlier_mask=inlier_mask_local,
        inlier_count=int(np.sum(inlier_mask_local)),
        outlier_count=int(np.sum(~inlier_mask_local)),
        total_correspondences=n_valid,
        inlier_ratio=float(np.sum(inlier_mask_local)) / n_valid if n_valid > 0 else 0.0,
        residual_mean=round(residual_mean, 6),
        residual_median=round(residual_median, 6),
        residual_p95=round(residual_p95, 6),
        residual_max=round(residual_max, 6),
        symmetric_transfer_mean=round(float(np.mean(sym)), 6),
        symmetric_transfer_max=round(float(np.max(sym)), 6),
        condition_number=round(cond_val, 6) if cond_val is not None else None,
        determinant=round(det_val, 8) if det_val is not None else None,
        degeneracy_flags=list(chosen.degeneracy_flags),
        iterations_used=chosen.iterations_used,
        seed_used=chosen.seed_used,
    )

    checks, issues = _validate_result(diagnostics, cfg)
    verdict = RegistrationValidationVerdict.PASS
    if issues:
        verdict = RegistrationValidationVerdict.FAIL
    if diagnostics.inlier_count < cfg.validation.min_inliers:
        verdict = RegistrationValidationVerdict.INSUFFICIENT

    validation = ValidationResult(verdict=verdict, checks=checks, issues=issues)

    return RegistrationResult(
        transform_type=TransformType(model_type_str.upper()),
        selection_reason=fallback_reason,
        transform_matrix=chosen.matrix,
        transform_diagnostics=diagnostics,
        validation=validation,
        pts_a_sensor=np.column_stack([pts_a_x[valid_mask], pts_a_y[valid_mask]]),
        pts_b_sensor=np.column_stack([pts_b_x[valid_mask], pts_b_y[valid_mask]]),
        valid_mask=valid_mask,
        runtime_seconds=round(time.time() - t_start, 4),
    )


def _validate_result(
    diag: TransformDiagnostics,
    cfg: RegistrationConfig,
) -> tuple[dict[str, bool], list[str]]:
    vc = cfg.validation
    checks: dict[str, bool] = {}
    issues: list[str] = []

    checks["min_inliers"] = diag.inlier_count >= vc.min_inliers
    if not checks["min_inliers"]:
        issues.append(f"INLIERS_LOW: {diag.inlier_count} < {vc.min_inliers}")

    checks["min_inlier_ratio"] = diag.inlier_ratio >= vc.min_inlier_ratio
    if not checks["min_inlier_ratio"]:
        issues.append(f"INLIER_RATIO_LOW: {diag.inlier_ratio:.4f} < {vc.min_inlier_ratio}")

    checks["residual_mean"] = diag.residual_mean <= vc.max_residual_mean_px
    if not checks["residual_mean"]:
        issues.append(f"RESIDUAL_MEAN_HIGH: {diag.residual_mean:.4f} > {vc.max_residual_mean_px}")

    checks["residual_median"] = diag.residual_median <= vc.max_residual_median_px
    if not checks["residual_median"]:
        issues.append(f"RESIDUAL_MEDIAN_HIGH: {diag.residual_median:.4f} > {vc.max_residual_median_px}")

    checks["residual_p95"] = diag.residual_p95 <= vc.max_residual_p95_px
    if not checks["residual_p95"]:
        issues.append(f"RESIDUAL_P95_HIGH: {diag.residual_p95:.4f} > {vc.max_residual_p95_px}")

    checks["symmetric_transfer"] = diag.symmetric_transfer_max <= vc.max_symmetric_transfer_px
    if not checks["symmetric_transfer"]:
        issues.append(f"SYMMETRIC_TRANSFER_HIGH: {diag.symmetric_transfer_max:.4f} > {vc.max_symmetric_transfer_px}")

    if vc.check_determinant and diag.determinant is not None:
        checks["determinant"] = abs(diag.determinant) >= vc.min_abs_determinant
        if not checks["determinant"]:
            issues.append(f"SINGULAR_MATRIX: |det|={abs(diag.determinant):.2e} < {vc.min_abs_determinant}")

    if diag.condition_number is not None:
        checks["condition_number"] = diag.condition_number <= vc.max_condition_number
        if not checks["condition_number"]:
            issues.append(f"HIGH_CONDITION: {diag.condition_number:.2e} > {vc.max_condition_number}")

    checks["no_model_issues"] = len(diag.degeneracy_flags) == 0
    if diag.degeneracy_flags:
        issues.append(f"DEGENERACY_FLAGS: {diag.degeneracy_flags}")

    return checks, issues


def _error_result(
    error_code: str,
    pts_a_x: np.ndarray,
    pts_a_y: np.ndarray,
    pts_b_x: np.ndarray,
    pts_b_y: np.ndarray,
    valid_mask: np.ndarray,
    t_start: float,
    detail: str,
) -> RegistrationResult:
    import time

    empty_diag = TransformDiagnostics(
        matrix_type="none",
        matrix=None,
        inlier_mask=np.array([], dtype=bool),
        inlier_count=0,
        outlier_count=int(np.sum(valid_mask)),
        total_correspondences=int(np.sum(valid_mask)),
        inlier_ratio=0.0,
        residual_mean=float("nan"),
        residual_median=float("nan"),
        residual_p95=float("nan"),
        residual_max=float("nan"),
        symmetric_transfer_mean=float("nan"),
        symmetric_transfer_max=float("nan"),
        condition_number=None,
        determinant=None,
        degeneracy_flags=[],
        iterations_used=0,
        seed_used=0,
    )
    return RegistrationResult(
        transform_type=TransformType.HOMOGRAPHY,
        selection_reason=TransformSelectionReason.PREFERRED,
        transform_matrix=None,
        transform_diagnostics=empty_diag,
        validation=ValidationResult(
            verdict=RegistrationValidationVerdict.FAIL,
            checks={},
            issues=[detail],
        ),
        pts_a_sensor=np.column_stack([pts_a_x[valid_mask], pts_a_y[valid_mask]]),
        pts_b_sensor=np.column_stack([pts_b_x[valid_mask], pts_b_y[valid_mask]]),
        valid_mask=valid_mask,
        runtime_seconds=round(time.time() - t_start, 4),
        error=error_code,
    )
