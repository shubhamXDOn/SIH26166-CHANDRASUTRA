"""Reliability-aware selection (M5, mode SUPPORTED_REGION).

Selects the spatially supported reliable region(s) as evidence for
registration, deterministically, honestly abstaining when thresholds fail.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.spatial.config import SpatialReliabilityConfig
from backend.app.spatial.grid import Grid
from backend.app.spatial.reliability import ComponentInfo, ReliabilityResult

SELECTED = "SELECTED"
INSUFFICIENT = "INSUFFICIENT"


@dataclass
class SelectionPlan:
    selection_outcome: str
    decision_reason: str
    selected_cell_ids: set[str]
    selected_component_ids: list[str]
    selected_cells_covered: bool = False
    trace: dict | None = None


def plan_selection(
    grid: Grid,
    cfg: SpatialReliabilityConfig,
    result: ReliabilityResult,
) -> SelectionPlan:
    sel = cfg.selection
    edge_policy = cfg.boundary.edge_policy
    exclude_edge = edge_policy in ("EXCLUDE", "EXPOSE")

    eligible: list[ComponentInfo] = []
    for comp in result.components:
        edge_only = all(grid.is_edge_cell(r, c) for r, c in zip(comp.rows, comp.cols))
        if exclude_edge and edge_only:
            continue
        if comp.cell_count >= sel.min_component_cells and comp.correspondence_count >= sel.min_component_correspondences:
            eligible.append(comp)

    # deterministic ordering: largest evidence first
    eligible.sort(key=lambda c: (-c.cell_count, -c.correspondence_count, c.component_id))

    if not eligible:
        return SelectionPlan(
            selection_outcome=INSUFFICIENT,
            decision_reason="NO_ELIGIBLE_COMPONENT",
            selected_cell_ids=set(),
            selected_component_ids=[],
            selected_cells_covered=False,
            trace={
                "policy": cfg.selection_policy(),
                "eligibility": "no component met min_component_cells and min_component_correspondences",
            },
        )

    selected_comps: list[ComponentInfo] = []
    selected_ids: set[str] = set()
    for comp in eligible:
        selected_comps.append(comp)
        selected_ids.update(comp.cells)
        if len(selected_ids) >= sel.min_selected_region_cells:
            break

    covered = len(selected_ids) >= sel.min_selected_region_cells
    if not covered:
        return SelectionPlan(
            selection_outcome=INSUFFICIENT,
            decision_reason="BELOW_MIN_SELECTED_REGION_CELLS",
            selected_cell_ids=set(),
            selected_component_ids=[],
            selected_cells_covered=False,
            trace={
                "policy": cfg.selection_policy(),
                "candidate_cells": len(selected_ids),
                "threshold": sel.min_selected_region_cells,
            },
        )

    return SelectionPlan(
        selection_outcome=SELECTED,
        decision_reason="SUPPORTED_REGION_SELECTED",
        selected_cell_ids=selected_ids,
        selected_component_ids=[c.component_id for c in selected_comps],
        selected_cells_covered=True,
        trace={
            "policy": cfg.selection_policy(),
            "component_ids": [c.component_id for c in selected_comps],
            "selected_cell_count": len(selected_ids),
            "edge_touching_components_excluded": exclude_edge,
        },
    )


def assign_reasons(
    grid: Grid,
    cfg: SpatialReliabilityConfig,
    result: ReliabilityResult,
    plan: SelectionPlan,
    *,
    cell_keys: list[str],  # scene cell id per verified record, "" if not mappable
    row_keys: list[int],
    col_keys: list[int],
    tile_ids: list[str],
    candidate_indices: list[int],
) -> tuple[list[str], list[list[str]], list[bool]]:
    """Return (primary_reason, secondary_reasons, final_selected, capped) per record."""
    from backend.app.spatial.states import SelectionReasonCode as RC

    cell_by_id = {c.cell_id: c for c in result.cells}
    comp_cells: dict[str, str] = {}
    for comp in result.components:
        for cid in comp.cells:
            comp_cells[cid] = comp.component_id
    projected: set[str] = set()
    for comp in result.components:
        if comp.cell_count >= cfg.selection.min_component_cells:
            projected.add(comp.component_id)

    primary: list[str] = []
    secondary: list[list[str]] = []
    eligible_flag: list[bool] = []
    for key, rid, cid in zip(cell_keys, row_keys, col_keys):
        if not key:
            primary.append(RC.SR_NOT_MAPPABLE.value)
            secondary.append([])
            eligible_flag.append(False)
            continue
        cell = cell_by_id.get(key)
        if cell is None or not cell.reliable:
            primary.append(RC.SR_EXCLUDED_LOW_SPATIAL_SUPPORT.value)
            secondary.append([])
            eligible_flag.append(False)
            continue
        comp_sel = comp_cells.get(key)
        if comp_sel is None:
            primary.append(RC.SR_EXCLUDED_ISOLATED.value)
            secondary.append([])
            eligible_flag.append(False)
            continue
        if key in plan.selected_cell_ids:
            reasons = [RC.SR_SELECTED_SUPPORTED_REGION.value]
            if cell.supported:
                reasons.append(RC.SR_SELECTED_NEIGHBOR_SUPPORTED.value)
            if plan.selected_cells_covered:
                reasons.append(RC.SR_SELECTED_SPATIAL_COVERAGE.value)
            primary.append(RC.SR_SELECTED_SUPPORTED_REGION.value)
            secondary.append(reasons[1:])
            eligible_flag.append(True)
            continue
        if comp_sel in plan.selected_component_ids:
            primary.append(RC.SR_EXCLUDED_OUTSIDE_SELECTED_REGION.value)
            secondary.append([])
            eligible_flag.append(False)
            continue
        if comp_sel in projected:
            primary.append(RC.SR_EXCLUDED_OUTSIDE_SELECTED_REGION.value)
            secondary.append([])
            eligible_flag.append(False)
            continue
        primary.append(RC.SR_EXCLUDED_LOW_SPATIAL_SUPPORT.value)
        secondary.append([])
        eligible_flag.append(False)

    # deterministic final subset + cap
    selected = []
    for idx, flag in enumerate(eligible_flag):
        if flag:
            selected.append(idx)
    selected.sort(key=lambda i: (row_keys[i], col_keys[i], tile_ids[i], candidate_indices[i]))
    cap = cfg.selection.max_selected_correspondences
    limited = len(selected) > cap
    keep = set(selected[:cap] if limited else selected)
    final_selected: list[bool] = []
    for i in range(len(cell_keys)):
        if i in keep:
            final_selected.append(True)
        elif i in set(selected):
            final_selected.append(False)
            primary[i] = RC.SR_EXCLUDED_LIMIT.value
            secondary[i] = []
        else:
            final_selected.append(False)
    return primary, secondary, final_selected, limited