"""Ground geometry for overlap computation (M2).

Honesty rule: the ground placement of each product comes from documented
sources only.

    * TEST_FIXTURE geometry originates from an explicit, labelled request —
      usable for software tests only; every artifact records
      ``geometry_source: TEST_FIXTURE`` and is never presented as real.
    * Real pairs in M2 carry no camera model / footprint coordinates in their
      labels, so (absent a fixture override) overlap prep BLOCKS with the
      stable code NO_GEOMETRY instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

GEOMETRY_SOURCE_REAL = "PAIR_METADATA"
GEOMETRY_SOURCE_FIXTURE = "TEST_FIXTURE"


@dataclass
class FootprintBox:
    row_min_m: float
    row_max_m: float
    col_min_m: float
    col_max_m: float

    @property
    def height_m(self) -> float:
        return max(0.0, self.row_max_m - self.row_min_m)

    @property
    def width_m(self) -> float:
        return max(0.0, self.col_max_m - self.col_min_m)

    @property
    def area_m2(self) -> float:
        return self.width_m * self.height_m

    def to_dict(self) -> dict:
        return {
            "row_min_m": round(self.row_min_m, 3),
            "row_max_m": round(self.row_max_m, 3),
            "col_min_m": round(self.col_min_m, 3),
            "col_max_m": round(self.col_max_m, 3),
            "width_m": round(self.width_m, 3),
            "height_m": round(self.height_m, 3),
            "area_m2": round(self.area_m2, 3),
        }


@dataclass
class ProductGeom:
    sensor: str
    lines: int
    samples: int
    gsd_m: float
    row_offset_m: float
    col_offset_m: float
    gsd_source: str  # TEST_FIXTURE_OVERRIDE | NOMINAL | LABEL | UNKNOWN

    @property
    def box(self) -> FootprintBox:
        return FootprintBox(
            row_min_m=self.row_offset_m,
            row_max_m=self.row_offset_m + self.lines * self.gsd_m,
            col_min_m=self.col_offset_m,
            col_max_m=self.col_offset_m + self.samples * self.gsd_m,
        )


@dataclass
class GeometryPlan:
    source: str
    reference: str
    products: dict[str, ProductGeom]

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "reference": self.reference,
            "products": {
                sensor: {
                    "sensor": g.sensor,
                    "lines": g.lines,
                    "samples": g.samples,
                    "gsd_m": g.gsd_m,
                    "gsd_source": g.gsd_source,
                    "row_offset_m": g.row_offset_m,
                    "col_offset_m": g.col_offset_m,
                    "footprint_m": g.box.to_dict(),
                }
                for sensor, g in self.products.items()
            },
        }


@dataclass
class GeometryBlock:
    code: str
    message: str
    stage: str = "PREPARING_OVERLAP"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "stage": self.stage}


def _parse_gsd(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "" or value == "UNKNOWN":
        return default
    text = str(value).split(" ")[0].strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return default


def resolve_geometry(
    record,
    product_a,
    product_b,
    request_geometry: dict | None,
) -> GeometryPlan | GeometryBlock:
    """Deterministically derive ground geometry for the pair.

    Order of precedence (documented):
        1. Explicit TEST_FIXTURE override in the PREPARE request.
        2. Documented footprint/GSD from the pair record — if present.
        3. Block with NO_GEOMETRY (never guess).

    Returns a GeometryPlan, or a GeometryBlock describing the honest blocker.
    """
    sensor_a = record.sensor_a
    sensor_b = record.sensor_b

    req = request_geometry or {}
    source = req.get("source", "")
    if source == GEOMETRY_SOURCE_FIXTURE:
        return _plan_from_fixture(req, sensor_a, product_a, sensor_b, product_b)

    # Real path: we need documented row/col offsets in a shared frame and a gsd.
    # M2 labels do not expose these (only UNKNOWN footprints), so we block.
    if source and source != GEOMETRY_SOURCE_REAL:
        return GeometryBlock(
            code="GEOMETRY_SOURCE_UNSUPPORTED",
            message=f"Geometry source '{source}' is not supported for real overlap preparation.",
        )
    return GeometryBlock(
        code="NO_GEOMETRY",
        message=(
            "The pair has no documented ground geometry (no camera model / footprint "
            "coordinates in the M2 labels) and no TEST_FIXTURE override was supplied. "
            "Overlap cannot be prepared without guessing, so this stage is blocked."
        ),
    )


def _plan_from_fixture(req: dict, sensor_a: str, product_a, sensor_b: str, product_b) -> GeometryPlan:
    products = req.get("products") or {}
    reference = (req.get("reference") or "").strip() or "Synthetic ground frame injected for software validation only — NOT real orbital geometry."

    used: dict[str, ProductGeom] = {}
    for sensor, info in ((sensor_a, product_a), (sensor_b, product_b)):
        override = products.get(sensor, {})
        gsd = override.get("gsd_m")
        gsd_source = "TEST_FIXTURE_OVERRIDE" if gsd is not None else "NOMINAL"
        if gsd is None:
            gsd = _parse_gsd(info.gsd)
        if gsd is None:
            # Honest blocker: cannot even place the synthetic footprint.
            return GeometryBlock(
                code="NO_GSD",
                message=f"Sensor '{sensor}' has no usable GSD, so its synthetic footprint cannot be placed.",
            )
        used[sensor] = ProductGeom(
            sensor=sensor,
            lines=int(info.height),
            samples=int(info.width),
            gsd_m=float(gsd),
            row_offset_m=float(override.get("row_offset_m", 0.0)),
            col_offset_m=float(override.get("col_offset_m", 0.0)),
            gsd_source=gsd_source,
        )
    return GeometryPlan(
        source=GEOMETRY_SOURCE_FIXTURE,
        reference=reference,
        products=used,
    )