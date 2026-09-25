"""M4 deep matcher — recorded coordinate transforms (grid <-> effective).

The SuperPoint score grid is ``cell * floor(effective_h / cell)`` by
``cell * floor(effective_w / cell)`` (cell == 8); the effective image
frame is the model input window at ``max_image_dimension``. Mapping
between the two frames is a pure linear scale with no crop:

    grid_x = effective_x * (grid_w / effective_w)   (and same for y)

Native (original M2 product) coordinates are reached by composing the
effective frame, whose resize factor is recorded at run time.

Every transform records the exact parameters it used so round trips are
verifiable and no coordinate is ever silently assumed.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _dims(*, width: int, height: int) -> dict[str, int]:
    return {"height": int(height), "width": int(width)}


def grid_dimensions(effective_dims: tuple[int, int], cell: int = 8) -> tuple[int, int]:
    """(height, width) of the SuperPoint score grid for a model-input window."""
    eff_h, eff_w = effective_dims
    return (int(eff_h // cell) * cell, int(eff_w // cell) * cell)


def _scale(grid: tuple[int, int], effective: tuple[int, int]) -> tuple[float, float]:
    gh, gw = grid
    eh, ew = effective
    if eh <= 0 or ew <= 0:
        raise ValueError(f"effective dims must be positive; got {effective}")
    sy = gh / float(eh)
    sx = gw / float(ew)
    return (float(sx), float(sy))


def build_grid_to_effective(
    grid_dims: tuple[int, int], effective_dims: tuple[int, int]
) -> dict[str, Any]:
    """Recorded linear transform grid->effective for a single axis-pair."""
    sx, sy = _scale(grid_dims, effective_dims)
    return {
        "kind": "linear_scale",
        "grid_dimensions": _dims(width=grid_dims[1], height=grid_dims[0]),
        "effective_dimensions": _dims(width=effective_dims[1], height=effective_dims[0]),
        "scale": {"x": sx, "y": sy},
        "plane": "MODEL_SCORE_GRID",
    }


def grid_to_effective(
    xy: np.ndarray, grid_dims: tuple[int, int], effective_dims: tuple[int, int]
) -> np.ndarray:
    """Map (N,2) [x,y] keypoints from score grid to effective frame."""
    p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    sx, sy = _scale(grid_dims, effective_dims)
    sx, sy = 1.0 / sx, 1.0 / sy
    out = p.copy()
    out[:, 0] = out[:, 0] * sx
    out[:, 1] = out[:, 1] * sy
    return out


def effective_to_grid(
    xy: np.ndarray, grid_dims: tuple[int, int], effective_dims: tuple[int, int]
) -> np.ndarray:
    """Map (N,2) [x,y] keypoints from effective frame to score grid."""
    p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    sx, sy = _scale(grid_dims, effective_dims)
    out = p.copy()
    out[:, 0] = out[:, 0] * sx
    out[:, 1] = out[:, 1] * sy
    return out


def build_effective_to_native(
    effective_dims: tuple[int, int], native_dims: tuple[int, int]
) -> dict[str, Any]:
    """Recorded linear transform effective->native (resize factor)."""
    eh, ew = effective_dims
    nh, nw = native_dims
    if eh <= 0 or ew <= 0 or nh <= 0 or nw <= 0:
        raise ValueError("dims must all be positive")
    return {
        "kind": "linear_scale_resample",
        "effective_dimensions": _dims(width=ew, height=eh),
        "native_dimensions": _dims(width=nw, height=nh),
        "scale": {"x": nw / float(ew), "y": nh / float(eh)},
        "plane": "NATIVE_PRODUCT",
    }


def effective_to_native(
    xy: np.ndarray, effective_dims: tuple[int, int], native_dims: tuple[int, int]
) -> np.ndarray:
    p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    eh, ew = effective_dims
    nh, nw = native_dims
    out = p.copy()
    out[:, 0] = out[:, 0] * (nw / float(ew))
    out[:, 1] = out[:, 1] * (nh / float(eh))
    return out


def native_to_effective(
    xy: np.ndarray, effective_dims: tuple[int, int], native_dims: tuple[int, int]
) -> np.ndarray:
    p = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    eh, ew = effective_dims
    nh, nw = native_dims
    out = p.copy()
    out[:, 0] = out[:, 0] * (ew / float(nw))
    out[:, 1] = out[:, 1] * (eh / float(nh))
    return out