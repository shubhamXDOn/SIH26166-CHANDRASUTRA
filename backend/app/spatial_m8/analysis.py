"""M8 SPATIAL — per-side spatial bookkeeping evidence.

All measurements are expressed in pixels in the declared effective matcher
plane of the side. They are spatial bookkeeping evidence — coverage, cell
occupancy, entropy, extent, centroid, spread and concentration — never an
accuracy, probability or registration claim.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .config import CoverageConfig


def _fmt(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 9)


def _normalized_entropy(counts: np.ndarray, total: int) -> float | None:
    """Shannon entropy over the cell distribution, normalised to 0..1.

    None when there is no distribution to measure (zero or one cell used).
    """
    if total <= 0:
        return None
    nonzero = counts[counts > 0].astype(np.float64)
    if len(nonzero) < 2:
        return None
    p = nonzero / float(total)
    h = -float(np.sum(p * np.log2(p)))
    denom = math.log2(float(len(nonzero)))
    if denom <= 0:
        return None
    return round(h / denom, 9)


def _side_block(points: np.ndarray, counts: np.ndarray, total_cells: int, cfg: CoverageConfig) -> dict[str, Any]:
    """Bookkeeping block for one side's trusted points (px in effective plane)."""
    n = len(points)
    occupied = int(np.count_nonzero(counts))
    coverage = round(occupied / float(total_cells), 9) if total_cells > 0 else 0.0
    max_cell = int(np.max(counts)) if counts.size and counts.size > 0 else 0
    concentration = round(float(max_cell) / float(n), 9) if n > 0 else None
    entropy = _normalized_entropy(counts, n)

    xs = points[:, 0]
    ys = points[:, 1]
    ext = {
        "min_x": _fmt(float(np.min(xs))) if n else None,
        "max_x": _fmt(float(np.max(xs))) if n else None,
        "min_y": _fmt(float(np.min(ys))) if n else None,
        "max_y": _fmt(float(np.max(ys))) if n else None,
        "span_x_px": _fmt(float(np.max(xs) - np.min(xs))) if n else None,
        "span_y_px": _fmt(float(np.max(ys) - np.min(ys))) if n else None,
        "extent_diag_px": _fmt(float(math.hypot(np.max(xs) - np.min(xs), np.max(ys) - np.min(ys)))) if n else None,
    }
    centroid = {"x": _fmt(float(np.mean(xs))), "y": _fmt(float(np.mean(ys)))} if n else None
    spread = {"std_x_px": _fmt(float(np.std(xs))), "std_y_px": _fmt(float(np.std(ys)))} if n else None

    return {
        "count": int(n),
        "occupied_cells": occupied,
        "total_cells": total_cells,
        "coverage_ratio": coverage,
        "max_cell_count": max_cell,
        "concentration_ratio": concentration,
        "entropy_normalized": entropy,
        "extent": ext,
        "centroid": centroid,
        "spread": spread,
        "units": "px in effective matcher plane",
    }


def spatial_analysis(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    occ_a: np.ndarray,
    occ_b: np.ndarray,
    dims_a: dict[str, float],
    dims_b: dict[str, float],
    cfg: CoverageConfig,
) -> dict[str, Any]:
    """Build the two-side bookkeeping blocks (pure, no I/O)."""
    rows = occ_a.shape[0]
    cols = occ_a.shape[1]
    total_cells = rows * cols
    return {
        "frame": "EFFECTIVE_MATCHER_PLANE",
        "grid": {"rows": rows, "cols": cols, "total_cells": total_cells},
        "a": _side_block(pts_a, occ_a, total_cells, cfg),
        "b": _side_block(pts_b, occ_b, total_cells, cfg),
    }


__all__ = ["spatial_analysis", "_normalized_entropy"]