"""M8 SPATIAL — pure spatial analysis + balanced selection engine.

Deterministic by construction: no I/O, no RNG, cell assignment and selection
order are fully reproducible from the same trusted input set and config.
The engine never re-decides the M7 verdict; it receives the recovered trusted
correspondences and produces spatial bookkeeping + a balanced selection.
"""

from __future__ import annotations

import numpy as np

from . import states
from .analysis import spatial_analysis
from .config import SpatialSelectionConfig
from .grid import cell_of_point_grid, grid_counts
from .selection import select_balanced


def _dims_ok(dims_a: dict, dims_b: dict) -> bool:
    for dims in (dims_a, dims_b):
        if not isinstance(dims, dict):
            return False
        if not (dims.get("height") and dims.get("width")):
            return False
        if float(dims.get("height") or 0) <= 0 or float(dims.get("width") or 0) <= 0:
            return False
    return True


def _explanation(state: str, reasons: list[str], trusted: int, selected: int, excluded: int) -> str:
    if state == states.SELECTED:
        return (
            f"Spatial selection produced {selected} of {trusted} trusted "
            f"correspondences (excluded {excluded}). Deterministic spatial "
            "bookkeeping only; no accuracy or registration claim."
        )
    if state == states.SELECTED_WITH_WARNINGS:
        return (
            f"Spatial selection produced {selected} of {trusted} trusted "
            f"correspondences with recorded spatial warnings ({', '.join(reasons)}). "
            "Warnings are bookkeeping evidence; no accuracy or registration claim."
        )
    return f"ABSTAIN because: {', '.join(reasons)}."


