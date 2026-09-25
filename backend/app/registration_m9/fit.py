"""M9 REGISTRATION — model fit (smallest-valid policy, fully deterministic).

MODEL FIT is separated from MODEL ACCEPTANCE (validate.py) and IMAGE WARP
(warp.py). No RNG, no iterative refinement: affine is a direct least-squares
solve and homography is a normalized DLT (Hartley-style two-point
normalization), then verified. In ``auto`` mode the smallest technically valid
model is preferred — a valid affine is never re-fit as a homography merely to
obtain a more favourable acceptance metric; homography is an explicit
escalation only when the affine matrix is not mathematically usable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import states
from .config import RegistrationM9Config


def _to_hom(pts: np.ndarray) -> np.ndarray:
    n = len(pts)
    h = np.ones((n, 3), dtype=np.float64)
    h[:, :2] = pts
    return h


def _normalization(pts: np.ndarray) -> np.ndarray:
    """Two-point similarity normalization: origin at centroid, unit RMS distance."""
    c = np.mean(pts, axis=0)
    d = np.sqrt(np.mean(np.sum((pts - c) ** 2, axis=1)))
    s = (np.sqrt(2.0) / d) if d > 1e-12 else 1.0
    T = np.eye(3, dtype=np.float64)
    T[0, 0] = s
    T[1, 1] = s
    T[0, 2] = -s * c[0]
    T[1, 2] = -s * c[1]
    return T


def fit_affine(pts_a: np.ndarray, pts_b: np.ndarray) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Least-squares affine A-frame -> B-frame. Returns (3x3 matrix, diagnostics)."""
    n = len(pts_a)
    if n < 3:
        return None, {"model_type": states.AFFINE, "algorithm": "lstsq",
                      "error": "INSUFFICIENT_POINTS", "source_point_count": n,
                      "target_point_count": len(pts_b)}
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
        result, residuals, rank, s = np.linalg.lstsq(A, b_vec, rcond=None)
    except np.linalg.LinAlgError:
        return None, {"model_type": states.AFFINE, "algorithm": "lstsq",
                      "error": "LSTSQ_FAILED", "source_point_count": n,
                      "target_point_count": len(pts_b)}
    M = np.eye(3, dtype=np.float64)
    M[:2, :] = result.reshape(2, 3)
    diag: dict[str, Any] = {
        "model_type": states.AFFINE,
        "algorithm": "least_squares_lstsq",
        "source_point_count": int(n),
        "target_point_count": int(len(pts_b)),
        "rank": int(rank),
        "condition_sigma": float(s[0] / s[-1]) if s.size and s[-1] > 1e-12 else None,
        "fit_residual": float(np.sqrt(residuals[0])) if residuals.size else 0.0,
        "normalization": "none",
        "rng": "NONE",
        "rng_seed_policy": "Direct deterministic solve; no random sampling.",
    }
    return M, diag


