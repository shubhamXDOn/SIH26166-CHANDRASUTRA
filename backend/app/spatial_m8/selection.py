"""M8 SPATIAL — deterministic GRID_BALANCED correspondence selection.

Selection is pure and deterministic (no RNG):

* entries are sorted by ``(residual asc, original index asc)``;
* phase 1 guarantees ``min_per_occupied_cell`` from each occupied source cell;
* phase 2 refills the remaining ``max_selected`` budget round-robin across
  occupied cells in row-major order, so spatially concentrated regions cannot
  swallow the whole budget;

The selected set is always a strict subset of the trusted input set.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .config import SelectionConfig


def select_balanced(entries: list[dict[str, Any]], cfg: SelectionConfig) -> dict[str, Any]:
    """Return the balanced selection record (no I/O, fully deterministic)."""
    min_trusted = max(cfg.min_trusted, 1)
    if len(entries) < min_trusted:
        return {
            "state": "ABSTAIN",
            "code": "FEW_TRUSTED",
            "selected": [],
            "excluded": [],
            "limit_applied": False,
        }
    if not entries:
        return {
            "state": "ABSTAIN",
            "code": "ZERO_TRUSTED",
            "selected": [],
            "excluded": [],
            "limit_applied": False,
        }

    ordered = sorted(entries, key=lambda e: (e.get("residual") or 0.0, int(e.get("m7_index") or 0)))
    limit = max(int(cfg.max_selected), 1)

    if len(ordered) <= limit:
        selected = [int(e["m8_index"]) for e in ordered]
        excluded: list[int] = []
        return {
            "state": "SELECTED",
            "selected": selected,
            "excluded": excluded,
            "limit_applied": False,
            "policy": cfg.policy,
            "tie_break": cfg.tie_break,
            "max_selected": limit,
        }

    by_cell: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for e in ordered:
        by_cell[tuple(e.get("source_cell") or (0, 0))].append(e)
    cells = sorted(by_cell.keys())

    per_cell_min = max(int(cfg.min_per_occupied_cell), 0)
    budget = limit
    selected_indices: list[int] = []

    def take(cell: tuple[int, int], count: int) -> None:
        nonlocal budget
        lst = by_cell[cell]
        take_n = min(count, len(lst), budget)
        selected_indices.extend(int(e["m8_index"]) for e in lst[:take_n])
        budget -= take_n

    for cell in cells:
        if budget <= 0:
            break
        take(cell, per_cell_min)

    pointers = {cell: max(per_cell_min, 0) for cell in cells}
    while budget > 0:
        progressed = False
        for cell in cells:
            if budget <= 0:
                break
            lst = by_cell[cell]
            i = pointers[cell]
            if i < len(lst):
                selected_indices.append(int(lst[i]["m8_index"]))
                pointers[cell] = i + 1
                budget -= 1
                progressed = True
        if not progressed:
            break

    selected_set = set(selected_indices)
    excluded = [int(e["m8_index"]) for e in ordered if e["m8_index"] not in selected_set]
    return {
        "state": "SELECTED",
        "selected": selected_indices,
        "excluded": excluded,
        "limit_applied": True,
        "policy": cfg.policy,
        "tie_break": cfg.tie_break,
        "max_selected": limit,
    }


__all__ = ["select_balanced"]