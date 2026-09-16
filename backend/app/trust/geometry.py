from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.app.trust.config import RansacConfig


@dataclass
class ModelResult:
    model_type: str
    matrix: np.ndarray | None
    inlier_mask: np.ndarray
    inlier_count: int
    outlier_count: int
    total_usable: int
    inlier_ratio: float
    residual_stats: dict
    iterations_used: int
    seed_used: int
    degeneracy_flags: list[str]


def _residual_stats(residuals: np.ndarray) -> dict:
    if len(residuals) == 0:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0}
    return {
        "mean": float(np.mean(residuals)),
        "median": float(np.median(residuals)),
        "p95": float(np.percentile(residuals, 95)),
        "max": float(np.max(residuals)),
        "min": float(np.min(residuals)),
    }


def _compute_residuals_forward(pts_a: np.ndarray, pts_b: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    n = pts_a.shape[0]
    ha = np.ones((n, 3), dtype=np.float64)
    ha[:, :2] = pts_a
    proj = (matrix @ ha.T).T
    denom = proj[:, 2:3]
    denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
    proj_xy = proj[:, :2] / denom
    return np.sqrt(np.sum((proj_xy - pts_b) ** 2, axis=1))


def _compute_residuals_reverse(pts_a: np.ndarray, pts_b: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    try:
        inv = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return np.full(pts_b.shape[0], np.inf)
    return _compute_residuals_forward(pts_b, pts_a, inv)


def _check_degeneracy(pts_a: np.ndarray, min_unique: int, max_cond: float) -> list[str]:
    flags: list[str] = []
    if len(pts_a) < min_unique:
        flags.append("INSUFFICIENT_POINTS")
        return flags
    unique_a = np.unique(pts_a, axis=0)
    if len(unique_a) < min_unique:
        flags.append("IDENTICAL_POINTS")
    diffs = np.diff(unique_a, axis=0)
    if len(diffs) > 0:
        cross = diffs[:-1, 0] * diffs[1:, 1] - diffs[:-1, 1] * diffs[1:, 0]
        if np.all(np.abs(cross) < 1e-10):
            flags.append("COLLINEAR_POINTS")
    try:
        centered = unique_a - unique_a.mean(axis=0)
        _, s, _ = np.linalg.svd(centered, full_matrices=False)
        cond = float(s[0] / max(s[-1], 1e-12))
        if cond > max_cond:
            flags.append("HIGH_CONDITION_NUMBER")
    except np.linalg.LinAlgError:
        flags.append("SVD_FAILED")
    return flags


def _fit_homography_dlt(pts_a: np.ndarray, pts_b: np.ndarray) -> np.ndarray | None:
    n = pts_a.shape[0]
    if n < 4:
        return None
    A = np.zeros((2 * n, 9), dtype=np.float64)
    for i in range(n):
        xa, ya = pts_a[i]
        xb, yb = pts_b[i]
        A[2 * i] = [-xa, -ya, -1, 0, 0, 0, xa * xb, ya * xb, xb]
        A[2 * i + 1] = [0, 0, 0, -xa, -ya, -1, xa * yb, ya * yb, yb]
    try:
        _, _, Vt = np.linalg.svd(A, full_matrices=True)
        H = Vt[-1].reshape(3, 3)
        if abs(H[2, 2]) < 1e-12:
            return None
        H /= H[2, 2]
        return H
    except np.linalg.LinAlgError:
        return None


def _fit_affine_dlt(pts_a: np.ndarray, pts_b: np.ndarray) -> np.ndarray | None:
    n = pts_a.shape[0]
    if n < 3:
        return None
    A = np.zeros((2 * n, 6), dtype=np.float64)
    b_vec = np.zeros(2 * n, dtype=np.float64)
    for i in range(n):
        xa, ya = pts_a[i]
        xb, yb = pts_b[i]
        A[2 * i] = [xa, ya, 1, 0, 0, 0]
        A[2 * i + 1] = [0, 0, 0, xa, ya, 1]
        b_vec[2 * i] = xb
        b_vec[2 * i + 1] = yb
    try:
        result, _, _, _ = np.linalg.lstsq(A, b_vec, rcond=None)
        M = np.array([
            [result[0], result[1], result[2]],
            [result[3], result[4], result[5]],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)
        return M
    except np.linalg.LinAlgError:
        return None


def _validate_model(matrix: np.ndarray, model_type: str) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if matrix is None:
        return False, ["NULL_MATRIX"]
    if np.any(np.isnan(matrix)):
        issues.append("NAN_ENTRIES")
    if np.any(np.isinf(matrix)):
        issues.append("INF_ENTRIES")
    if model_type == "homography":
        det = np.linalg.det(matrix[:2, :2])
        if abs(det) < 1e-8:
            issues.append("SINGULAR_LINEAR_PART")
        try:
            cond = float(np.linalg.cond(matrix[:2, :2]))
            if cond > 1e10:
                issues.append("HIGH_CONDITION_NUMBER")
        except np.linalg.LinAlgError:
            issues.append("CONDITION_FAILED")
    return len(issues) == 0, issues


def estimate_homography(pts_a: np.ndarray, pts_b: np.ndarray, cfg: RansacConfig) -> ModelResult:
    rng = np.random.RandomState(cfg.seed)
    n = pts_a.shape[0]
    model_type = "homography"
    degeneracy_flags = _check_degeneracy(
        pts_a, min_unique=4, max_cond=1e6,
    )
    if n < 4 or len(degeneracy_flags) > 0:
        return ModelResult(
            model_type=model_type, matrix=None,
            inlier_mask=np.zeros(n, dtype=bool), inlier_count=0,
            outlier_count=n, total_usable=n, inlier_ratio=0.0,
            residual_stats={}, iterations_used=0, seed_used=cfg.seed,
            degeneracy_flags=degeneracy_flags,
        )
    best_mask = np.zeros(n, dtype=bool)
    best_count = 0
    best_matrix = None
    best_residuals = np.array([])
    iterations = 0
    for it in range(cfg.max_iterations):
        iterations = it + 1
        idx = rng.choice(n, 4, replace=False)
        sub_a = pts_a[idx]
        sub_b = pts_b[idx]
        sub_diffs = sub_a[1:] - sub_a[0]
        if np.any(np.all(np.abs(sub_diffs) < 1e-10, axis=1)):
            continue
        H = _fit_homography_dlt(sub_a, sub_b)
        if H is None:
            continue
        valid, _ = _validate_model(H, model_type)
        if not valid:
            continue
        res = _compute_residuals_forward(pts_a, pts_b, H)
        mask = res < cfg.inlier_threshold_px
        count = int(np.sum(mask))
        if count > best_count:
            best_count = count
            best_mask = mask
            best_matrix = H
            best_residuals = res[mask]
    if best_count >= 4:
        re_mask = np.zeros(n, dtype=bool)
        re_idx = np.where(best_mask)[0]
        if len(re_idx) >= 4:
            re_H = _fit_homography_dlt(pts_a[re_idx], pts_b[re_idx])
            if re_H is not None:
                valid, _ = _validate_model(re_H, model_type)
                if valid:
                    re_res = _compute_residuals_forward(pts_a, pts_b, re_H)
                    re_mask = re_res < cfg.inlier_threshold_px
                    re_count = int(np.sum(re_mask))
                    if re_count >= best_count:
                        best_mask = re_mask
                        best_matrix = re_H
                        best_count = re_count
                        best_residuals = re_res[re_mask]
    inlier_ratio = best_count / n if n > 0 else 0.0
    stats = _residual_stats(best_residuals) if best_count > 0 else {}
    return ModelResult(
        model_type=model_type, matrix=best_matrix,
        inlier_mask=best_mask, inlier_count=best_count,
        outlier_count=n - best_count, total_usable=n,
        inlier_ratio=inlier_ratio, residual_stats=stats,
        iterations_used=iterations, seed_used=cfg.seed,
        degeneracy_flags=degeneracy_flags,
    )


def estimate_affine(pts_a: np.ndarray, pts_b: np.ndarray, cfg: RansacConfig) -> ModelResult:
    rng = np.random.RandomState(cfg.seed)
    n = pts_a.shape[0]
    model_type = "affine"
    degeneracy_flags = _check_degeneracy(
        pts_a, min_unique=3, max_cond=1e6,
    )
    if n < 3 or len(degeneracy_flags) > 0:
        return ModelResult(
            model_type=model_type, matrix=None,
            inlier_mask=np.zeros(n, dtype=bool), inlier_count=0,
            outlier_count=n, total_usable=n, inlier_ratio=0.0,
            residual_stats={}, iterations_used=0, seed_used=cfg.seed,
            degeneracy_flags=degeneracy_flags,
        )
    best_mask = np.zeros(n, dtype=bool)
    best_count = 0
    best_matrix = None
    best_residuals = np.array([])
    iterations = 0
    for it in range(cfg.max_iterations):
        iterations = it + 1
        idx = rng.choice(n, 3, replace=False)
        sub_a = pts_a[idx]
        sub_b = pts_b[idx]
        M = _fit_affine_dlt(sub_a, sub_b)
        if M is None:
            continue
        valid, _ = _validate_model(M, model_type)
        if not valid:
            continue
        res = _compute_residuals_forward(pts_a, pts_b, M)
        mask = res < cfg.inlier_threshold_px
        count = int(np.sum(mask))
        if count > best_count:
            best_count = count
            best_mask = mask
            best_matrix = M
            best_residuals = res[mask]
    if best_count >= 3:
        re_idx = np.where(best_mask)[0]
        if len(re_idx) >= 3:
            re_M = _fit_affine_dlt(pts_a[re_idx], pts_b[re_idx])
            if re_M is not None:
                valid, _ = _validate_model(re_M, model_type)
                if valid:
                    re_res = _compute_residuals_forward(pts_a, pts_b, re_M)
                    re_mask = re_res < cfg.inlier_threshold_px
                    re_count = int(np.sum(re_mask))
                    if re_count >= best_count:
                        best_mask = re_mask
                        best_matrix = re_M
                        best_count = re_count
                        best_residuals = re_res[re_mask]
    inlier_ratio = best_count / n if n > 0 else 0.0
    stats = _residual_stats(best_residuals) if best_count > 0 else {}
    return ModelResult(
        model_type=model_type, matrix=best_matrix,
        inlier_mask=best_mask, inlier_count=best_count,
        outlier_count=n - best_count, total_usable=n,
        inlier_ratio=inlier_ratio, residual_stats=stats,
        iterations_used=iterations, seed_used=cfg.seed,
        degeneracy_flags=degeneracy_flags,
    )


def compute_symmetric_transfer(
    pts_a: np.ndarray, pts_b: np.ndarray, matrix: np.ndarray,
) -> np.ndarray:
    fwd = _compute_residuals_forward(pts_a, pts_b, matrix)
    rev = _compute_residuals_reverse(pts_a, pts_b, matrix)
    return np.maximum(fwd, rev)


def validate_model_matrix(matrix: np.ndarray | None, model_type: str) -> tuple[bool, list[str]]:
    return _validate_model(matrix, model_type)