def fit_homography_normalized_dlt(
    pts_a: np.ndarray, pts_b: np.ndarray, normalized: bool = True,
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """Normalized DLT homography A-frame -> B-frame. Returns (3x3, diagnostics)."""
    n = len(pts_a)
    if n < 4:
        return None, {"model_type": states.HOMOGRAPHY, "algorithm": "normalized_dlt",
                      "error": "INSUFFICIENT_POINTS", "source_point_count": n,
                      "target_point_count": len(pts_b)}
    Ta = _normalization(pts_a) if normalized else np.eye(3, dtype=np.float64)
    Tb = _normalization(pts_b) if normalized else np.eye(3, dtype=np.float64)
    ha = Ta @ _to_hom(pts_a).T
    hb = Tb @ _to_hom(pts_b).T
    A = np.zeros((2 * n, 9), dtype=np.float64)
    for i in range(n):
        xa, ya, wa = ha[0, i], ha[1, i], ha[2, i]
        xb, yb, wb = hb[0, i], hb[1, i], hb[2, i]
        A[2 * i] = [0, 0, 0, -wb * xa, -wb * ya, -wb * wa, yb * xa, yb * ya, yb * wa]
        A[2 * i + 1] = [wb * xa, wb * ya, wb * wa, 0, 0, 0, -xb * xa, -xb * ya, -xb * wa]
    try:
        _, s, Vt = np.linalg.svd(A, full_matrices=True)
        H_norm = Vt[-1].reshape(3, 3)
    except np.linalg.LinAlgError:
        return None, {"model_type": states.HOMOGRAPHY, "algorithm": "normalized_dlt",
                      "error": "SVD_FAILED", "source_point_count": n,
                      "target_point_count": len(pts_b)}
    H = np.linalg.inv(Tb) @ H_norm @ Ta
    if abs(H[2, 2]) < 1e-12:
        return None, {"model_type": states.HOMOGRAPHY, "algorithm": "normalized_dlt",
                      "error": "DEGENERATE_HOMOGENEOUS", "source_point_count": n,
                      "target_point_count": len(pts_b)}
    H = H / H[2, 2]
    diag: dict[str, Any] = {
        "model_type": states.HOMOGRAPHY,
        "algorithm": "normalized_dlt" if normalized else "dlt",
        "source_point_count": int(n),
        "target_point_count": int(len(pts_b)),
        "normalization": "two_point_similarity" if normalized else "none",
        "dlt_condition": float(s[0] / max(s[-1], 1e-12)),
        "rng": "NONE",
        "rng_seed_policy": "Direct deterministic solve; no random sampling.",
    }
    return H, diag


@dataclass
class FitResult:
    model_type: str
    selection_reason: str
    algorithm: str
    matrix: np.ndarray | None
    fit_diagnostics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def _matrix_usable(matrix: np.ndarray) -> tuple[bool, list[str]]:
    if matrix is None or (not np.all(np.isfinite(matrix))):
        return False, ["NON_FINITE_MATRIX"]
    det = np.linalg.det(matrix[:2, :2])
    if not np.isfinite(det) or abs(det) < 1e-9:
        return False, ["SINGULAR_LINEAR_PART"]
    lst = matrix.tolist()
    return True, []


def choose_and_fit(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    cfg: RegistrationM9Config,
    requested_model: str = "auto",
) -> FitResult:
    """Select and fit the declared model under the smallest-valid policy.

    ``requested_model``: ``auto`` (affine preferred, homography only when the
    affine matrix is not mathematically usable), ``affine`` or ``homography``
    (explicit). This is the MODEL FIT step only; acceptance is judged later.
    """
    requested_model = (requested_model or "auto").strip().upper()
    model = cfg.model
    if requested_model == states.AFFINE:
        M, diag = fit_affine(pts_a, pts_b)
        usable, issues = _matrix_usable(M)
        if not usable:
            return FitResult(states.AFFINE, states.SELECTION_REASON_SMALLEST_VALID,
                             diag.get("algorithm", "lstsq"), None, diag,
                             error=f"TRANSFORM_FIT_ERROR: {', '.join(issues)}")
        return FitResult(states.AFFINE, states.SELECTION_REASON_SMALLEST_VALID,
                         diag.get("algorithm", "lstsq"), M, diag)

    if requested_model == states.HOMOGRAPHY:
        H, diag = fit_homography_normalized_dlt(
            pts_a, pts_b, normalized=bool(model.normalized_dlt))
        usable, issues = _matrix_usable(H)
        if not usable:
            return FitResult(states.HOMOGRAPHY, states.SELECTION_REASON_EXPLICIT_HOMOGRAPHY,
                             diag.get("algorithm", "normalized_dlt"), None, diag,
                             error=f"TRANSFORM_FIT_ERROR: {', '.join(issues)}")
        return FitResult(states.HOMOGRAPHY, states.SELECTION_REASON_EXPLICIT_HOMOGRAPHY,
                         diag.get("algorithm", "normalized_dlt"), H, diag)

    # auto: smallest technically valid model first
    M, diag = fit_affine(pts_a, pts_b)
    usable, _ = _matrix_usable(M)
    if usable and len(pts_a) >= max(model.min_points_affine, 2):
        return FitResult(states.AFFINE, states.SELECTION_REASON_SMALLEST_VALID,
                         diag.get("algorithm", "lstsq"), M, diag)

    # affine not mathematically usable -> explicit escalation to homography
    H, hdiag = fit_homography_normalized_dlt(
        pts_a, pts_b, normalized=bool(model.normalized_dlt))
    usable, issues = _matrix_usable(H)
    if not usable or len(pts_a) < max(model.min_points_homography, 2):
        return FitResult(states.HOMOGRAPHY, states.SELECTION_REASON_AFFINE_ESCALATED,
                         hdiag.get("algorithm", "normalized_dlt"), None, hdiag,
                         error=f"TRANSFORM_FIT_ERROR: {', '.join(issues) or 'AFFINE_AND_HOMOGRAPHY_INVALID'}")
    return FitResult(states.HOMOGRAPHY, states.SELECTION_REASON_AFFINE_ESCALATED,
                     hdiag.get("algorithm", "normalized_dlt"), H, hdiag)


__all__ = ["choose_and_fit", "fit_affine", "fit_homography_normalized_dlt", "FitResult"]