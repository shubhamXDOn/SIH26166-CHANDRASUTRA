"""Coordinate-space conversions for M6 registration.

Converts M5 selected correspondences from tile-local pixel space to sensor
pixel space, using mapping geometry from M5's scene mapping. Both spaces
are explicitly declared — never mixed without explicit conversion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class SensorOverlapBox:
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


@dataclass(frozen=True)
class TileOrigin:
    tile_id: str
    sensor: str
    side: str
    row_start: int
    col_start: int
    width: int
    height: int


def load_mapping_context(spatial_run_dir: Path) -> dict | None:
    mapping_path = spatial_run_dir / "mapping.json"
    if not mapping_path.is_file():
        return None
    try:
        with open(mapping_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _parse_overlap_boxes(mapping: dict) -> dict[str, SensorOverlapBox]:
    boxes: dict[str, SensorOverlapBox] = {}
    for sensor, r in (mapping.get("overlap") or {}).items():
        try:
            boxes[sensor] = SensorOverlapBox(
                sensor=str(sensor),
                row_start=int(r["row_start"]),
                row_end=int(r["row_end"]),
                col_start=int(r["col_start"]),
                col_end=int(r["col_end"]),
            )
        except (TypeError, KeyError, ValueError):
            continue
    return boxes


def _parse_tile_index(mapping: dict) -> dict[str, TileOrigin]:
    index: dict[str, TileOrigin] = {}
    for tid, t in (mapping.get("tile_index") or {}).items():
        try:
            index[str(tid)] = TileOrigin(
                tile_id=str(tid),
                sensor=str(t.get("sensor", "")),
                side=str(t.get("side", "")),
                row_start=int(t.get("row_start", 0)),
                col_start=int(t.get("col_start", 0)),
                width=int(t.get("width", 0)),
                height=int(t.get("height", 0)),
            )
        except (TypeError, KeyError, ValueError):
            continue
    return index


def build_tile_geometry_map(mapping: dict) -> dict[str, dict[str, TileOrigin]]:
    per_match: dict[str, dict[str, TileOrigin]] = {}
    tile_index = _parse_tile_index(mapping)
    for m in mapping.get("mappings", []):
        mid = str(m.get("match_tile_id", ""))
        ga = m.get("geometry_a")
        gb = m.get("geometry_b")
        geom_a = None
        geom_b = None
        if ga is not None:
            try:
                geom_a = TileOrigin(
                    tile_id=str(ga.get("tile_id", "")),
                    sensor=str(ga.get("sensor", "")),
                    side="a",
                    row_start=int(ga.get("row_start", 0)),
                    col_start=int(ga.get("col_start", 0)),
                    width=int(ga.get("width", 0)),
                    height=int(ga.get("height", 0)),
                )
            except (TypeError, KeyError, ValueError):
                geom_a = tile_index.get(str(ga.get("tile_id", "")))
        if gb is not None:
            try:
                geom_b = TileOrigin(
                    tile_id=str(gb.get("tile_id", "")),
                    sensor=str(gb.get("sensor", "")),
                    side="b",
                    row_start=int(gb.get("row_start", 0)),
                    col_start=int(gb.get("col_start", 0)),
                    width=int(gb.get("width", 0)),
                    height=int(gb.get("height", 0)),
                )
            except (TypeError, KeyError, ValueError):
                geom_b = tile_index.get(str(gb.get("tile_id", "")))
        per_match[mid] = {"a": geom_a, "b": geom_b}
    return per_match


def tile_local_to_sensor_pixel(
    x_local: np.ndarray,
    y_local: np.ndarray,
    tile_origin: TileOrigin | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(x_local)
    if tile_origin is None:
        nan = np.full(n, np.nan)
        return nan, nan, np.zeros(n, dtype=bool)
    px_x = x_local + float(tile_origin.col_start)
    px_y = y_local + float(tile_origin.row_start)
    valid = np.isfinite(x_local) & np.isfinite(y_local)
    return px_x, px_y, valid


def normalized_to_sensor_pixel(
    nx: np.ndarray,
    ny: np.ndarray,
    overlap_box: SensorOverlapBox | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(nx)
    if overlap_box is None or overlap_box.width_px <= 0 or overlap_box.height_px <= 0:
        nan = np.full(n, np.nan)
        return nan, nan, np.zeros(n, dtype=bool)
    px_x = np.asarray(nx, dtype=np.float64) * overlap_box.width_px + overlap_box.col_start
    px_y = np.asarray(ny, dtype=np.float64) * overlap_box.height_px + overlap_box.row_start
    valid = np.isfinite(nx) & np.isfinite(ny)
    return px_x, px_y, valid


def build_sensor_pixel_points(
    x_a: np.ndarray,
    y_a: np.ndarray,
    x_b: np.ndarray,
    y_b: np.ndarray,
    source_tile_ids: np.ndarray,
    tile_geom_map: dict[str, dict[str, TileOrigin]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(x_a)
    pts_a = np.full((n, 2), np.nan, dtype=np.float64)
    pts_b = np.full((n, 2), np.nan, dtype=np.float64)
    valid = np.zeros(n, dtype=bool)
    for i in range(n):
        tid = str(source_tile_ids[i])
        geom = tile_geom_map.get(tid)
        if geom is None:
            continue
        ga = geom.get("a")
        gb = geom.get("b")
        if ga is None or gb is None:
            continue
        if not np.isfinite(x_a[i]) or not np.isfinite(y_a[i]):
            continue
        if not np.isfinite(x_b[i]) or not np.isfinite(y_b[i]):
            continue
        pts_a[i, 0] = float(x_a[i]) + float(ga.col_start)
        pts_a[i, 1] = float(y_a[i]) + float(ga.row_start)
        pts_b[i, 0] = float(x_b[i]) + float(gb.col_start)
        pts_b[i, 1] = float(y_b[i]) + float(gb.row_start)
        valid[i] = True
    return pts_a[:, 0], pts_a[:, 1], pts_b[:, 0], pts_b[:, 1], valid
