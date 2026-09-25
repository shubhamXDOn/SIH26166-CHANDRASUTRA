"""Pair registry, provenance and validation domain (M1).

Defines the PairRecord schema, the canonical metadata records
(``data/metadata/pairs.json`` + ``pairs.csv``), deterministic Pair ID
allocation (CS-P001, ...) and the pair validation service.

Raw files are sacred: this module never writes to ``data/raw``. Registration
only *records* already-present raw files and their hashes.
"""

from __future__ import annotations

import csv
import datetime
import re
from pathlib import Path

from pydantic import BaseModel, Field

from .config import Settings, m1_config
from .loader import (
    SOURCE_REAL_PRADAN,
    SOURCE_TEST_FIXTURE,
    UNKNOWN,
    ProductInfo,
    classify_product_source,
    load_product,
    sha256_of,
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

OVERLAP_STATUSES = ("CONFIRMED_OVERLAP", "OVERLAP_UNCONFIRMED", "NO_OVERLAP", "UNKNOWN")
VALID_PAIR_ID_RE = re.compile(r"^CS-P\d{3,}$")
ALLOWED_RAW_DIRS = ["raw/ohrc", "raw/tmc2", "raw/iirs", "raw/lroc"]
METADATA_CSV_FIELDS = [
    "pair_id",
    "image_a_filename", "image_a_product_id", "image_b_filename", "image_b_product_id",
    "sensor_a", "sensor_b",
    "source_archive", "source_url",
    "product_type_a", "product_type_b",
    "processing_level_a", "processing_level_b",
    "image_a_width", "image_a_height", "image_b_width", "image_b_height",
    "dtype_a", "dtype_b",
    "nominal_gsd_a", "nominal_gsd_b",
    "acquisition_datetime_a", "acquisition_datetime_b",
    "overlap_status", "overlap_evidence",
    "raw_file_hash_a", "raw_file_hash_b",
    "ingestion_status", "validation_status",
    "registered_at_utc", "last_validated_utc",
    "matcher", "inliers", "inlier_ratio", "rmse", "final_status", "failure_reason",
    "source_class_a", "source_class_b", "data_source_gate",
]

# Core fields that count towards "metadata completeness" (honest: UNKNOWN is
# not complete).
COMPLETENESS_FIELDS = [
    "image_a_filename", "image_a_product_id", "image_b_filename", "image_b_product_id",
    "sensor_a", "sensor_b", "source_archive",
    "product_type_a", "product_type_b",
    "processing_level_a", "processing_level_b",
    "image_a_width", "image_a_height", "image_b_width", "image_b_height",
    "dtype_a", "dtype_b",
    "acquisition_datetime_a", "acquisition_datetime_b",
    "overlap_status",
    "raw_file_hash_a", "raw_file_hash_b",
]


class PairRecord(BaseModel):
    """Full, versioned pair metadata record (CSV columns stay a subset)."""

    # --- identity / provenance --------------------------------------------
    pair_id: str
    image_a_filename: str
    image_a_rel_path: str = UNKNOWN
    image_a_product_id: str = UNKNOWN
    image_b_filename: str
    image_b_rel_path: str = UNKNOWN
    image_b_product_id: str = UNKNOWN
    sensor_a: str = UNKNOWN
    sensor_b: str = UNKNOWN
    source_archive: str = "ISRO / ISSDC PRADAN — Chandrayaan-2"
    source_url: str = "https://pradan.issdc.gov.in/ch2/"
    source_access_note: str = ""

    # --- product type / processing ----------------------------------------
    product_type_a: str = UNKNOWN
    product_type_b: str = UNKNOWN
    processing_level_a: str = UNKNOWN
    processing_level_b: str = UNKNOWN

    # --- geometry ----------------------------------------------------------
    image_a_width: int | str = UNKNOWN
    image_a_height: int | str = UNKNOWN
    image_b_width: int | str = UNKNOWN
    image_b_height: int | str = UNKNOWN
    dtype_a: str = UNKNOWN
    dtype_b: str = UNKNOWN
    nominal_gsd_a: str = UNKNOWN
    nominal_gsd_b: str = UNKNOWN

    # --- acquisition -------------------------------------------------------
    acquisition_datetime_a: str = UNKNOWN
    acquisition_datetime_b: str = UNKNOWN
    footprint_a: str = UNKNOWN
    footprint_b: str = UNKNOWN
    illumination_info: str = UNKNOWN
    viewing_geometry_info: str = UNKNOWN

    # --- overlap -----------------------------------------------------------
    overlap_status: str = UNKNOWN
    overlap_evidence: str = ""
    crop_coordinates: dict | None = None

    # --- integrity ---------------------------------------------------------
    raw_file_hash_a: str = ""
    raw_file_hash_b: str = ""
    raw_size_a: int | None = None
    raw_size_b: int | None = None
    label_a_filename: str | None = None
    label_b_filename: str | None = None

    # --- governance --------------------------------------------------------
    data_use_notes: str = (
        "For scientific demonstration only. Products remain property of "
        "their original owners (ISRO). No redistribution."
    )
    attribution_notes: str = (
        "Chandrayaan-2 OHRC / TMC-2 products, ISRO / ISSDC PRADAN archive."
    )
    notes: str = ""

    # --- lifecycle ---------------------------------------------------------
    ingestion_status: str = "REGISTERED"
    validation_status: str = "UNVALIDATED"
    registered_at_utc: str = Field(default_factory=lambda: _now_utc())
    last_validated_utc: str = ""

    # --- data-source governance (real-data activation, M1 PATH A) -----------
    # source_class: REAL_PRADAN | TEST_FIXTURE | UNKNOWN for each side.
    # data_source_gate: PATH_A_REAL_DATA | PATH_B_SYNTHETIC_ONLY | PATH_UNKNOWN.
    source_class_a: str = UNKNOWN
    source_class_b: str = UNKNOWN
    data_source_gate: str = "PATH_UNKNOWN"

    # --- future scientific-result fields (NOT_RUN until measured) ----------
    preprocessing_config_id: str | None = None
    matcher: str | None = None
    model_checkpoint: str | None = None
    hardware: str | None = None
    candidate_matches: int | None = None
    inliers: int | None = None
    inlier_ratio: float | None = None
    rmse: float | None = None
    spatial_coverage: str | None = None
    runtime: str | None = None
    final_status: str = "NOT_RUN"
    failure_reason: str | None = None


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class PairRegistry:
    """Read/write the canonical pair records on disk (json + csv)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.metadata_dir = settings.data_root_path / "metadata"
        self.json_path = self.metadata_dir / "pairs.json"
        self.csv_path = self.metadata_dir / "pairs.csv"
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    # -- read ----------------------------------------------------------------
    def list(self) -> list[PairRecord]:
        if not self.json_path.is_file():
            return []
        try:
            import json

            data = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        pairs = data.get("pairs", data if isinstance(data, list) else [])
        records: list[PairRecord] = []
        for raw in pairs:
            try:
                records.append(PairRecord.model_validate(raw))
            except Exception:  # noqa: BLE001 - skip corrupt records, log separately
                continue
        return records

    def get(self, pair_id: str) -> PairRecord | None:
        for rec in self.list():
            if rec.pair_id == pair_id:
                return rec
        return None

    def next_pair_id(self) -> str:
        used = []
        for rec in self.list():
            m = VALID_PAIR_ID_RE.match(rec.pair_id)
            if m:
                used.append(int(rec.pair_id.split("-P")[1]))
        n = max(used, default=0) + 1
        return f"CS-P{n:03d}"

    def validate_pair_id(self, pair_id: str) -> str | None:
        if not VALID_PAIR_ID_RE.match(pair_id):
            return "Pair ID must follow the deterministic format CS-P001."
        if self.get(pair_id) is not None:
            return f"Pair ID {pair_id} already registered."
        return None

    # -- write ---------------------------------------------------------------
    def save(self, record: PairRecord) -> PairRecord:
        records = self.list()
        existing = [r for r in records if r.pair_id != record.pair_id]
        existing.append(record)
        existing.sort(key=lambda r: r.pair_id)
        self._write_json(existing)
        self._write_csv(existing)
        return record

    def _write_json(self, records: list[PairRecord]) -> None:
        import json

        payload = {
            "schema_version": 1,
            "note": "CHANDRASUTRA pair metadata. Future scientific fields "
                    "remain null/NOT_RUN until measured — see per-record.",
            "pairs": [r.model_dump() for r in records],
        }
        tmp = self.json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.json_path)

    def _write_csv(self, records: list[PairRecord]) -> None:
        tmp = self.csv_path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=METADATA_CSV_FIELDS)
            writer.writeheader()
            for r in records:
                writer.writerow({k: _csv_cell(getattr(r, k, UNKNOWN)) for k in METADATA_CSV_FIELDS})
        tmp.replace(self.csv_path)


def _csv_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


# --------------------------------------------------------------------------
# Data-source governance helpers (real-data activation, M1 PATH A)
# --------------------------------------------------------------------------

def data_gate(source_a: str, source_b: str) -> str:
    """Resolve the data-source gate for a pair.

    PATH_A_REAL_DATA: both sides are genuine PRADAN products (benchmark track).
    PATH_B_SYNTHETIC_ONLY: at least one side is an engineering fixture.
    PATH_UNKNOWN: cannot be classified.
    """
    if source_a == SOURCE_REAL_PRADAN and source_b == SOURCE_REAL_PRADAN:
        return "PATH_A_REAL_DATA"
    if SOURCE_TEST_FIXTURE in (source_a, source_b):
        return "PATH_B_SYNTHETIC_ONLY"
    return "PATH_UNKNOWN"


def overlap_from_footprints(prod_a: ProductInfo, prod_b: ProductInfo) -> tuple[str, str]:
    """Determine overlap from structural footprint evidence (bbox interiors).

    Thin wrapper over :func:`structural_overlap` that keeps the historical
    ``(status, evidence)`` contract used by registration. CONFIRMED_OVERLAP
    only when both labels carry a complete lat/lon footprint whose interiors
    intersect. Missing/incomplete evidence is OVERLAP_UNCONFIRMED — never
    guessed.
    """
    result = structural_overlap(prod_a, prod_b)
    return result["status"], result["evidence"]


_BBOX_KEYS = ("min_latitude", "max_latitude", "min_longitude", "max_longitude")


def structural_overlap(prod_a: ProductInfo, prod_b: ProductInfo) -> dict:
    """Derive a documented, method-tagged overlap verdict from footprint evidence.

    Method priority (M2):
        1. ``polygon_intersection`` — when both labels carry a Footprint
           polygon that is consistent with its own label bounding box and the
           clipped intersection has positive area (geographic deg^2).
        2. ``bbox_intersection`` — bounding-box interiors overlap
           (longitude-wrap aware).
    Anything else is OVERLAP_UNCONFIRMED with an explicit reason. The method
    and reason are first-class outputs; no overlap is ever invented.
    """
    fa = (prod_a.extra or {}).get("footprint_struct") if prod_a.status == "OK" else None
    fb = (prod_b.extra or {}).get("footprint_struct") if prod_b.status == "OK" else None
    ba = (fa or {}).get("bbox") if isinstance(fa, dict) else None
    bb = (fb or {}).get("bbox") if isinstance(fb, dict) else None

    result = {
        "status": "OVERLAP_UNCONFIRMED",
        "method": "none",
        "evidence": "footprint_evidence_missing_on_one_side",
        "reason": "One or both products carry no geographic footprint evidence.",
        "warnings": [],
        "intersection": None,
    }
    if not ba or not bb:
        return {**result, "evidence": "footprint_evidence_missing_on_one_side"}
    if not all(ba.get(k) is not None for k in _BBOX_KEYS) or not all(bb.get(k) is not None for k in _BBOX_KEYS):
        return {**result, "evidence": "footprint_bbox_incomplete"}

    # --- polygon path (only when trustworthy) --------------------------------
    pa = (fa or {}).get("polygon") if isinstance(fa, dict) else None
    pb = (fb or {}).get("polygon") if isinstance(fb, dict) else None
    poly = _polygon_overlap(pa, pb, ba, bb)
    if poly is not None:
        result.update(poly)
        return result

    # --- bounding-box path (longitude-window aware) --------------------------
    min_lat = max(ba["min_latitude"], bb["min_latitude"])
    max_lat = min(ba["max_latitude"], bb["max_latitude"])
    a0, a1 = float(ba["min_longitude"]), float(ba["max_longitude"])
    b0, b1 = float(bb["min_longitude"]), float(bb["max_longitude"])
    if a1 < a0:  # west>east => box crosses the 0/360 boundary
        a1 += 360.0
    if b1 < b0:
        b1 += 360.0
    direct = _lon_window_intersection(a0, a1, b0, b1, allow_shifts=False)
    window = _lon_window_intersection(a0, a1, b0, b1, allow_shifts=True)
    if max_lat <= min_lat or window is None:
        d0, d1 = direct if direct is not None else (0.0, 0.0)
        return {
            **result,
            "evidence": f"footprints_disjoint lat=[{min_lat:.4f},{max_lat:.4f}] lon=[{d0:.4f},{d1:.4f}]",
            "reason": "The documented footprints do not intersect in latitude or longitude.",
        }
    min_lon, max_lon = window
    warnings: list[str] = []
    if direct is None:
        warnings.append(
            "longitude_wraparound: the intersecting longitude window only overlaps after unwrapping by +/-360 deg."
        )
    return {
        "status": "CONFIRMED_OVERLAP",
        "method": "bbox_intersection",
        "evidence": (
            f"footprint_bbox_intersection lat=[{min_lat:.4f},{max_lat:.4f}] "
            f"lon=[{min_lon:.4f},{max_lon:.4f}]"
        ),
        "reason": "Both labels document overlapping bounding boxes.",
        "warnings": warnings,
        "intersection": {
            "lat": [round(min_lat, 4), round(max_lat, 4)],
            "lon": [round(min_lon, 4), round(max_lon, 4)],
        },
    }


def _lon_window_intersection(a0: float, a1: float, b0: float, b1: float, *, allow_shifts: bool) -> tuple[float, float] | None:
    """Largest positive longitude intersection across candidate +/-360 shifts.

    ``allow_shifts=False`` returns the unshifted (nominal) intersection so the
    caller can detect true wraparound cases.
    """
    shifts = (0.0, -360.0, 360.0) if allow_shifts else (0.0,)
    best: tuple[float, float] | None = None
    for sa in shifts:
        for sb in shifts:
            lo = max(a0 + sa, b0 + sb)
            hi = min(a1 + sa, b1 + sb)
            if hi - lo > 1e-9 and (best is None or (hi - lo) > (best[1] - best[0])):
                best = (lo, hi)
    return best


def _dedupe_vertices(vertices: list[list[float]]) -> list[list[float]]:
    seen: set[tuple[float, float]] = set()
    out: list[list[float]] = []
    for lat, lon in vertices:
        key = (round(float(lat), 6), round(float(lon), 6))
        if key in seen:
            continue
        seen.add(key)
        out.append([float(lat), float(lon)])
    return out


def _polygon_bbox(vertices: list[list[float]]) -> dict:
    lats = [v[0] for v in vertices]
    lons = [v[1] for v in vertices]
    return {
        "min_latitude": min(lats),
        "max_latitude": max(lats),
        "min_longitude": min(lons),
        "max_longitude": max(lons),
    }


def _bbox_within_tolerance(poly_bbox: dict, label_bbox: dict) -> bool:
    """A documented footprint polygon must match the label bounding box.

    Prevents a stray/extraneous vertex (e.g. a degenerate 0,0 entry) from
    silently corrupting the intersection result; on mismatch the caller falls
    back to the honest bounding-box method.
    """
    for axis_min, axis_max in (
        ("min_latitude", "max_latitude"),
        ("min_longitude", "max_longitude"),
    ):
        if poly_bbox[axis_min] is None or poly_bbox[axis_max] is None:
            return False
        span = abs(label_bbox[axis_max] - label_bbox[axis_min])
        tol = max(1.0, span * 0.2)
        if poly_bbox[axis_min] < label_bbox[axis_min] - tol:
            return False
        if poly_bbox[axis_max] > label_bbox[axis_max] + tol:
            return False
    return True


def _unwrap_longitudes(pts: list[list[float]], ref_lon: float) -> list[list[float]]:
    """Shift longitudes by +/-360 so a footprint stays contiguous near ref_lon."""
    out: list[list[float]] = []
    for lat, lon in pts:
        lon2 = float(lon)
        while lon2 - ref_lon > 180.0:
            lon2 -= 360.0
        while lon2 - ref_lon < -180.0:
            lon2 += 360.0
        out.append([float(lat), lon2])
    return out


def _polygon_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _clip_polygon(subject: list[tuple[float, float]], clip: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sutherland–Hodgman polygon clipping (convex clip polygon assumed)."""
    output = list(subject)
    clip = list(clip)
    clip_len = len(clip)
    if clip_len < 3 or len(output) < 3:
        return []

    def signed_area(pts):
        return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) / 2.0

    if signed_area(clip) < 0.0:
        clip = clip[::-1]  # normalize to counter-clockwise so `inside` holds

    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0.0

    def intersect(p1, p2, a, b):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = a
        x4, y4 = b
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(denom) < 1e-12:
            return p2
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    for i in range(clip_len):
        a = clip[i]
        b = clip[(i + 1) % clip_len]
        input_list, output = list(output), []
        if not input_list:
            break
        s = input_list[-1]
        for e in input_list:
            if inside(e, a, b):
                if not inside(s, a, b):
                    output.append(intersect(s, e, a, b))
                output.append(e)
            elif inside(s, a, b):
                output.append(intersect(s, e, a, b))
            s = e
    return output


