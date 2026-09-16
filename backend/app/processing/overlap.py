"""Overlap preparation: common ground envelope + per-sensor pixel regions (M2)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import FootprintBox, GeometryPlan


@dataclass
class PixelRegion:
    sensor: str
    row_start: int
    row_end: int
    col_start: int
    col_end: int
    width_px: int = 0
    height_px: int = 0

    def __post_init__(self) -> None:
        self.width_px = max(0, self.col_end - self.col_start)
        self.height_px = max(0, self.row_end - self.row_start)

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


@dataclass
class OverlapResult:
    status: str  # CONFIRMED_OVERLAP | OVERLAP_UNCONFIRMED | NO_OVERLAP | BLOCKED
    envelope: FootprintBox | None
    regions: dict[str, PixelRegion]
    source: str
    reason: str = ""
    blocked_code: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "source": self.source,
            "envelope_m": self.envelope.to_dict() if self.envelope else None,
            "regions": {k: v.to_dict() for k, v in self.regions.items()},
            "reason": self.reason,
            "blocked_code": self.blocked_code,
        }


def compute_overlap(plan: GeometryPlan, sensor_a: str, sensor_b: str) -> OverlapResult:
    """Intersect the two documented footprints and slice per-sensor pixels."""
    box_a = plan.products[sensor_a].box
    box_b = plan.products[sensor_b].box

    row_min = max(box_a.row_min_m, box_b.row_min_m)
    row_max = min(box_a.row_max_m, box_b.row_max_m)
    col_min = max(box_a.col_min_m, box_b.col_min_m)
    col_max = min(box_a.col_max_m, box_b.col_max_m)

    if row_max <= row_min or col_max <= col_min:
        return OverlapResult(
            status="NO_OVERLAP",
            envelope=None,
            regions={},
            source=plan.source,
            reason="The documented footprints do not intersect; there is no common ground area to crop.",
        )

    envelope = FootprintBox(row_min_m=row_min, row_max_m=row_max, col_min_m=col_min, col_max_m=col_max)

    regions: dict[str, PixelRegion] = {}
    for sensor in (sensor_a, sensor_b):
        g = plan.products[sensor]
        r0 = max(0, int((row_min - g.row_offset_m) // g.gsd_m))
        r1 = min(g.lines, int(np.ceil((row_max - g.row_offset_m) / g.gsd_m)))
        c0 = max(0, int((col_min - g.col_offset_m) // g.gsd_m))
        c1 = min(g.samples, int(np.ceil((col_max - g.col_offset_m) / g.gsd_m)))
        regions[sensor] = PixelRegion(sensor=sensor, row_start=r0, row_end=r1, col_start=c0, col_end=c1)

    # Footprint-intersection overlap is CONFIRMED when the geometry is
    # documented and precise; TEST_FIXTURE geometry is labelled synthetic in
    # every artifact down the line.
    status = "CONFIRMED_OVERLAP"
    reason = (
        f"Common ground envelope from documented footprint intersection "
        f"({envelope.width_m:.1f} m x {envelope.height_m:.1f} m)."
    )
    if plan.source == "TEST_FIXTURE":
        reason += " Geometry source: TEST_FIXTURE (synthetic, software validation only)."

    return OverlapResult(status=status, envelope=envelope, regions=regions, source=plan.source, reason=reason)


def blocked_overlap(code: str, reason: str) -> OverlapResult:
    return OverlapResult(status="BLOCKED", envelope=None, regions={}, source="", reason=reason, blocked_code=code)