def analyze_and_select(
    trusted: list[dict],
    dims_a: dict,
    dims_b: dict,
    cfg: SpatialSelectionConfig,
) -> dict:
    """Run the M8 spatial analysis + balanced selection over the trusted set.

    ``trusted`` entries carry at least: m8_index, m7_index, x_a, y_a, x_b, y_b,
    residual. Overview-level guarding (ZERO/FEW trusted, coordinate frame) is
    handled here so the engine is self-contained and pure.
    """
    if not _dims_ok(dims_a, dims_b):
        return _blocked(
            states.INVALID_COORDINATE_FRAME,
            "One or both effective matcher planes could not be declared; refusing "
            "to assign cells to an undefined coordinate frame.",
        )

    n = len(trusted)
    if n == 0:
        return _abstain(
            states.ZERO_TRUSTED,
            "The M7 trusted set is empty; there is nothing to analyse or select.",
        )
    if n < max(cfg.selection.min_trusted, 1):
        return _abstain(
            states.FEW_TRUSTED,
            f"Only {n} trusted correspondences (minimum {cfg.selection.min_trusted}); "
            "spatial selection is not meaningful at this scale.",
        )

    pts_a = np.asarray([[e["x_a"], e["y_a"]] for e in trusted], dtype=np.float64)
    pts_b = np.asarray([[e["x_b"], e["y_b"]] for e in trusted], dtype=np.float64)
    height_a = float(dims_a["height"])
    width_a = float(dims_a["width"])
    height_b = float(dims_b["height"])
    width_b = float(dims_b["width"])

    cells_a = cell_of_point_grid(pts_a, height_a, width_a, cfg.grid.rows, cfg.grid.cols)
    cells_b = cell_of_point_grid(pts_b, height_b, width_b, cfg.grid.rows, cfg.grid.cols)

    trusted_with_cells: list[dict] = []
    for i, e in enumerate(trusted):
        cell_a = (int(cells_a[i, 0]), int(cells_a[i, 1]))
        cell_b = (int(cells_b[i, 0]), int(cells_b[i, 1]))
        trusted_with_cells.append({**e, "source_cell": cell_a, "target_cell": cell_b})

    blocks = spatial_analysis(
        pts_a,
        pts_b,
        grid_counts(pts_a, height_a, width_a, cfg.grid)["occupancy"],
        grid_counts(pts_b, height_b, width_b, cfg.grid)["occupancy"],
        dims_a,
        dims_b,
        cfg.coverage,
    )

    source_block = blocks["a"]
    target_block = blocks["b"]

    warnings: list[str] = []
    if source_block["occupied_cells"] < cfg.selection.min_occupied_cells:
        warnings.append(states.FEW_OCCUPIED_CELLS)
    if source_block["coverage_ratio"] < cfg.coverage.low_coverage_ratio:
        warnings.append(states.LOW_SOURCE_COVERAGE)
    if target_block["coverage_ratio"] < cfg.coverage.low_coverage_ratio:
        warnings.append(states.LOW_TARGET_COVERAGE)
    if source_block["concentration_ratio"] is not None and \
            source_block["concentration_ratio"] > cfg.coverage.concentration_ratio:
        warnings.append(states.CONCENTRATED_SOURCE)
    if target_block["concentration_ratio"] is not None and \
            target_block["concentration_ratio"] > cfg.coverage.concentration_ratio:
        warnings.append(states.CONCENTRATED_TARGET)
    if _has_edges(pts_a, height_a, width_a) or _has_edges(pts_b, height_b, width_b):
        warnings.append(states.BOUNDARY_POINTS_REPORTED)

    selection = select_balanced(trusted_with_cells, cfg.selection)
    if selection.get("state") == "ABSTAIN":
        return _abstain(selection.get("code", states.NO_VALID_SELECTION),
                        f"Spatial selection abstained: {selection.get('code')}.")

    selected_idx_set = set(selection["selected"])
    selected_entries = [e for e in trusted_with_cells if e["m8_index"] in selected_idx_set]
    selected_count = len(selected_entries)
    if selected_count < max(cfg.selection.min_selected, 1):
        return _abstain(
            states.NO_VALID_SELECTION,
            f"Selection yielded {selected_count} correspondences "
            f"(minimum {cfg.selection.min_selected}); spatial selection cannot be recorded.",
        )

    if selection.get("limit_applied") and cfg.selection.limit_applied_warning:
        warnings.append(states.SELECTION_LIMIT_APPLIED)
    warnings = list(dict.fromkeys(warnings))

    state = states.SELECTED_WITH_WARNINGS if warnings else states.SELECTED
    reasons = list(warnings) if warnings else ["SPATIAL_BOOKKEEPING_OK"]
    evidence = {
        "trusted_count": n,
        "selected_count": selected_count,
        "excluded_count": len(selection["excluded"]),
        "limit_applied": bool(selection.get("limit_applied")),
        "analysis": blocks,
        "selection_record": {
            "policy": selection.get("policy", cfg.selection.policy),
            "tie_break": selection.get("tie_break", cfg.selection.tie_break),
            "max_selected": selection.get("max_selected", cfg.selection.max_selected),
            "selected": [
                {
                    "m8_index": int(e["m8_index"]),
                    "m7_index": int(e["m7_index"]),
                    "match_index_a": e.get("match_index_a"),
                    "match_index_b": e.get("match_index_b"),
                    "x_a": float(e["x_a"]), "y_a": float(e["y_a"]),
                    "x_b": float(e["x_b"]), "y_b": float(e["y_b"]),
                    "residual": round(float(e.get("residual") or 0.0), 9),
                }
                for e in selected_entries
            ],
            "excluded_indexes": list(sorted(selection["excluded"])),
        },
        "frame": {
            "frame": "EFFECTIVE_MATCHER_PLANE",
            "side_a": {"effective_dimensions": dims_a},
            "side_b": {"effective_dimensions": dims_b},
        },
    }

    return {
        "decision": {
            "state": state,
            "reasons": reasons,
            "explanation": _explanation(state, reasons, n, selected_count, len(selection["excluded"])),
            "block_code": None,
            "abstain_code": None,
        },
        "evidence": evidence,
        "warnings": warnings,
    }


def _has_edges(pts: np.ndarray, height: float, width: float) -> bool:
    xs = pts[:, 0]
    ys = pts[:, 1]
    return bool(np.any(np.logical_or(
        np.logical_or(xs < 0, ys < 0),
        np.logical_or(xs >= width, ys >= height),
    )))


def _abstain(code: str, explanation: str) -> dict:
    return {
        "decision": {
            "state": states.ABSTAIN,
            "reasons": [code],
            "explanation": explanation,
            "block_code": None,
            "abstain_code": code,
        },
        "evidence": {"trusted_count": None},
        "warnings": [],
    }


def _blocked(code: str, explanation: str) -> dict:
    return {
        "decision": {
            "state": states.BLOCKED,
            "reasons": [code],
            "explanation": explanation,
            "block_code": code,
            "abstain_code": None,
        },
        "evidence": {},
        "warnings": [],
    }


__all__ = ["analyze_and_select"]