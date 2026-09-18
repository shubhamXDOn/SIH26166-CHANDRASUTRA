"""M6 strict loader for M5 selected correspondences + spatial artifacts.

Validates: file exists, pair ID matches, M5 status COMPLETE, selection outcome usable,
arrays exist/finite/matching lengths, source tile IDs valid, component IDs valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.app.spatial.states import SpatialRunState

_REQUIRED_NPZ_KEYS = frozenset({
    "x_a", "y_a", "x_b", "y_b",
    "scene_x", "scene_y", "scene_side",
    "source_tile_id", "source_candidate_index",
    "side_a_cell_id", "side_b_cell_id",
    "component_id", "selection_reason",
})


@dataclass
class LoadedEvidence:
    pair_id: str
    n_correspondences: int
    x_a: np.ndarray
    y_a: np.ndarray
    x_b: np.ndarray
    y_b: np.ndarray
    scene_x: np.ndarray
    scene_y: np.ndarray
    scene_side: np.ndarray
    source_tile_id: np.ndarray
    source_candidate_index: np.ndarray
    side_a_cell_id: np.ndarray
    side_b_cell_id: np.ndarray
    component_id: np.ndarray
    selection_reason: np.ndarray
    unique_tile_ids: list[str]
    unique_component_ids: list[str]
    m5_status: dict
    m5_summary: dict


class LoaderError(Exception):
    pass


def load_selected_correspondences(
    data_root: Path,
    pair_id: str,
    spatial_service,
) -> LoadedEvidence:
    run_dir = spatial_service.find_run_for_pair(pair_id)
    if run_dir is None:
        raise LoaderError("M5_NOT_AVAILABLE: No spatial run found for this pair.")

    status_path = run_dir / "status.json"
    if not status_path.is_file():
        raise LoaderError("M5_NOT_AVAILABLE: status.json missing.")
    try:
        with open(status_path, encoding="utf-8") as f:
            status = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise LoaderError(f"M5_NOT_AVAILABLE: cannot parse status.json: {e}")

    if status.get("state") != SpatialRunState.COMPLETE.value:
        raise LoaderError(
            f"M5_NOT_COMPLETE: M5 state is {status.get('state')}, expected COMPLETE."
        )

    selection_path = run_dir / "selection.json"
    if selection_path.is_file():
        try:
            with open(selection_path, encoding="utf-8") as f:
                selection = json.load(f)
            outcome = selection.get("selection_outcome") or selection.get("outcome", "")
            if outcome not in ("SELECTED",):
                raise LoaderError(
                    f"NO_SELECTION: M5 selection outcome is {outcome}, expected SELECTED."
                )
        except (OSError, json.JSONDecodeError):
            raise LoaderError("NO_SELECTION: Cannot read selection.json.")

    summary_path = run_dir / "summary.json"
    try:
        with open(summary_path, encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, json.JSONDecodeError):
        summary = {}

    npz_path = run_dir / "selected_correspondences.npz"
    if not npz_path.is_file():
        raise LoaderError("NO_SELECTION: selected_correspondences.npz not found.")

    try:
        data = np.load(str(npz_path), allow_pickle=False)
    except Exception as e:
        raise LoaderError(f"COORDINATE_LOAD_FAILED: Cannot read npz: {e}")

    missing = _REQUIRED_NPZ_KEYS - set(data.files)
    if missing:
        raise LoaderError(f"COORDINATE_LOAD_FAILED: Missing npz keys: {sorted(missing)}")

    x_a = np.asarray(data["x_a"], dtype=np.float64).ravel()
    y_a = np.asarray(data["y_a"], dtype=np.float64).ravel()
    x_b = np.asarray(data["x_b"], dtype=np.float64).ravel()
    y_b = np.asarray(data["y_b"], dtype=np.float64).ravel()
    scene_x = np.asarray(data["scene_x"], dtype=np.float64).ravel()
    scene_y = np.asarray(data["scene_y"], dtype=np.float64).ravel()
    scene_side = np.asarray(data["scene_side"], dtype="U1").ravel()
    source_tile_id = np.asarray(data["source_tile_id"], dtype="U64").ravel()
    source_candidate_index = np.asarray(data["source_candidate_index"], dtype=np.int64).ravel()
    side_a_cell_id = np.asarray(data["side_a_cell_id"], dtype="U16").ravel()
    side_b_cell_id = np.asarray(data["side_b_cell_id"], dtype="U16").ravel()
    component_id = np.asarray(data["component_id"], dtype="U16").ravel()
    selection_reason = np.asarray(data["selection_reason"], dtype="U64").ravel()

    n = len(x_a)
    if n == 0:
        raise LoaderError("INSUFFICIENT_EVIDENCE: Zero selected correspondences.")

    lengths = [len(y_a), len(x_b), len(y_b), len(scene_x), len(scene_y),
               len(scene_side), len(source_tile_id), len(source_candidate_index),
               len(side_a_cell_id), len(side_b_cell_id), len(component_id),
               len(selection_reason)]
    if any(l != n for l in lengths):
        raise LoaderError("COORDINATE_LOAD_FAILED: Array length mismatch (LENGTH_MISMATCH) in npz.")

    if not np.any(np.isfinite(x_a) & np.isfinite(y_a) & np.isfinite(x_b) & np.isfinite(y_b)):
        raise LoaderError("INSUFFICIENT_EVIDENCE: No finite coordinate pairs.")

    valid_finite = np.sum(np.isfinite(x_a) & np.isfinite(y_a) & np.isfinite(x_b) & np.isfinite(y_b))
    if valid_finite < 4:
        raise LoaderError(
            f"INSUFFICIENT_EVIDENCE: Only {valid_finite} finite correspondences (< 4 minimum)."
        )

    sides = scene_side
    bad_sides = np.unique(sides[~np.isin(sides, ("a", "b"))])
    if bad_sides.size:
        raise LoaderError(
            f"COORDINATE_LOAD_FAILED: scene_side contains invalid value(s): {sorted(map(str, bad_sides))}."
        )

    scene_finite = np.isfinite(scene_x) & np.isfinite(scene_y)
    if np.any(scene_finite & ((scene_x < 0.0) | (scene_x > 1.0) | (scene_y < 0.0) | (scene_y > 1.0))):
        raise LoaderError("COORDINATE_LOAD_FAILED: scene coordinates outside normalized [0, 1] range.")

    unique_tiles = sorted(set(source_tile_id.tolist()))
    unique_comps = sorted(set(component_id.tolist()))

    return LoadedEvidence(
        pair_id=pair_id,
        n_correspondences=n,
        x_a=x_a, y_a=y_a, x_b=x_b, y_b=y_b,
        scene_x=scene_x, scene_y=scene_y, scene_side=scene_side,
        source_tile_id=source_tile_id,
        source_candidate_index=source_candidate_index,
        side_a_cell_id=side_a_cell_id,
        side_b_cell_id=side_b_cell_id,
        component_id=component_id,
        selection_reason=selection_reason,
        unique_tile_ids=unique_tiles,
        unique_component_ids=unique_comps,
        m5_status=status,
        m5_summary=summary,
    )
