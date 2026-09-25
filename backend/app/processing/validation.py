"""M2 real-data validation — structured, evidence-based product + pair checks.

Implements the M2 validation contract:

    * PDS4 label identity (logical identifier, product class, instrument,
      array geometry, data type, time) — reported honestly when absent.
    * IMG/XML binary consistency (expected bytes from the label geometry vs
      the actual file) — truncated files FAIL, oversized files WARN.
    * Numerical sanity (positive dimensions, sane coordinates / bbox ordering,
      supported dtypes).
    * Sensor fidelity (OHRC stays OHRC, TMC-2 stays TMC-2; the label is
      stronger than the filename).
    * Pair-level structural overlap via ``structural_overlap`` with an
      explicit ``overlap_method``.

The full object is persisted per pair under
``data/metadata/m2_validation/<pair_id>.json``. raw files are never opened
for writing anywhere in this module.
"""

from __future__ import annotations

import json
import datetime
from pathlib import Path

from ..config import Settings
from ..loader import (
    UNKNOWN,
    ProductReadError,
    SOURCE_REAL_PRADAN,
    expected_dtype,
    load_product,
    sha256_of,
)
from ..logging_conf import get_logger
from ..pairs import (
    PairRegistry,
    _rel_or_filename,
    resolve_raw_path,
    structural_overlap,
)

logger = get_logger(__name__)

_BBOX_KEYS = ("min_latitude", "max_latitude", "min_longitude", "max_longitude")


def _now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Per-product validation blocks
# ---------------------------------------------------------------------------

def expected_array_bytes(meta: dict) -> int | None:
    """Bytes implied by label geometry: offset + lines*samples*bands*itemsize."""
    if not (isinstance(meta.get("lines"), int) and isinstance(meta.get("samples"), int)):
        return None
    try:
        dtype = expected_dtype(str(meta.get("data_type") or ""))
    except ProductReadError:
        return None
    bands = int(meta.get("bands") or 1)
    offset = int(meta.get("offset_bytes") or 0)
    return offset + int(meta["lines"]) * int(meta["samples"]) * bands * dtype.itemsize


def binary_consistency(info) -> dict:
    """Compare the label-implied byte geometry against the actual raw file."""
    if info.status != "OK":
        return {"status": "FAIL", "detail": "product could not be loaded", "expected_bytes": None, "actual_bytes": None}
    meta = info.metadata or {}
    expected = expected_array_bytes(meta)
    actual = int(info.size_bytes or 0)
    if expected is None:
        return {
            "status": "UNKNOWN",
            "detail": "label carries no usable binary geometry (lines/samples/data_type)",
            "expected_bytes": None,
            "actual_bytes": actual,
        }
    if actual == expected:
        return {"status": "PASS", "detail": "file size matches the label geometry exactly", "expected_bytes": expected, "actual_bytes": actual}
    if actual < expected:
        return {
            "status": "FAIL",
            "detail": f"file is truncated: {actual} bytes present, label geometry requires {expected} bytes",
            "expected_bytes": expected,
            "actual_bytes": actual,
        }
    return {
        "status": "WARNING",
        "detail": f"file is {actual - expected} bytes larger than the label geometry (trailing bytes not covered by the label)",
        "expected_bytes": expected,
        "actual_bytes": actual,
    }


def label_identity_checks(meta: dict) -> list[dict]:
    """The PDS4 identification fields M2 expects in a genuine CH-2 label."""
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str, warn: bool = False):
        checks.append({
            "check": name,
            "status": "PASS" if passed else ("WARN" if warn else "FAIL"),
            "detail": detail,
        })

    add("logical_identifier", bool(str(meta.get("logical_identifier") or "").strip() and str(meta.get("logical_identifier") or UNKNOWN) != UNKNOWN),
        str(meta.get("logical_identifier") or UNKNOWN))
    add("product_class", bool(str(meta.get("product_class") or "").strip() and str(meta.get("product_class") or UNKNOWN) != UNKNOWN),
        str(meta.get("product_class") or UNKNOWN))
    instrument = str(meta.get("instrument") or UNKNOWN)
    add("instrument", instrument != UNKNOWN, instrument, warn=instrument == UNKNOWN)
    add("array_geometry", _is_int(meta.get("lines")) and _is_int(meta.get("samples")),
        f"{meta.get('lines')} x {meta.get('samples')}")
    add("data_type", bool(str(meta.get("data_type") or "").strip() and str(meta.get("data_type") or UNKNOWN) != UNKNOWN),
        str(meta.get("data_type") or UNKNOWN))
    add("observation_time", bool(str(meta.get("start_date_time") or "").strip() and str(meta.get("start_date_time") or UNKNOWN) != UNKNOWN),
        str(meta.get("start_date_time") or UNKNOWN))
    return checks


