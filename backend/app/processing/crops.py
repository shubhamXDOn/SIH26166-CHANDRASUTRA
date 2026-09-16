"""Controlled crop/tile generation within the confirmed overlap region (M2).

Tiles are sensor-native (no resampling in M2, see the resampling policy in
config) and cover the overlap region for each sensor. Every tile records its
sensor, pixel window, ground box, valid-data fraction and id (CS-P001-T001…).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import ProcessingConfig
from .overlap import PixelRegion


@dataclass
class Tile:
    tile_id: str
    sensor: str
    side: str
    row_start: int
    col_start: int
    width: int
    height: int
    valid_fraction: float
    clipped: bool
    too_small: bool
    ground_box: dict | None
    sequence: int
    preview_filename: str
    array_filename: str


def generate_tiles(
    display_arr: np.ndarray,
    mask: np.ndarray,
    region: PixelRegion,
    *,
    sensor: str,
    side: str,
    pair_id: str,
    cfg: ProcessingConfig,
) -> list[Tile]:
    """Generate a deterministic grid of tiles covering the overlap region.

    ``side`` is 'a' or 'b' and used only for preview/array file naming the
    caller resolves; tiles are recorded per sensor. A tile is clipped when the
    window extends past the region or image edge, and flagged ``too_small``
    when either dimension is below the configured usability floor.
    """
    if region.width_px <= 0 or region.height_px <= 0:
        return []

    size = cfg.crop_size_px
    stride = cfg.crop_stride_px
    min_w = cfg.min_tile_width_px
    min_h = cfg.min_tile_height_px

    rows = np.arange(region.row_start, region.row_end, stride)
    cols = np.arange(region.col_start, region.col_end, stride)

    tiles: list[Tile] = []
    seq = 0
    for r0 in rows:
        for c0 in cols:
            r1 = min(r0 + size, region.row_end)
            c1 = min(c0 + size, region.col_end)
            width = c1 - c0
            height = r1 - r0
            if width <= 0 or height <= 0:
                continue
            seq += 1
            window = mask[r0:r1, c0:c1]
            total = window.size
            valid_fraction = round(float(np.count_nonzero(window == 0)) / total, 6) if total else 0.0
            clipped = width < size or height < size
            too_small = width < min_w or height < min_h
            tiles.append(
                Tile(
                    tile_id=f"{pair_id}-T{seq:03d}",
                    sensor=sensor,
                    side=side,
                    row_start=r0,
                    col_start=c0,
                    width=width,
                    height=height,
                    valid_fraction=valid_fraction,
                    clipped=clipped,
                    too_small=too_small,
                    ground_box=None,  # filled by caller with region meters
                    sequence=seq,
                    preview_filename=f"{pair_id}_T{seq:03d}.png",
                    array_filename=f"{pair_id}_T{seq:03d}.npy",
                )
            )
    return tiles


def tile_to_dict(tile: Tile) -> dict[str, Any]:
    return {
        "tile_id": tile.tile_id,
        "sensor": tile.sensor,
        "side": tile.side,
        "row_start": tile.row_start,
        "col_start": tile.col_start,
        "width": tile.width,
        "height": tile.height,
        "valid_fraction": tile.valid_fraction,
        "clipped": tile.clipped,
        "too_small": tile.too_small,
        "ground_box": tile.ground_box,
        "array_filename": tile.array_filename,
        "preview_filename": tile.preview_filename,
    }