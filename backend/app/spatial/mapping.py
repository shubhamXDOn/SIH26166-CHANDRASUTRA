"""M5 scene coordinate model + tile → scene mapping.

Coordinate space is ``pair_overlap_normalized``: every correspondence moves
from its sensor-native tile window (tile-local px) to the sensor's pair
overlap bounding box (image px), then to normalized [0, 1]² scene
coordinates. Both sensors are normalised to their OWN overlap box so the A
and B scenes become comparable grids. Tiles that cannot be mapped safely are
marked NOT_MAPPABLE with an explicit reason — never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .states import MappingReason, MappingStatus


@dataclass(frozen=True)
class OverlapBox:
    sensor: str
    row_start: int
    row_end: int
    col_start: int
    col_end: int

    @property
    def width_px(self) -> int:
        return max(0, self.col_end - self.col_start)

    @property
    def height_px(self) -> int:
        return max(0, self.row_end - self.row_start)

    def to_dict(self) -> dict:
        return {
            "sensor": self.sensor,
            "row_start": self.row_start,
            "row_end": self.row_end,
            "col_start": self.col_start,
            "col_end": self.col_end,
            "width_px": self.width_px,
            "height_px": self.height_px,
        }


@dataclass(frozen=True)
class TileGeometry:
    tile_id: str
    sensor: str
    side: str
    row_start: int
    col_start: int
    width: int
    height: int


@dataclass(frozen=True)
class TileSceneMapping:
    match_tile_id: str
    tile_a: str
    tile_b: str
    sensor_a: str
    sensor_b: str
    geometry_a: TileGeometry | None
    geometry_b: TileGeometry | None
    status: MappingStatus
    reason: MappingReason


def load_scene_map(
    processing_root: Path,
    match_run_dir: Path,
    match_summary: dict,
    edge_tolerance_px: float = 0.5,
) -> dict:
    """Build the coordinate-space declaration + per-match-tile mappings.

    Also returns the raw overlap boxes and tile index so the caller can map
    correspondence points without re-reading files.
    """
    proc_cfg_dir = processing_root
    overlap_box, tile_index = _load_m2_context(proc_cfg_dir)
    from .states import MappingReason as MR

    if overlap_box is None or tile_index is None:
        return {
            "coordinate_space": "pair_overlap_normalized",
            "status": MappingStatus.NOT_MAPPABLE.value,
            "reason": MR.MISSING_OVERLAP_GEOMETRY.value,
            "overlap": {},
            "tile_index": {},
            "mappings": [],
            "edge_tolerance_px": edge_tolerance_px,
        }

    mappings: list[dict] = []
    for mt in match_summary.get("per_tile", []):
        mid = str(mt.get("match_tile_id", ""))
        decision = _load_tile_decision(match_run_dir, mid)
        tile_a = str(decision.get("tile_a", ""))
        tile_b = str(decision.get("tile_b", ""))
        geom_a = tile_index.get(tile_a)
        geom_b = tile_index.get(tile_b)
        if geom_a is None or geom_b is None:
            reason, status = MR.MISSING_TILE_GEOMETRY, MappingStatus.NOT_MAPPABLE
        else:
            reason, status = MR.MAP_OK, MappingStatus.MAPPED
        mappings.append({
            "match_tile_id": mid,
            "tile_a": tile_a,
            "tile_b": tile_b,
            "sensor_a": geom_a["sensor"] if geom_a else None,
            "sensor_b": geom_b["sensor"] if geom_b else None,
            "geometry_a": geom_a,
            "geometry_b": geom_b,
            "status": status.value,
            "reason": reason.value,
        })

    return {
        "coordinate_space": "pair_overlap_normalized",
        "status": MappingStatus.MAPPED.value,
        "reason": MR.MAP_OK.value,
        "overlap": {k: v.to_dict() for k, v in overlap_box.items()},
        "tile_index": tile_index,
        "mappings": mappings,
        "edge_tolerance_px": edge_tolerance_px,
    }


def map_correspondences(
    scene: dict,
    mapping: dict | None,
    side: str,
    x_local: np.ndarray,
    y_local: np.ndarray,
    edge_tolerance_px: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Map tile-local x/y arrays (one tile) to normalized scene coords.

    Returns (nx, ny, mapped_mask, unique_reasons). Non-finite input and out-of
    scene points are marked not mapped with their reason.
    """
    if mapping is None or mapping.get("status") != MappingStatus.MAPPED.value:
        shape = np.shape(x_local)
        n = int(np.prod(shape)) if shape else 0
        nan = np.full(n, np.nan)
        mask = np.zeros(n, dtype=bool)
        return nan, nan, mask, [MappingReason.TILE_NOT_MAPPED_TO_TWO_SIDES.value]

    geom_key = "geometry_a" if side == "a" else "geometry_b"
    geom = mapping.get(geom_key)
    if geom is None:
        shape = np.shape(x_local)
        n = int(np.prod(shape)) if shape else 0
        nan = np.full(n, np.nan)
        return nan, nan, np.zeros(n, dtype=bool), [MappingReason.TILE_NOT_MAPPED_TO_TWO_SIDES.value]

    sensor = geom.get("sensor")
    boxd = scene["overlap"].get(sensor)
    if boxd is None:
        shape = np.shape(x_local)
        n = int(np.prod(shape)) if shape else 0
        nan = np.full(n, np.nan)
        return nan, nan, np.zeros(n, dtype=bool), [MappingReason.MISSING_OVERLAP_GEOMETRY.value]

    width = boxd.get("width_px", 0)
    height = boxd.get("height_px", 0)
    if width <= 0 or height <= 0:
        shape = np.shape(x_local)
        n = int(np.prod(shape)) if shape else 0
        nan = np.full(n, np.nan)
        return nan, nan, np.zeros(n, dtype=bool), [MappingReason.ZERO_AREA_OVERLAP.value]

    x = np.asarray(x_local, dtype=np.float64).ravel()
    y = np.asarray(y_local, dtype=np.float64).ravel()
    finite = np.isfinite(x) & np.isfinite(y)
    px_x = x + float(geom.get("col_start", 0))
    px_y = y + float(geom.get("row_start", 0))
    tol = float(edge_tolerance_px)
    in_range = (
        (px_x >= boxd["col_start"] - tol) & (px_x <= boxd["col_end"] + tol)
        & (px_y >= boxd["row_start"] - tol) & (px_y <= boxd["row_end"] + tol)
    )
    mapped = finite & in_range
    nx = np.full_like(x, np.nan)
    ny = np.full_like(y, np.nan)
    if np.any(mapped):
        nx[mapped] = np.clip(
            (px_x[mapped] - boxd["col_start"]) / width, 0.0, 1.0)
        ny[mapped] = np.clip(
            (px_y[mapped] - boxd["row_start"]) / height, 0.0, 1.0)
    reasons: list[str] = []
    reasons.append(MappingReason.MAP_OK.value)
    if not np.all(finite):
        reasons.append(MappingReason.NON_FINITE_COORDINATES.value)
    if np.any(finite & ~in_range) or (~finite).any():
        reasons.append(MappingReason.OUT_OF_SCENE.value)
    return nx, ny, mapped, reasons


