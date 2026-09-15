"""Data / datasets endpoint (M0 foundation, upgraded by M1).

Exposes the real on-disk data architecture readiness *and* the real M1 pair
metadata aggregates. No science is performed here and no counts are faked:
with zero registered pairs every counter honestly reads zero.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings
from ..data import data_directory_status, ensure_derived_directories
from ..logging_conf import get_logger
from ..pairs import PairRegistry, metadata_completeness
from .deps import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/data", tags=["data"])


def _directory_dicts(settings: Settings) -> list[dict]:
    return [
        {
            "id": d.id,
            "path": d.path,
            "description": d.description,
            "exists": d.exists,
            "is_raw": d.is_raw,
        }
        for d in data_directory_status(settings)
    ]


def _raw_product_count(settings: Settings) -> int:
    root = settings.data_root_path
    count = 0
    for d in data_directory_status(settings):
        if d.is_raw and d.exists:
            dir_path = root / d.path
            try:
                count += sum(1 for f in dir_path.iterdir() if f.is_file() and not f.name.startswith("."))
            except OSError:
                continue
    return count


@router.get("/status")
def data_status(settings: Settings = Depends(get_settings)) -> dict:
    """Live status of data architecture + real M1 pair registry aggregates."""
    ensure_derived_directories(settings)
    directories = _directory_dicts(settings)
    ready = [d for d in directories if d["exists"]]

    registry = PairRegistry(settings)
    records = registry.list()
    valid = [r for r in records if r.validation_status == "VALID"]
    candidate = [r for r in records if r.overlap_status == "OVERLAP_UNCONFIRMED"]
    confirmed = [r for r in records if r.overlap_status == "CONFIRMED_OVERLAP"]
    completeness_values = [metadata_completeness(r)["fraction"] for r in records]

    sensors: list[str] = []
    for r in records:
        for key in ("sensor_a", "sensor_b"):
            value = getattr(r, key, "")
            if value in ("", "UNKNOWN"):
                continue
            if value not in sensors:
                sensors.append(value)

    first_pair = None
    if records:
        first_pair = {
            "pair_id": records[0].pair_id,
            "validation_status": records[0].validation_status,
            "overlap_status": records[0].overlap_status,
        }

    last_ingestion = max((r.registered_at_utc for r in records), default=None)
    last_validation = max((r.last_validated_utc for r in records), default=None)

    return {
        "root": str(settings.data_root_path),
        "milestone": settings.milestone,
        "product": settings.product_name,
        "pairs_registered": len(records),
        "pairs_valid": len(valid),
        "pairs_candidate": len(candidate),
        "pairs_confirmed_overlap": len(confirmed),
        "raw_products_present": _raw_product_count(settings),
        "metadata_completeness": {
            "average_fraction": round(sum(completeness_values) / len(completeness_values), 3) if completeness_values else 0.0,
            "per_pair": {r.pair_id: metadata_completeness(r)["fraction"] for r in records},
        },
        "first_pair_status": first_pair,
        "available_sensors": sensors,
        "last_ingestion_utc": last_ingestion,
        "last_validation_utc": last_validation,
        "source": {
            "organization": "ISRO / ISSDC",
            "archive": "PRADAN",
            "mission": "Chandrayaan-2",
            "url": "https://pradan.issdc.gov.in/ch2/",
            "access": {
                "anonymous": False,
                "note": "PRADAN requires user registration and administrator approval before downloads are permitted.",
            },
        },
        "pairs_note": (
            "No OHRC–TMC-2 pair is registered yet. Real products must be placed "
            "under data/raw and registered via the Data workspace. Official downloads "
            "require a PRADAN account with approved access."
            if not records
            else f"{len(records)} pair(s) registered — most recent {records[-1].pair_id}."
        ),
        "raw_policy": "immutable — writing to data/raw is forbidden by design.",
        "directories": directories,
        "summary": {
            "total": len(directories),
            "present": len(ready),
            "missing": len(directories) - len(ready),
        },
    }


@router.get("/sensors")
def sensors() -> dict:
    """Phase-A sensor catalog (documentation value, no fabricated imagery)."""
    return {
        "phase_a": [
            {
                "id": "ohrc",
                "name": "Orbiter High Resolution Camera",
                "mission": "Chandrayaan-2",
                "kind": "panchromatic, ~0.25 m/px at 100 km",
                "role": "high-resolution detail layer",
            },
            {
                "id": "tmc2",
                "name": "Terrain Mapping Camera-2",
                "mission": "Chandrayaan-2",
                "kind": "stereoscopic terrain mapping (~5 m/px)",
                "role": "regional context / stereo layer",
            },
        ],
        "reference": {
            "id": "lroc",
            "name": "Lunar Reconnaissance Orbiter Camera",
            "mission": "NASA LRO",
            "role": "independent reference for later validation (M+ milestones)",
        },
        "future": ["iirs", "chandrayaan3"],
        "note": "Catalog only. No images are claimed to be loaded until real files exist.",
    }