def _polygon_overlap(pa: list | None, pb: list | None, ba: dict, bb: dict) -> dict | None:
    """Return a CONFIRMED polygon result, or None to fall back to the bbox path.

    Only trustworthy polygons are used: >=3 unique vertices each, bounded size,
    and a bounding box consistent with the label's bounding box.
    """
    if not isinstance(pa, list) or not isinstance(pb, list) or len(pa) < 3 or len(pb) < 3:
        return None
    if len(pa) > 600 or len(pb) > 600:
        return None
    poly_a = _dedupe_vertices(pa)
    poly_b = _dedupe_vertices(pb)
    if len(poly_a) < 3 or len(poly_b) < 3:
        return None
    if not (_bbox_within_tolerance(_polygon_bbox(poly_a), ba) and _bbox_within_tolerance(_polygon_bbox(poly_b), bb)):
        return None
    ref_lon = (
        (ba["min_longitude"] + ba["max_longitude"]) + (bb["min_longitude"] + bb["max_longitude"])
    ) / 4.0
    a_pts = [(lat, lon) for lat, lon in _unwrap_longitudes(poly_a, ref_lon)]
    b_pts = [(lat, lon) for lat, lon in _unwrap_longitudes(poly_b, ref_lon)]
    clipped = _clip_polygon(list(a_pts), list(b_pts))
    area = _polygon_area(clipped)
    if area <= 1e-6:
        return None  # polygons disjoint -> the caller decides honestly
    return {
        "status": "CONFIRMED_OVERLAP",
        "method": "polygon_intersection",
        "evidence": f"footprint_polygon_intersection area=[{area:.6f}] degrees2 vertices={len(clipped)}",
        "reason": "Both labels document footprint polygons that intersect.",
        "warnings": [
            "Polygon intersection computed in lat/lon degrees (geographic approximation); no map projection claimed."
        ],
        "intersection": {"polygon_vertices_n": len(clipped), "area_deg2": round(area, 6)},
    }


