"""M6 warp module.

Maps a sensor-A crop window into a sensor-B output window using the fitted
transform matrix (3x3).  Homography and affine share the same pipeline by
up-casting affine to 3x3, inverting, and composing with tile origin offsets
to give a single dst→src 3x3 for ``cv2.warpPerspective``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

_INTERP = cv2.INTER_LINEAR
_BORDER = cv2.BORDER_CONSTANT


@dataclass
class WarpSpec:
    src_array: np.ndarray          # 2-D source crop (masked/valid)
    src_row_start: int             # top of source window in sensor A pixels
    src_col_start: int
    out_rows: int                  # height of output window in sensor B pixels
    out_cols: int                  # width of output window
    out_row_start: int             # top of output window in sensor B pixels
    out_col_start: int


@dataclass
class WarpProduct:
    warped: np.ndarray             # 2-D float32 warped array
    valid_mask: np.ndarray         # bool mask (True where mapped inside source)
    matrix_type: str               # "homography" or "affine"


def _to_3x3(matrix: np.ndarray) -> np.ndarray:
    h = np.eye(3, dtype=np.float64)
    if matrix.shape == (3, 3):
        return matrix.copy()
    if matrix.shape == (2, 3):
        h[:2, :] = matrix
        return h
    raise ValueError(f"Unexpected matrix shape: {matrix.shape}")


def _build_cv_matrix(
    matrix: np.ndarray,
    spec: WarpSpec,
) -> np.ndarray:
    H = _to_3x3(matrix)
    try:
        H_inv = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        H_inv = np.linalg.pinv(H)

    # output-local -> B-global (positive offset)
    T_out = np.eye(3, dtype=np.float64)
    T_out[0, 2] = spec.out_col_start
    T_out[1, 2] = spec.out_row_start

    # A-global -> A-local (subtract source origin)
    T_src = np.eye(3, dtype=np.float64)
    T_src[0, 2] = -spec.src_col_start
    T_src[1, 2] = -spec.src_row_start

    # dst-local → dst-global → src-global → src-local
    cv_mat = T_src @ H_inv @ T_out
    return cv_mat


def warp_tile(
    spec: WarpSpec,
    matrix: np.ndarray,
    matrix_type: str = "homography",
    fill_value: int = 0,
) -> WarpProduct:
    if spec.out_rows <= 0 or spec.out_cols <= 0:
        return WarpProduct(
            warped=np.zeros((0, 0), dtype=np.float32),
            valid_mask=np.zeros((0, 0), dtype=bool),
            matrix_type=matrix_type,
        )

    cv_mat = _build_cv_matrix(matrix, spec)

    warped = cv2.warpPerspective(
        spec.src_array.astype(np.float32),
        cv_mat,
        (spec.out_cols, spec.out_rows),
        flags=_INTERP,
        borderMode=_BORDER,
        borderValue=float(fill_value),
    )

    valid = (warped != float(fill_value)) & np.isfinite(warped)
    return WarpProduct(warped=warped, valid_mask=valid, matrix_type=matrix_type)