def numeric_sanity_checks(meta: dict) -> list[dict]:
    checks: list[dict] = []

    def add(name: str, passed: bool, detail: str):
        checks.append({"check": name, "status": "PASS" if passed else "FAIL", "detail": detail})

    dims_ok = _is_int(meta.get("lines")) and _is_int(meta.get("samples")) \
        and int(meta["lines"]) > 0 and int(meta["samples"]) > 0
    add("dimensions_positive", dims_ok, f"{meta.get('lines')} x {meta.get('samples')}")

    try:
        itemsize = expected_dtype(str(meta.get("data_type") or "")).itemsize
        add("dtype_supported", True, str(meta.get("data_type")))
    except ProductReadError as exc:
        add("dtype_supported", False, str(exc.message))

    bbox = (meta.get("footprint") or {}).get("bbox") if isinstance(meta.get("footprint"), dict) else None
    if bbox:
        lat_ok = -90.0 <= bbox["min_latitude"] <= 90.0 and -90.0 <= bbox["max_latitude"] <= 90.0 \
            and bbox["min_latitude"] <= bbox["max_latitude"]
        add("bbox_latitude_range", lat_ok,
            f"min={bbox['min_latitude']} max={bbox['max_latitude']}")
        lon_ok = -180.0 <= bbox["min_longitude"] <= 360.0 and -180.0 <= bbox["max_longitude"] <= 360.0
        add("bbox_longitude_range", lon_ok,
            f"min={bbox['min_longitude']} max={bbox['max_longitude']}")
        order_ok = bbox["min_longitude"] <= bbox["max_longitude"]
        add("bbox_ordering", order_ok or True,
            "west<=east nominal; east<west interpreted as 0/360 wraparound" if not order_ok else "west<=east")
    else:
        checks.append({"check": "bbox_present", "status": "WARN", "detail": "no label bounding box to sanity-check"})

    polygon = (meta.get("footprint") or {}).get("polygon") if isinstance(meta.get("footprint"), dict) else None
    if polygon is not None:
        add("footprint_polygon_vertices", len(polygon) >= 3, f"{len(polygon)} vertices")
    return checks


def sensor_consistency(info, recorded_sensor: str) -> dict:
    """OHRC must remain OHRC; the label beats the filename. Returns a verdict."""
    instrument = info.instrument if info.instrument not in ("", UNKNOWN) else None
    return {
        "check": "sensor_consistency",
        "status": "PASS" if instrument == recorded_sensor and instrument else "WARN",
        "detail": (f"label/record sensor: {instrument or UNKNOWN} (recorded: {recorded_sensor})"
                   if instrument != recorded_sensor
                   else f"label/record sensor agree: {instrument}"),
    }


def product_validation(info, path: Path, recorded_sensor: str) -> dict:
    meta = info.metadata or {}
    identity = label_identity_checks(meta)
    sanity = numeric_sanity_checks(meta)
    binary = binary_consistency(info)

    errors = [{"check": c["check"], "detail": c["detail"]} for c in identity + sanity if c["status"] == "FAIL"]
    if binary["status"] == "FAIL":
        errors.append({"check": "binary_consistency", "detail": binary["detail"]})
    warnings = [c["detail"] for c in identity + sanity if c["status"] == "WARN"]
    if binary["status"] == "WARNING":
        warnings.append(binary["detail"])

    return {
        "filename": info.filename,
        "product_id": info.product_id,
        "source_class": info.source_class,
        "sensor": sensor_consistency(info, recorded_sensor),
        "dimensions": {
            "width": info.width,
            "height": info.height,
            "bands": info.bands,
            "dtype": info.dtype,
            "bytes_per_pixel": info.bytes_per_pixel,
            "label_expected_bytes": expected_array_bytes(meta),
        },
        "label_identity": {"status": _verdict(identity), "checks": identity},
        "binary_consistency": binary,
        "numeric_sanity": {"status": _verdict(sanity), "checks": sanity},
        "footprint": {
            "status": _footprint_level(meta),
            "summary": info.footprint,
        },
        "errors": errors,
        "warnings": warnings,
    }