DEFAULT_RAW_LEVEL_RANK = {"c": 0, "d": 1, "r": 2, "UNKNOWN": 3}


def _level_rank(e: dict) -> int:
    level = str(e.get("processing_level") or UNKNOWN).split(" ")[0].lower()[:1]
    return DEFAULT_RAW_LEVEL_RANK.get(level, DEFAULT_RAW_LEVEL_RANK["UNKNOWN"])


def scan_raw_products(settings: Settings) -> list[dict]:
    """Scan configured data/raw locations for ingestible products (read-only).

    Returns a public, path-relativised inventory with source classification,
    footprint summary and load status. Never writes; never reports abs paths.
    """
    root = settings.data_root_path.resolve()
    raw_root = root / "raw"
    if not raw_root.is_dir():
        return []
    allowed = m1_config().get("allowed_raw_locations", ALLOWED_RAW_DIRS)
    skipped_exts = {".xml", ".xml.bak", ".trk", ".readme", ".md", ".csv", ".json", ".nfo", ".txt"}
    entries: list[dict] = []
    for loc in allowed:
        base = root / loc
        if not base.is_dir():
            continue
        sensor_dir = Path(loc).name
        for image_path in sorted(base.iterdir()):
            if not image_path.is_file() or image_path.name.startswith("."):
                continue
            ext = image_path.suffix.lower()
            if ext in skipped_exts:
                continue
            label_path = image_path.with_suffix(".xml")
            label = label_path if label_path.is_file() else None
            info = load_product(image_path, label)
            entries.append({
                "rel_path": str(image_path.relative_to(root)).replace("\\", "/"),
                "filename": image_path.name,
                "size_bytes": info.size_bytes,
                "product_id": info.product_id,
                "instrument": info.instrument if info.instrument != UNKNOWN else sensor_dir,
                "processing_level": info.processing_level,
                "source_class": info.source_class,
                "status": info.status,
                "error": (info.error or {}).get("message", "") if info.status != "OK" else None,
                "footprint": info.footprint,
                "label_filename": info.label_filename,
            })
    return entries


