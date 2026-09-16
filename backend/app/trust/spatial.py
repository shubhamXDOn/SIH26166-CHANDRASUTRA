from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SpatialDiagnostics:
    grid_cells_occupied: int
    total_cells: int
    occupancy_ratio: float
    concentration_ratio: float
    spatial_extent_diag: float
    coordinate_spread_x: float
    coordinate_spread_y: float


def compute_spatial_diagnostics(
    pts_a: np.ndarray,
    pts_b: np.ndarray,
    inlier_mask: np.ndarray,
    grid_cells: int = 4,
) -> SpatialDiagnostics:
    inlier_a = pts_a[inlier_mask]
    inlier_b = pts_b[inlier_mask]
    n_inliers = len(inlier_a)
    total_cells = grid_cells * grid_cells
    if n_inliers == 0:
        return SpatialDiagnostics(
            grid_cells_occupied=0, total_cells=total_cells,
            occupancy_ratio=0.0, concentration_ratio=0.0,
            spatial_extent_diag=0.0,
            coordinate_spread_x=0.0, coordinate_spread_y=0.0,
        )
    min_xy = np.minimum(inlier_a.min(axis=0), inlier_b.min(axis=0))
    max_xy = np.maximum(inlier_a.max(axis=0), inlier_b.max(axis=0))
    combined = np.vstack([inlier_a, inlier_b])
    span_x = float(combined[:, 0].max() - combined[:, 0].min())
    span_y = float(combined[:, 1].max() - combined[:, 1].min())
    norm_x = (combined[:, 0] - combined[:, 0].min()) / max(span_x, 1e-10)
    norm_y = (combined[:, 1] - combined[:, 1].min()) / max(span_y, 1e-10)
    cell_x = np.clip((norm_x * grid_cells).astype(int), 0, grid_cells - 1)
    cell_y = np.clip((norm_y * grid_cells).astype(int), 0, grid_cells - 1)
    occupied = set()
    cell_counts: dict[tuple[int, int], int] = {}
    for cx, cy in zip(cell_x, cell_y):
        key = (int(cx), int(cy))
        occupied.add(key)
        cell_counts[key] = cell_counts.get(key, 0) + 1
    grid_occupied = len(occupied)
    occupancy_ratio = grid_occupied / total_cells if total_cells > 0 else 0.0
    max_cell = max(cell_counts.values()) if cell_counts else 0
    concentration = max_cell / n_inliers if n_inliers > 0 else 0.0
    extent = float(np.sqrt(np.sum((max_xy - min_xy) ** 2)))
    spread_x = float(np.std(combined[:, 0]))
    spread_y = float(np.std(combined[:, 1]))
    return SpatialDiagnostics(
        grid_cells_occupied=grid_occupied,
        total_cells=total_cells,
        occupancy_ratio=occupancy_ratio,
        concentration_ratio=concentration,
        spatial_extent_diag=extent,
        coordinate_spread_x=spread_x,
        coordinate_spread_y=spread_y,
    )