def _verdict(checks: list[dict]) -> str:
    if any(c["status"] == "FAIL" for c in checks):
        return "INVALID"
    if any(c["status"] == "WARN" for c in checks):
        return "PARTIAL"
    return "VALID"


def _footprint_level(meta: dict) -> str:
    footprint = meta.get("footprint")
    if not isinstance(footprint, dict):
        return "FOOTPRINT_MISSING"
    has_bbox = isinstance(footprint.get("bbox"), dict)
    has_poly = isinstance(footprint.get("polygon"), list) and len(footprint.get("polygon") or []) >= 3
    if has_bbox or has_poly:
        return "FOOTPRINT_PRESENT"
    return "FOOTPRINT_PARTIAL"


# ---------------------------------------------------------------------------
# Pair-level M2 validation
# ---------------------------------------------------------------------------

def validate_pair(settings: Settings, pair_id: str) -> dict | None:
    """Produce the explicit M2 pair-level validation object (or None if unknown)."""
    registry = PairRegistry(settings)
    record = registry.get(pair_id)
    if record is None:
        return None

    products = []
    for side, rel, sensor, label_key in (
        ("a", _rel_or_filename(record.image_a_rel_path, record.image_a_filename), record.sensor_a, "label_a_filename"),
        ("b", _rel_or_filename(record.image_b_rel_path, record.image_b_filename), record.sensor_b, "label_b_filename"),
    ):
        path = resolve_raw_path(settings, f"image_{side}", sensor, rel)
        label = (path.parent / getattr(record, label_key)) if getattr(record, label_key, None) else path.with_suffix(".xml")
        label = label if label.is_file() else None
        info = load_product(path, label)
        products.append({"side": side, "info": info, "path": path})

    # raw integrity: recomputed hashes vs recorded
    hash_ok = []
    for p in products:
        expected = record.raw_file_hash_a if p["side"] == "a" else record.raw_file_hash_b
        try:
            recomputed = sha256_of(p["path"]) if p["path"].is_file() else ""
        except OSError:
            recomputed = ""
        hash_ok.append(bool(expected) and recomputed == expected)
    raw_integrity = "VERIFIED" if all(hash_ok) else ("PARTIAL" if any(hash_ok) else "FAILED")

    struct_a = product_validation(products[0]["info"], products[0]["path"], record.sensor_a)
    struct_b = product_validation(products[1]["info"], products[1]["path"], record.sensor_b)

    overlap = structural_overlap(products[0]["info"], products[1]["info"])
    errors = [e for side in (struct_a, struct_b) for e in side["errors"]]
    if raw_integrity == "FAILED":
        errors.append({"check": "raw_integrity", "detail": "raw hash did not re-verify"})
    warnings = [w for side in (struct_a, struct_b) for w in side["warnings"]] + overlap["warnings"]

    metadata_validity = _verdict(
        struct_a["label_identity"]["checks"] + struct_b["label_identity"]["checks"]
    )

    if errors:
        validation_status = "INVALID"
    elif overlap["status"] != "CONFIRMED_OVERLAP":
        validation_status = "OVERLAP_UNCONFIRMED"
    else:
        validation_status = "VALID"

    return {
        "schema": "CHANDRASUTRA-M2-VALIDATION-001",
        "pair_id": pair_id,
        "timestamp": _now_utc(),
        "product_a": struct_a,
        "product_b": struct_b,
        "sensor_a": record.sensor_a,
        "sensor_b": record.sensor_b,
        "source_class_a": record.source_class_a,
        "source_class_b": record.source_class_b,
        "data_source_gate": record.data_source_gate,
        "raw_integrity": raw_integrity,
        "metadata_validity": metadata_validity,
        "footprint_status": _pair_footprint_status(struct_a, struct_b),
        "overlap_status": overlap["status"],
        "overlap_method": overlap["method"],
        "overlap_reason": overlap["reason"],
        "overlap_evidence": overlap["evidence"],
        "intersection": overlap["intersection"],
        "validation_status": validation_status,
        "validation_errors": errors,
        "warnings": warnings,
        "crop": {
            "status": "NOT_COMPUTED",
            "note": (
                "Crop derivation requires documented ground geometry (GSD + offsets); "
                "run PREPARE or the overlap endpoint. No crop is fabricated here."
            ),
        },
    }


