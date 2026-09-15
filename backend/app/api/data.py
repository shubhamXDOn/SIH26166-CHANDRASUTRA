"""Data / datasets FOUNDATION endpoints (M0).

Exposes the real on-disk data architecture readiness only. No science is
performed here. Real ingestion, validation and pair management arrive in M1.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings
from ..data import data_directory_status, ensure_derived_directories
from ..logging_conf import get_logger
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


@router.get("/status")
def data_status(settings: Settings = Depends(get_settings)) -> dict:
    """Live status of the data architecture (directories only)."""
    ensure_derived_directories(settings)
    directories = _directory_dicts(settings)
    ready = [d for d in directories if d["exists"]]
    return {
        "root": str(settings.data_root_path),
        "milestone": "M0",
        "pairs_registered": 0,
        "pairs_note": "No OHRC-TMC-2 pair registered yet. First documented pair arrives in M1 from ISSDC PRADAN.",
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