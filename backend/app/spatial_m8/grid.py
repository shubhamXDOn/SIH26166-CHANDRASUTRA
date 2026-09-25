"""M8 SPATIAL — deterministic grid cell assignment for one side.

Coordinates are interpreted in the declared effective matcher plane of the
side (pixels). Assignments are fully deterministic: no RNG, integer floor
partitioning, and out-of-frame points are clipped only for bookkeeping while
still flagged honestly under the REPORT_ONLY edge policy.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import GridConfig


def cell_for_point(
    x: float,
    y: float,
    height: float,
    width: float,
    rows: int,
    cols: int,
) -> tuple[int, int, bool]:
    """Return (cell_row, cell_col, out_of_frame) for one ``[x, y]`` point."""
    cols = max(int(cols), 1)
    rows = max(int(rows), 1)
    out = bool(
        not np.isfinite(x) or not np.isfinite(y)
        or x < 0.0 or y < 0.0 or x >= width or y >= height
    )
    c = int(np.floor(x / (width / cols))) if width > 0 and np.isfinite(x) else 0
    r = int(np.floor(y / (height / rows))) if height > 0 and np.isfinite(y) else 0
    c = min(max(c, 0), cols - 1)
    r = min(max(r, 0), rows - 1)
    return r, c, out


def grid_counts(
    points: np.ndarray,
    height: float,
    width: float,
    grid: GridConfig,
) -> dict[str, Any]:
    """Count occupancy per cell for an (N, 2) ``[x, y]`` point array.

    Returns occupancy (rows x cols int array), rows, cols, and the list of
    per-point edge flags (True = out of the effective plane).
    """
    rows = max(int(grid.rows), 1)
    cols = max(int(grid.cols), 1)
    n = len(points)
    occupancy = np.zeros((rows, cols), dtype=np.int64)
    edges: list[bool] = []
    for i in range(n):
        x, y = points[i]
        r, c, out = cell_for_point(x, y, height, width, rows, cols)
        occupancy[r, c] += 1
        edges.append(bool(out))
    return {
        "rows": rows,
        "cols": cols,
        "occupancy": occupancy,
        "edge_flags": edges,
        "edge_policy": grid.edge_policy,
    }


def cell_of_point_grid(points: np.ndarray, height: float, width: float, rows: int, cols: int) -> np.ndarray:
    """Return the (N, 2) integer cell indices for a point array (deterministic)."""
    rows = max(int(rows), 1)
    cols = max(int(cols), 1)
    n = len(points)
    out = np.zeros((n, 2), dtype=np.int64)
    for i in range(n):
        x, y = points[i]
        r, c, _out = cell_for_point(x, y, height, width, rows, cols)
        out[i, 0] = r
        out[i, 1] = c
    return out


__all__ = ["cell_for_point", "grid_counts", "cell_of_point_grid"]