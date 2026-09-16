"""Reliability aggregation over the scene grid (M5).

Produces per-cell measurable evidence, neighborhood support, deterministic
connected reliable regions, fragmentation and boundary statistics. No opaque
confidence number: every figure is counts, ratios or explicit flags.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.spatial.config import SpatialReliabilityConfig
from backend.app.spatial.grid import Grid


@dataclass
class CellEvidence:
    cell_id: str
    r: int
    c: int
    observed: bool
    trusted_tile_count: int
    verified_inlier_count: int
    usable_correspondence_count: int
    spatial_density: float
    side_a_verified: int
    side_a_usable: int
    side_b_verified: int
    side_b_usable: int
    neighbor_support: int
    reliable: bool
    supported: bool
    edge_touching: bool
    component_id: str | None = None
    selected: bool = False

    def to_dict(self) -> dict:
        return {
            "cell_id": self.cell_id,
            "r": self.r,
            "c": self.c,
            "observed": self.observed,
            "trusted_tile_count": self.trusted_tile_count,
            "verified_inlier_count": self.verified_inlier_count,
            "usable_correspondence_count": self.usable_correspondence_count,
            "spatial_density": round(float(self.spatial_density), 6),
            "side_a": {"verified_inliers": self.side_a_verified, "usable_correspondences": self.side_a_usable},
            "side_b": {"verified_inliers": self.side_b_verified, "usable_correspondences": self.side_b_usable},
            "neighbor_support": self.neighbor_support,
            "reliable": self.reliable,
            "supported": self.supported,
            "component_id": self.component_id,
            "edge_touching": self.edge_touching,
            "selected": self.selected,
        }


@dataclass
class ComponentInfo:
    component_id: str
    cells: list[str]
    rows: list[int]
    cols: list[int]
    correspondence_count: int
    trusted_tile_count: int = 0
    selected: bool = False

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    def to_dict(self, grid: Grid) -> dict:
        if self.cells:
            r0, r1 = min(self.rows), max(self.rows)
            c0, c1 = min(self.cols), max(self.cols)
            centroid_r = sum(self.rows) / len(self.rows)
            centroid_c = sum(self.cols) / len(self.cols)
            nr = centroid_r / grid.rows
            nc = centroid_c / grid.cols
        else:
            r0 = r1 = c0 = c1 = 0
            nr = nc = 0.0
        return {
            "component_id": self.component_id,
            "cell_count": self.cell_count,
            "area_proxy": round(self.cell_count / grid.total_cells, 6) if grid.total_cells else 0.0,
            "correspondence_count": self.correspondence_count,
            "trusted_tile_count": self.trusted_tile_count,
            "bounding_box": {"r0": r0, "r1": r1, "c0": c0, "c1": c1},
            "centroid": {
                "r": round(centroid_r, 4), "c": round(centroid_c, 4),
                "nx": round(nc, 4), "ny": round(nr, 4),
            },
            "edge_touching": any(grid.is_edge_cell(r, c) for r, c in zip(self.rows, self.cols)),
            "cells": self.cells,
            "selected": self.selected,
        }


@dataclass
class ReliabilityResult:
    cells: list[CellEvidence] = field(default_factory=list)
    components: list[ComponentInfo] = field(default_factory=list)
    fragmentation: dict = field(default_factory=dict)
    boundary: dict = field(default_factory=dict)
    reliable_cells: list[str] = field(default_factory=list)
    supported_cells: list[str] = field(default_factory=list)


def compute_reliability(
    grid: Grid,
    cfg: SpatialReliabilityConfig,
    *,
    verified: dict[str, int],
    usable: dict[str, int],
    tiles: dict[str, set[str]],
    side_a_verified: dict[str, int] | None = None,
    side_a_usable: dict[str, int] | None = None,
    side_b_verified: dict[str, int] | None = None,
    side_b_usable: dict[str, int] | None = None,
) -> ReliabilityResult:
    side_a_verified = side_a_verified or {}
    side_a_usable = side_a_usable or {}
    side_b_verified = side_b_verified or {}
    side_b_usable = side_b_usable or {}
    rel_cfg = cfg.reliability
    radius = cfg.neighborhood.support_radius_cells

    cells: list[CellEvidence] = []
    reliable_flags: dict[str, bool] = {}
    for cell_id in grid.all_cell_ids():
        rc = grid.rc(cell_id)
        v = int(verified.get(cell_id, 0))
        u = int(usable.get(cell_id, 0))
        t = len(tiles.get(cell_id, set()))
        observed = v > 0 or u > 0
        box = grid.cell_box(rc[0], rc[1])
        reliable = (
            observed
            and v >= rel_cfg.min_verified_inliers_per_cell
            and t >= rel_cfg.min_trusted_tiles_per_cell
        )
        reliable_flags[cell_id] = reliable
        cells.append(CellEvidence(
            cell_id=cell_id,
            r=rc[0],
            c=rc[1],
            observed=observed,
            trusted_tile_count=t,
            verified_inlier_count=v,
            usable_correspondence_count=u,
            spatial_density=float(v) / box["area_proxy"] if box["area_proxy"] > 0 else 0.0,
            side_a_verified=int(side_a_verified.get(cell_id, 0)),
            side_a_usable=int(side_a_usable.get(cell_id, 0)),
            side_b_verified=int(side_b_verified.get(cell_id, 0)),
            side_b_usable=int(side_b_usable.get(cell_id, 0)),
            neighbor_support=0,
            reliable=reliable,
            supported=False,
            edge_touching=grid.is_edge_cell(rc[0], rc[1]),
        ))

    for c in cells:
        nb = 0
        for nr, nc in grid.neighbors(c.r, c.c, radius):
            if reliable_flags.get(grid.cell_id(nr, nc), False):
                nb += 1
        c.neighbor_support = nb
        c.supported = c.reliable and nb >= 1

    components = _label_components(grid, cfg, reliable_flags, verified, tiles)
    comp_ids: dict[str, str] = {}
    for comp in components:
        for cid in comp.cells:
            comp_ids[cid] = comp.component_id
    for c in cells:
        c.component_id = comp_ids.get(c.cell_id)

    reliable_list = [c.cell_id for c in cells if c.reliable]
    supported_ids = [c.cell_id for c in cells if c.supported]
    edge_cells_reliable = [c.cell_id for c in cells if c.reliable and c.edge_touching]
    edge_cells_total = sum(1 for c in cells if c.edge_touching)
    total_reliable = len(reliable_list)
    isolated = [c.cell_id for c in cells if c.reliable and c.neighbor_support == 0]
    largest = max((comp.cell_count for comp in components), default=0)

    fragmentation = {
        "total_reliable_cells": total_reliable,
        "connected_components": len(components),
        "largest_component_size": largest,
        "largest_component_ratio": round(largest / total_reliable, 6) if total_reliable else 0.0,
        "isolated_cell_count": len(isolated),
        "mean_component_size": round(
            sum(comp.cell_count for comp in components) / len(components),
            6) if components else 0.0,
    }
    boundary = {
        "edge_touching_cells": len(edge_cells_reliable),
        "edge_fraction": round(len(edge_cells_reliable) / total_reliable, 6) if total_reliable else 0.0,
        "boundary_concentration": round(
            len(edge_cells_reliable) / edge_cells_total, 6) if edge_cells_total else 0.0,
    }

    return ReliabilityResult(
        cells=cells,
        components=components,
        fragmentation=fragmentation,
        boundary=boundary,
        reliable_cells=reliable_list,
        supported_cells=supported_ids,
    )


def _label_components(
    grid: Grid,
    cfg: SpatialReliabilityConfig,
    reliable: dict[str, bool],
    verified: dict[str, int],
    tiles: dict[str, set[str]],
) -> list[ComponentInfo]:
    connectivity = cfg.connected_components.connectivity
    visited: set[str] = set()
    components: list[ComponentInfo] = []
    counter = 0
    for cell_id in grid.all_cell_ids():
        if not reliable.get(cell_id, False) or cell_id in visited:
            continue
        counter += 1
        cid = f"C{counter:02d}"
        stack = [cell_id]
        visited.add(cell_id)
        cells_local: list[str] = []
        while stack:
            cur = stack.pop()
            cells_local.append(cur)
            rc = grid.rc(cur)
            for nr, nc in grid.neighbors(rc[0], rc[1], 1):
                if connectivity == 4 and not (nr == rc[0] or nc == rc[1]):
                    continue
                nbid = grid.cell_id(nr, nc)
                if reliable.get(nbid, False) and nbid not in visited:
                    visited.add(nbid)
                    stack.append(nbid)
        cells_sorted = sorted(cells_local)
        rows = [int(grid.rc(c)[0]) for c in cells_sorted]
        cols = [int(grid.rc(c)[1]) for c in cells_sorted]
        comp_tiles: set[str] = set()
        corr = 0
        for c in cells_sorted:
            corr += int(verified.get(c, 0))
            comp_tiles |= tiles.get(c, set())
        components.append(ComponentInfo(
            component_id=cid,
            cells=cells_sorted,
            rows=rows,
            cols=cols,
            correspondence_count=corr,
            trusted_tile_count=len(comp_tiles),
        ))
    return components