def resolve_geometry(mapping: dict, side: str) -> TileGeometry | None:
    g = mapping.get("geometry_a" if side == "a" else "geometry_b")
    if not g:
        return None
    return TileGeometry(
        tile_id=str(g.get("tile_id", "")),
        sensor=str(g.get("sensor", "")),
        side=str(g.get("side", side)),
        row_start=int(g.get("row_start", 0)),
        col_start=int(g.get("col_start", 0)),
        width=int(g.get("width", 0)),
        height=int(g.get("height", 0)),
    )


def _deepest(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    deepest: Path | None = None
    for proc_dir in sorted(root.iterdir()):
        if proc_dir.is_dir():
            deepest = proc_dir
    return deepest


def _load_m2_context(proc_run: Path | None) -> tuple[dict | None, dict | None]:
    if proc_run is None:
        return None, None
    overlap_path = proc_run / "diagnostics" / "overlap.json"
    tiles_path = proc_run / "crops" / "tiles.json"
    try:
        with open(overlap_path, encoding="utf-8") as f:
            overlap = json.load(f)
        with open(tiles_path, encoding="utf-8") as f:
            tiles = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None, None

    regions: dict[str, OverlapBox] = {}
    for sensor, r in (overlap.get("regions") or {}).items():
        try:
            box = OverlapBox(
                sensor=str(sensor),
                row_start=int(r.get("row_start", 0)),
                row_end=int(r.get("row_end", 0)),
                col_start=int(r.get("col_start", 0)),
                col_end=int(r.get("col_end", 0)),
            )
        except (TypeError, ValueError):
            continue
        regions[sensor] = box
    if not regions:
        return None, None

    tile_index: dict[str, dict] = {}
    for t in tiles.get("tiles", []):
        try:
            tile_index[str(t["tile_id"])] = {
                "tile_id": str(t["tile_id"]),
                "sensor": str(t.get("sensor", "")),
                "side": str(t.get("side", "")),
                "row_start": int(t.get("row_start", 0)),
                "col_start": int(t.get("col_start", 0)),
                "width": int(t.get("width", 0)),
                "height": int(t.get("height", 0)),
                "array_filename": str(t.get("array_filename", "")),
            }
        except (TypeError, ValueError, KeyError):
            continue
    if not tile_index:
        return regions or None, None
    return regions, tile_index


def _load_tile_decision(match_run_dir: Path, match_tile_id: str) -> dict:
    cand_json = match_run_dir / "candidates" / f"{match_tile_id}.json"
    if not cand_json.is_file():
        return {}
    try:
        with open(cand_json, encoding="utf-8") as f:
            payload = json.load(f)
        return payload.get("decision") or {}
    except (OSError, json.JSONDecodeError):
        return {}