def select_real_pair(settings: Settings) -> tuple[dict | None, dict | None]:
    """Pick the first genuine OHRC and first genuine TMC-2 product (C > D > R)."""
    real = [e for e in scan_raw_products(settings) if e["source_class"] == SOURCE_REAL_PRADAN]
    by_instrument: dict[str, list[dict]] = {}
    for entry in real:
        by_instrument.setdefault(str(entry.get("instrument") or UNKNOWN), []).append(entry)

    def pick(sensor: str) -> dict | None:
        candidates = sorted(by_instrument.get(sensor, []), key=_level_rank)
        return candidates[0] if candidates else None

    return pick("ohrc"), pick("tmc2")


def register_real_pair(
    settings: Settings,
    *,
    image_a_rel: str,
    image_b_rel: str,
    notes: str = "",
    source_url: str = "https://pradan.issdc.gov.in/ch2/",
) -> PairRecord:
    """Register ONE genuine PRADAN pair (image_a + image_b) with footprint overlap.

    Only REAL_PRADAN products may enter through this path; anything else
    raises ValueError with the honest classification. Idempotent: re-running
    with the same raw files updates the existing pair record instead of
    duplicating it. Raw files are never modified or moved.
    """
    pa = resolve_raw_path(settings, "image_a", UNKNOWN, image_a_rel)
    pb = resolve_raw_path(settings, "image_b", UNKNOWN, image_b_rel)
    for side, path in (("image_a", pa), ("image_b", pb)):
        if not path.is_file():
            raise ValueError(f"{side} file missing: {path.name}")
    product_a = load_product(pa, pa.with_suffix(".xml") if pa.with_suffix(".xml").is_file() else None)
    product_b = load_product(pb, pb.with_suffix(".xml") if pb.with_suffix(".xml").is_file() else None)
    for side, prod in (("image_a", product_a), ("image_b", product_b)):
        if prod.status != "OK":
            raise ValueError(f"{side} could not be loaded: {(prod.error or {}).get('message', prod.error)}")
        if prod.source_class != SOURCE_REAL_PRADAN:
            raise ValueError(
                f"{side} is not a genuine PRADAN product (source_class={prod.source_class}). "
                "Only REAL_PRADAN products may be registered for the real-data run."
            )

    overlap_status, overlap_evidence = overlap_from_footprints(product_a, product_b)
    registry = PairRegistry(settings)
    pair_id: str | None = None
    for rec in registry.list():
        same_files = (
            rec.image_a_rel_path == image_a_rel and rec.image_b_rel_path == image_b_rel
        )
        if same_files or (
            rec.image_a_filename == product_a.filename and rec.image_b_filename == product_b.filename
        ):
            pair_id = rec.pair_id
            break
    if pair_id is None:
        pair_id = registry.next_pair_id()

    record = build_record_from_products(
        pair_id,
        product_a,
        product_b,
        rel_a=image_a_rel,
        rel_b=image_b_rel,
        overlap_status=overlap_status,
        overlap_evidence=overlap_evidence,
        notes=notes,
        source_url=source_url,
    )
    return registry.save(record)


