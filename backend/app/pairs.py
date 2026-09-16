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
from .loader import UNKNOWN, ProductInfo, load_product, sha256_of

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