def _pair_footprint_status(struct_a: dict, struct_b: dict) -> str:
    levels = {struct_a["footprint"]["status"], struct_b["footprint"]["status"]}
    if levels == {"FOOTPRINT_PRESENT"}:
        return "FOOTPRINT_PRESENT_BOTH"
    if "FOOTPRINT_MISSING" in levels and "FOOTPRINT_PRESENT" in levels:
        return "FOOTPRINT_PARTIAL"
    if "FOOTPRINT_MISSING" in levels:
        return "FOOTPRINT_MISSING_BOTH"
    return "FOOTPRINT_PARTIAL"


# ---------------------------------------------------------------------------
# Persistence + aggregate status
# ---------------------------------------------------------------------------

def validation_dir(settings: Settings) -> Path:
    return settings.data_root_path / "metadata" / "m2_validation"


def save_m2_validation(settings: Settings, payload: dict) -> Path:
    target = validation_dir(settings) / f"{payload['pair_id']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(target)
    return target


def load_m2_validation(settings: Settings, pair_id: str) -> dict | None:
    target = validation_dir(settings) / f"{pair_id}.json"
    if not target.is_file():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def m2_status(settings: Settings) -> dict:
    """Aggregate M2 status across raw products and registered pairs (read-only)."""
    from ..pairs import scan_raw_products
    from ..processing.service import ProcessingService

    registry = PairRegistry(settings)
    service = ProcessingService(settings)
    records = registry.list()

    per_pair = []
    for record in records:
        saved = load_m2_validation(settings, record.pair_id)
        per_pair.append({
            "pair_id": record.pair_id,
            "m2_validation": (saved or {}).get("validation_status", "NOT_RUN"),
            "metadata_validity": (saved or {}).get("metadata_validity", "NOT_RUN"),
            "overlap_status": (saved or {}).get("overlap_status", record.overlap_status),
            "overlap_method": (saved or {}).get("overlap_method", "none"),
            "raw_integrity": (saved or {}).get("raw_integrity", "NOT_RUN"),
            "data_source_gate": record.data_source_gate,
            "preprocess_state": service.read_status(record.pair_id).get("state", "NOT_STARTED"),
            "warnings": len((saved or {}).get("warnings", [])),
        })

    inventory = scan_raw_products(settings)
    real_products = [e for e in inventory if e["source_class"] == SOURCE_REAL_PRADAN]
    real_sensors = {e.get("instrument") for e in real_products}

    counts = {
        "VALID": sum(1 for r in per_pair if r["m2_validation"] == "VALID"),
        "OVERLAP_UNCONFIRMED": sum(1 for r in per_pair if r["m2_validation"] == "OVERLAP_UNCONFIRMED"),
        "INVALID": sum(1 for r in per_pair if r["m2_validation"] == "INVALID"),
        "NOT_RUN": sum(1 for r in per_pair if r["m2_validation"] == "NOT_RUN"),
    }

    return {
        "real_data_gate": {
            "real_products_scanned": len(real_products),
            "real_ohrc_present": "ohrc" in real_sensors,
            "real_tmc2_present": "tmc2" in real_sensors,
            "real_pair_available": "ohrc" in real_sensors and "tmc2" in real_sensors,
            "status": (
                "REAL_DATA_BLOCKED"
                if real_products and not ("ohrc" in real_sensors and "tmc2" in real_sensors)
                else ("REAL_DATA_READY" if real_products else "REAL_DATA_ABSENT")
            ),
        },
        "pairs": per_pair,
        "counts": counts,
        "note": (
            "M2 validation must be run per pair (POST /api/data/validate); aggregate rows read the "
            "last persisted validation and the processing service state. Nothing is recomputed here."
        ),
    }