# --------------------------------------------------------------------------
# Registration support
# --------------------------------------------------------------------------

ALLOWED_RAW_IDS = ("ohrc", "tmc2", "iirs", "lroc")


def resolve_raw_path(settings: Settings, side: str, sensor_id: str | None, filename: str) -> Path:
    """Resolve a raw product path safely (inside data root, raw dir only)."""
    root = settings.data_root_path.resolve()
    rel = Path(filename)
    if rel.is_absolute():
        raise ValueError(f"{side} file must be relative to the data root, got absolute path.")
    parts = rel.parts
    if len(parts) < 2 or parts[0] != "raw":
        raise ValueError(f"{side} file must live under data/raw/, got: {filename!r}")
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"{side} file escapes the data root: {filename!r}")
    raw_root = (root / "raw").resolve()
    if not target.is_relative_to(raw_root):
        raise ValueError(f"{side} file must live under data/raw/: {filename!r}")
    allowed = m1_config().get("allowed_raw_locations", ALLOWED_RAW_DIRS)
    parent_rel = target.parent.relative_to(root)
    if str(parent_rel).replace("\\", "/") not in allowed:
        raise ValueError(
            f"{side} file must live inside one of the configured raw locations: {allowed} — got {parent_rel}"
        )
    return target


def infer_sensor_paths(settings: Settings, sensor_a: str, sensor_b: str, filename_a: str, filename_b: str) -> tuple[Path, Path]:
    """Place files under their documented sensor sub-directory if not already there."""
    pa = resolve_raw_path(settings, "image_a", sensor_a, filename_a)
    pb = resolve_raw_path(settings, "image_b", sensor_b, filename_b)
    return pa, pb


