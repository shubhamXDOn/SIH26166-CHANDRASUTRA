"""Pair management + validation API (M1).

Design (metadata-first): list/detail endpoints never open image files; only
``probe`` (on demand) and ``preview`` (lazy, derived) touch actual products.
No scientific matching results exist here — ever.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import Settings, m1_config
from ..errors import AppError, NotFoundError, ValidationError
from ..loader import UNKNOWN, build_preview, load_product
from ..logging_conf import get_logger
from ..pairs import (
    OVERLAP_STATUSES,
    PairRegistry,
    build_record_from_products,
    infer_sensor_id_from_path,
    metadata_completeness,
    resolve_raw_path,
    validate_record,
    write_validation_record,
    _rel_or_filename,
)
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep

logger = get_logger(__name__)
router = APIRouter(prefix="/pairs", tags=["pairs"], dependencies=[Depends(current_user_dep)])


def _allowed_raw_locations() -> list[str]:
    return m1_config().get("allowed_raw_locations", [])


class RegisterPairRequest(BaseModel):
    """Registration references existing raw files; nothing is copied/moved."""

    image_a: str
    label_a: str | None = None
    image_b: str
    label_b: str | None = None
    sensor_a: str | None = None
    sensor_b: str | None = None
    overlap_status: str = "UNKNOWN"
    overlap_evidence: str = ""
    illumination_info: str | None = None
    viewing_geometry_info: str | None = None
    data_use_notes: str | None = None
    attribution_notes: str | None = None
    notes: str | None = None
    pair_id: str | None = None
    source_url: str = "https://pradan.issdc.gov.in/ch2/"


def _prod_error(exc: AppError):
    exc.code = "PRODUCT_READ_FAILED"
    exc.http_status = 422
    exc.user_message = "A selected product could not be opened as a valid CH-2 product."
    return exc


def _registry(settings: Settings) -> PairRegistry:
    return PairRegistry(settings)


def _summary(record) -> dict:
    completeness = metadata_completeness(record)
    return {
        "pair_id": record.pair_id,
        "sensor_a": record.sensor_a,
        "sensor_b": record.sensor_b,
        "image_a_filename": record.image_a_filename,
        "image_b_filename": record.image_b_filename,
        "image_a_product_id": record.image_a_product_id,
        "image_b_product_id": record.image_b_product_id,
        "dimensions_a": f"{record.image_a_width}x{record.image_a_height}",
        "dimensions_b": f"{record.image_b_width}x{record.image_b_height}",
        "nominal_gsd_a": record.nominal_gsd_a,
        "nominal_gsd_b": record.nominal_gsd_b,
        "overlap_status": record.overlap_status,
        "metadata_completeness": completeness,
        "validation_status": record.validation_status,
        "ingestion_status": record.ingestion_status,
        "last_validated_utc": record.last_validated_utc,
        "registered_at_utc": record.registered_at_utc,
    }


# --------------------------------------------------------------------------
# List / scan / probe / next-id (declared before /{pair_id})
# --------------------------------------------------------------------------

@router.get("")
def list_pairs(settings: Settings = Depends(get_settings)) -> dict:
    records = _registry(settings).list()
    return {
        "count": len(records),
        "pairs": [_summary(r) for r in records],
        "note": "Metadata only — no files are opened for listing.",
    }


@router.get("/next-id")
def next_pair_id(settings: Settings = Depends(get_settings)) -> dict:
    return {"pair_id": _registry(settings).next_pair_id(), "format": "CS-PNNN"}


@router.get("/scan")
def scan_raw_dirs(settings: Settings = Depends(get_settings)) -> dict:
    """List candidate products already present under data/raw (no opening)."""
    root = settings.data_root_path
    result: list[dict] = []
    for rel in _allowed_raw_locations():
        d = root / rel
        if not d.is_dir():
            result.append({"id": rel, "path": rel, "exists": False, "products": [], "note": "directory missing"})
            continue
        entries: list[dict] = []
        label_map: dict[str, str] = {}
        for f in sorted(d.iterdir()):
            if f.suffix.lower() == ".xml":
                label_map[f.stem] = f.name
        seen: set[str] = set()
        for f in sorted(d.iterdir()):
            if not f.is_file() or f.suffix.lower() == ".xml":
                continue
            if f.suffix.lower() not in (".img", ".tif", ".tiff", ".png", ".jpg", ".jpeg"):
                continue
            base = f.stem
            if base in seen:
                continue
            seen.add(base)
            entries.append(
                {
                    "image": f.name,
                    "label": label_map.get(base),
                    "size_bytes": f.stat().st_size,
                    "kind": "product" if f.suffix.lower() == ".img" else f.suffix.lower().lstrip("."),
                }
            )
        result.append({"id": rel, "path": rel, "exists": True, "products": entries})
    return {"raw_dirs": result, "note": "File listing only; nothing is opened or modified."}


@router.get("/probe")
def probe_product(path: str = Query(...), settings: Settings = Depends(get_settings)) -> dict:
    """Read metadata from one candidate product (label-driven)."""
    if ".." in path:
        raise ValidationError("Path must stay inside the data root.")
    try:
        image_path = resolve_raw_path(settings, "probe", None, path)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if not image_path.is_file():
        raise NotFoundError(f"Product not found at {path!r}")
    label_path = image_path.with_suffix(".xml") if image_path.suffix.lower() in (".img",) else None
    if label_path and not label_path.is_file():
        label_path = None
    info = load_product(image_path, label_path)
    if info.status == "FAILURE":
        err = AppError(info.error.get("message", "Could not read the product."),
                       details=info.error.get("details", {}))
        err.code = info.error.get("code", "PRODUCT_READ_FAILED")
        err.http_status = 422
        err.user_message = "The selected product could not be read as a CH-2 product."
        raise err
    public = _public_product_dict(info, settings)
    return {"product": public, "note": "Metadata read only — raw file untouched."}


def _public_product_dict(info, settings: Settings) -> dict:
    """Scrub absolute server paths from product payloads."""
    data = info.to_dict()
    data.pop("path", None)
    try:
        data["rel_path"] = str(Path(info.path).resolve().relative_to(settings.data_root_path.resolve())).replace("\\", "/")
    except (ValueError, OSError):
        data["rel_path"] = UNKNOWN
    return data


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

@router.post("/register")
def register_pair(current: AnalystUser, req: RegisterPairRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    reg = _registry(settings)
    sensor_a = req.sensor_a or infer_sensor_id_from_path(settings, req.image_a)
    sensor_b = req.sensor_b or infer_sensor_id_from_path(settings, req.image_b)

    # 1. deterministic, stable, unique Pair ID
    pair_id = req.pair_id or reg.next_pair_id()
    if req.pair_id is None:
        pair_id = reg.next_pair_id()
    elif err := reg.validate_pair_id(pair_id):
        raise ValidationError(err)

    # 2. resolve + load both products (labels optional but preferred)
    try:
        path_a = resolve_raw_path(settings, "image_a", sensor_a, req.image_a)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    try:
        path_b = resolve_raw_path(settings, "image_b", sensor_b, req.image_b)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    if not path_a.is_file():
        raise NotFoundError(f"Image A raw file not found: {req.image_a!r}")
    if not path_b.is_file():
        raise NotFoundError(f"Image B raw file not found: {req.image_b!r}")

    label_a = _resolve_label(path_a, req.label_a)
    label_b = _resolve_label(path_b, req.label_b)

    prod_a = load_product(path_a, label_a)
    if prod_a.status != "OK":
        raise _prod_error(AppError(prod_a.error.get("message", "Image A unreadable"),
                                   details=prod_a.error.get("details", {})))
    prod_b = load_product(path_b, label_b)
    if prod_b.status != "OK":
        raise _prod_error(AppError(prod_b.error.get("message", "Image B unreadable"),
                                   details=prod_b.error.get("details", {})))

    if req.overlap_status not in OVERLAP_STATUSES:
        raise ValidationError(
            f"overlap_status must be one of {', '.join(OVERLAP_STATUSES)}."
        )

    record = build_record_from_products(
        pair_id,
        prod_a,
        prod_b,
        rel_a=req.image_a,
        rel_b=req.image_b,
        sensor_a=sensor_a,
        sensor_b=sensor_b,
        overlap_status=req.overlap_status,
        overlap_evidence=req.overlap_evidence,
        illumination_info=req.illumination_info or "",
        viewing_geometry_info=req.viewing_geometry_info or "",
        data_use_notes=req.data_use_notes or "",
        attribution_notes=req.attribution_notes or "",
        notes=req.notes or "",
        source_url=req.source_url,
    )
    record = reg.save(record)
    logger.info("Registered %s (%s x %s)", record.pair_id, record.sensor_a, record.sensor_b,
                extra={"operation": "register_pair", "status": "ok"})
    return {"registered": True, "pair_id": record.pair_id, "record": record.model_dump(),
            "note": "Raw files were referenced, never copied or modified."}


def _resolve_label(image_path: Path, provided: str | None) -> Path | None:
    if provided:
        return (image_path.parent / provided).resolve()
    sibling = image_path.with_suffix(".xml")
    return sibling if sibling.is_file() else None


# --------------------------------------------------------------------------
# Detail / validation / preview
# --------------------------------------------------------------------------

@router.get("/{pair_id}")
def pair_detail(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    record = _registry(settings).get(pair_id)
    if record is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    return {
        "record": record.model_dump(),
        "summary": _summary(record),
        "completeness": metadata_completeness(record),
    }


@router.get("/{pair_id}/validate")
def get_validation(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    record = _registry(settings).get(pair_id)
    if record is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    result = validate_record(record, settings)
    result["persisted"] = False
    return result


@router.post("/{pair_id}/validate")
def run_validation(pair_id: str, current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    reg = _registry(settings)
    record = reg.get(pair_id)
    if record is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    result = validate_record(record, settings)
    write_validation_record(result, settings)
    record.validation_status = result["status"]
    record.last_validated_utc = result["timestamp"]
    reg.save(record)
    result["persisted"] = True
    logger.info("Validated %s -> %s", pair_id, result["status"],
                extra={"operation": "validate_pair", "status": "done"})
    return result


@router.get("/{pair_id}/preview/{side}")
def pair_preview(pair_id: str, side: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    record = _registry(settings).get(pair_id)
    if record is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    if side not in ("a", "b"):
        raise ValidationError("side must be 'a' or 'b'.")
    rel = record.image_a_rel_path if side == "a" else record.image_b_rel_path
    sensor = record.sensor_a if side == "a" else record.sensor_b
    try:
        image_path = resolve_raw_path(settings, f"image_{side}", sensor,
                                      _rel_or_filename(rel, record.image_a_filename if side == "a" else record.image_b_filename))
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if not image_path.is_file():
        raise NotFoundError("Raw product file is missing.")
    label = _resolve_label(image_path, record.label_a_filename if side == "a" else record.label_b_filename)
    info = load_product(image_path, label)
    if info.status != "OK":
        return _preview_unavailable_json(info)
    png = build_preview(settings, info, max_width=int(m1_config().get("preview_max_width", 640)))
    return FileResponse(str(png), media_type="image/png", filename=png.name)


def _preview_unavailable_json(info):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=200,
        content={
            "error": {
                "code": "PREVIEW_UNAVAILABLE",
                "message": "Scientific preview unavailable for this product.",
                "user_message": "Scientific preview unavailable — " + (info.error or {}).get("message", "unknown reason"),
                "severity": "warning",
                "retryable": False,
                "details": {"reason": (info.error or {}).get("code", "UNKNOWN")},
            }
        },
    )