def infer_sensor_id_from_path(settings: Settings, rel: str) -> str:
    """Return the sensor id when the path already sits in a sensor dir."""
    norm = rel.replace("\\", "/")
    for loc in m1_config().get("allowed_raw_locations", ALLOWED_RAW_DIRS):
        if norm.startswith(loc + "/"):
            return Path(loc).name
    return UNKNOWN


def _default_rel(sensor: str, filename: str) -> str:
    if sensor not in ("", UNKNOWN) and filename not in ("", UNKNOWN):
        sensor_rel = {"ohrc": "raw/ohrc", "tmc2": "raw/tmc2", "iirs": "raw/iirs", "lroc": "raw/lroc"}.get(
            sensor, f"raw/{sensor}"
        )
        return f"{sensor_rel}/{filename}"
    return UNKNOWN


def build_record_from_products(
    pair_id: str,
    prod_a: ProductInfo,
    prod_b: ProductInfo,
    *,
    rel_a: str = UNKNOWN,
    rel_b: str = UNKNOWN,
    sensor_a: str = UNKNOWN,
    sensor_b: str = UNKNOWN,
    overlap_status: str = UNKNOWN,
    overlap_evidence: str = "",
    illumination_info: str = UNKNOWN,
    viewing_geometry_info: str = UNKNOWN,
    data_use_notes: str = "",
    attribution_notes: str = "",
    notes: str = "",
    source_url: str = "https://pradan.issdc.gov.in/ch2/",
) -> PairRecord:
    """Compose a PairRecord from the two loaded products (no fake values)."""
    gsd_a = prod_a.gsd if prod_a.status == "OK" else UNKNOWN
    gsd_b = prod_b.gsd if prod_b.status == "OK" else UNKNOWN
    sensor_a = sensor_a if sensor_a not in ("", UNKNOWN) else prod_a.instrument
    sensor_b = sensor_b if sensor_b not in ("", UNKNOWN) else prod_b.instrument
    rel_a = rel_a if rel_a not in ("", UNKNOWN) else _default_rel(sensor_a, prod_a.filename)
    rel_b = rel_b if rel_b not in ("", UNKNOWN) else _default_rel(sensor_b, prod_b.filename)
    source_class_a = prod_a.source_class if prod_a.status == "OK" else UNKNOWN
    source_class_b = prod_b.source_class if prod_b.status == "OK" else UNKNOWN
    return PairRecord(
        pair_id=pair_id,
        image_a_filename=prod_a.filename,
        image_a_rel_path=rel_a,
        image_a_product_id=prod_a.product_id,
        image_b_filename=prod_b.filename,
        image_b_rel_path=rel_b,
        image_b_product_id=prod_b.product_id,
        sensor_a=sensor_a,
        sensor_b=sensor_b,
        source_archive="ISRO / ISSDC PRADAN — Chandrayaan-2",
        source_url=source_url,
        product_type_a=prod_a.product_type,
        product_type_b=prod_b.product_type,
        processing_level_a=prod_a.processing_level,
        processing_level_b=prod_b.processing_level,
        image_a_width=prod_a.width,
        image_a_height=prod_a.height,
        image_b_width=prod_b.width,
        image_b_height=prod_b.height,
        dtype_a=prod_a.dtype,
        dtype_b=prod_b.dtype,
        nominal_gsd_a=gsd_a,
        nominal_gsd_b=gsd_b,
        acquisition_datetime_a=prod_a.acquisition_datetime,
        acquisition_datetime_b=prod_b.acquisition_datetime,
        footprint_a=prod_a.footprint,
        footprint_b=prod_b.footprint,
        illumination_info=illumination_info if illumination_info not in ("", UNKNOWN) else prod_a.illumination_info,
        viewing_geometry_info=viewing_geometry_info,
        overlap_status=overlap_status if overlap_status in OVERLAP_STATUSES else UNKNOWN,
        overlap_evidence=overlap_evidence,
        raw_file_hash_a=prod_a.raw_sha256,
        raw_file_hash_b=prod_b.raw_sha256,
        raw_size_a=prod_a.size_bytes,
        raw_size_b=prod_b.size_bytes,
        label_a_filename=prod_a.label_filename,
        label_b_filename=prod_b.label_filename,
        data_use_notes=data_use_notes or PairRecord.model_fields["data_use_notes"].default,
        attribution_notes=attribution_notes or PairRecord.model_fields["attribution_notes"].default,
        notes=notes,
        source_class_a=source_class_a,
        source_class_b=source_class_b,
        data_source_gate=data_gate(source_class_a, source_class_b),
    )


# --------------------------------------------------------------------------
# Validation service
# --------------------------------------------------------------------------

def _none_or_unknown(value) -> bool:
    return value in (None, "", UNKNOWN, [], {})


def _rel_or_filename(rel: str, filename: str) -> str:
    if rel and rel not in ("", UNKNOWN):
        return rel
    return filename


def metadata_completeness(record: PairRecord) -> dict:
    present = 0
    missing: list[str] = []
    for field in COMPLETENESS_FIELDS:
        if _none_or_unknown(getattr(record, field, None)):
            missing.append(field)
        else:
            present += 1
    ratio = present / len(COMPLETENESS_FIELDS) if COMPLETENESS_FIELDS else 0.0
    level = "COMPLETE_ENOUGH" if ratio >= 0.75 else ("PARTIAL" if ratio >= 0.5 else "INCOMPLETE")
    return {"fraction": round(ratio, 3), "present": present, "total": len(COMPLETENESS_FIELDS), "level": level, "missing": missing}


def validate_record(record: PairRecord, settings: Settings) -> dict:
    """Run the M1 pair validation: files, labels, hashes, readability, schema."""
    checks: list[dict] = []
    failures: list[dict] = []

    def check(name: str, passed: bool, detail: str = ""):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})
        if not passed:
            failures.append({"check": name, "detail": detail})

    # --- file existence -----------------------------------------------------
    path_a, path_b = None, None
    try:
        path_a = resolve_raw_path(settings, "image_a", record.sensor_a,
                                  _rel_or_filename(record.image_a_rel_path, record.image_a_filename))
    except ValueError as exc:
        check("image_a_path", False, str(exc))
    try:
        path_b = resolve_raw_path(settings, "image_b", record.sensor_b,
                                  _rel_or_filename(record.image_b_rel_path, record.image_b_filename))
    except ValueError as exc:
        check("image_b_path", False, str(exc))

    check("image_a_exists", bool(path_a and path_a.is_file()), f"{record.image_a_filename}" if path_a else "")
    check("image_b_exists", bool(path_b and path_b.is_file()), f"{record.image_b_filename}" if path_b else "")

    label_a = label_b = None
    if record.label_a_filename and path_a:
        label_a = path_a.parent / record.label_a_filename
        check("label_a_exists", label_a.is_file(), f"{record.label_a_filename}")
    else:
        check("label_a_exists", False, "no label recorded")
    if record.label_b_filename and path_b:
        label_b = path_b.parent / record.label_b_filename
        check("label_b_exists", label_b.is_file(), f"{record.label_b_filename}")
    else:
        check("label_b_exists", False, "no label recorded")

    # --- readability + dims/dtype correspondence ----------------------------
    prod_a = prod_b = None
    if path_a and path_a.is_file():
        prod_a = load_product(path_a, label_a if label_a and label_a.is_file() else None)
        check("image_a_readable", prod_a.status == "OK", prod_a.error.get("message", "") if prod_a.error else "")
    if path_b and path_b.is_file():
        prod_b = load_product(path_b, label_b if label_b and label_b.is_file() else None)
        check("image_b_readable", prod_b.status == "OK", prod_b.error.get("message", "") if prod_b.error else "")

    if prod_a and prod_a.status == "OK":
        check("image_a_dims_match", prod_a.width == record.image_a_width and prod_a.height == record.image_a_height,
              f"{prod_a.width}x{prod_a.height}")
    if prod_b and prod_b.status == "OK":
        check("image_b_dims_match", prod_b.width == record.image_b_width and prod_b.height == record.image_b_height,
              f"{prod_b.width}x{prod_b.height}")

    # --- raw integrity (hash re-verification) --------------------------------
    hash_ok_a = hash_ok_b = False
    if path_a and path_a.is_file() and record.raw_file_hash_a:
        hash_ok_a = sha256_of(path_a) == record.raw_file_hash_a
    check("raw_hash_a", hash_ok_a, "recomputed vs recorded" if path_a else "missing file")
    if path_b and path_b.is_file() and record.raw_file_hash_b:
        hash_ok_b = sha256_of(path_b) == record.raw_file_hash_b
    check("raw_hash_b", hash_ok_b, "recomputed vs recorded" if path_b else "missing file")

    # --- metadata / overlap ------------------------------------------------
    check("overlap_status_recorded", record.overlap_status in OVERLAP_STATUSES, record.overlap_status)
    evidence_required = record.overlap_status in ("CONFIRMED_OVERLAP", "OVERLAP_UNCONFIRMED")
    has_evidence = bool(record.overlap_evidence.strip())
    check("overlap_evidence_present", (not evidence_required) or has_evidence, "evidence needed when a positive overlap is claimed")
    check("pair_id_format", bool(VALID_PAIR_ID_RE.match(record.pair_id)), record.pair_id)

    completeness = metadata_completeness(record)
    check("metadata_complete_enough", completeness["level"] in ("COMPLETE_ENOUGH", "PARTIAL"),
          f"fraction={completeness['fraction']}")

    check("data_source_gate", record.data_source_gate in ("PATH_A_REAL_DATA", "PATH_B_SYNTHETIC_ONLY", "PATH_UNKNOWN"),
          record.data_source_gate)

    structural_ok = not failures and prod_a is not None and prod_b is not None
    status = "VALID" if structural_ok else "INVALID"
    benchmark_ready = record.overlap_status == "CONFIRMED_OVERLAP" and has_evidence
    raw_integrity = "VERIFIED" if (hash_ok_a and hash_ok_b) else ("PARTIAL" if (hash_ok_a or hash_ok_b) else "FAILED")

    return {
        "pair_id": record.pair_id,
        "timestamp": _now_utc(),
        "status": status,
        "raw_integrity": raw_integrity,
        "metadata": completeness,
        "overlap": {
            "status": record.overlap_status,
            "evidence": record.overlap_evidence,
            "benchmark_ready": benchmark_ready,
        },
        "checks": checks,
        "failures": failures,
        "scientific_matching": "NOT_RUN",
        "image_a": product_summary(prod_a),
        "image_b": product_summary(prod_b),
    }


def product_summary(prod: ProductInfo | None) -> dict:
    if prod is None:
        return {"status": "MISSING"}
    return {
        "filename": prod.filename,
        "product_id": prod.product_id,
        "instrument": prod.instrument,
        "status": prod.status,
        "width": prod.width,
        "height": prod.height,
        "dtype": prod.dtype,
        "gsd": prod.gsd,
        "acquisition_datetime": prod.acquisition_datetime,
        "label_filename": prod.label_filename,
        "source_class": prod.source_class,
        "footprint": prod.footprint,
    }


def write_validation_record(payload: dict, settings: Settings) -> Path:
    import json

    target = settings.data_root_path / "metadata" / "pair_validation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def apply_validation(record: PairRecord, settings: Settings) -> PairRecord:
    """Validate, persist the machine-readable validation record, update lifecycle."""
    result = validate_record(record, settings)
    write_validation_record(result, settings)
    record.validation_status = result["status"]
    record.last_validated_utc = result["timestamp"]
    PairRegistry(settings).save(record)
    return record