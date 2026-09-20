"""M5 spatial reliability API (/api/spatial).

Reliability-aware selection is a faithful representation of measurable
spatial evidence, not a scientific alignment claim. Missing prerequisites are
explicit (BLOCKED / INSUFFICIENT), never silently fabricated.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Settings, m4_config, m5_config
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..spatial.service import SpatialService
from ..run_guard import guard_run
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep

logger = get_logger(__name__)
router = APIRouter(prefix="/spatial", tags=["spatial"], dependencies=[Depends(current_user_dep)])

VALID_SPATIAL_CONFIG_IDS = {"SR-M5-001"}


def _service(settings: Settings) -> SpatialService:
    return SpatialService(
        settings.data_root_path,
        m5_config(),
        m4_defaults=(m4_config().get("defaults") or {}),
    )


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


@router.get("/configurations")
def list_configurations() -> dict:
    cfg = m5_config()
    return {
        "configurations": [
            {
                "spatial_reliability_configuration_id": cfg.get("spatial_reliability_configuration_id", "SR-M5-001"),
                "spatial_reliability_configuration_version": cfg.get("spatial_reliability_configuration_version", 1),
                "name": cfg.get("name", "Spatial Reliability & Reliability-Aware Selection"),
                "coordinate_space": cfg.get("coordinate_space", "pair_overlap_normalized"),
                "defaults": cfg.get("defaults", {}),
            },
        ],
        "default_spatial_reliability_configuration_id": "SR-M5-001",
        "valid_spatial_reliability_configuration_ids": sorted(VALID_SPATIAL_CONFIG_IDS),
        "note": "Engineering/policy defaults only; no scientifically tuned lunar thresholds exist yet.",
    }


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    root = service._spatial_root()
    pairs_total = 0
    pairs_complete = 0
    pairs_blocked_or_insufficient = 0
    if root.is_dir():
        for pair_dir in root.iterdir():
            if not pair_dir.is_dir():
                continue
            pairs_total += 1
            run = service.find_run_for_pair(pair_dir.name)
            status_path = None
            if run is not None:
                status_path = run / "status.json"
            if status_path is not None and status_path.is_file():
                st = json.loads(status_path.read_text(encoding="utf-8"))
                if st.get("state") == "COMPLETE":
                    pairs_complete += 1
                else:
                    pairs_blocked_or_insufficient += 1
            else:
                pairs_blocked_or_insufficient += 1
    return {
        "total_spatial_pairs": pairs_total,
        "complete_pairs": pairs_complete,
        "blocked_or_insufficient_pairs": pairs_blocked_or_insufficient,
        "note": "Spatial reliability summary (M5); not a scientific alignment claim.",
    }


class RunRequest(BaseModel):
    spatial_reliability_configuration_id: str | None = None


@router.get("/{pair_id}/status")
def pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    return service.read_status(pair_id)


@router.post("/{pair_id}/run")
def run_spatial(pair_id: str, current: AnalystUser, req: RunRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    sr_cfg_id = req.spatial_reliability_configuration_id or "SR-M5-001"
    if sr_cfg_id not in VALID_SPATIAL_CONFIG_IDS:
        raise NotFoundError(f"Unknown spatial reliability configuration: {sr_cfg_id}")
    service = _service(settings)
    return guard_run(
        settings, derived_stage="spatial", pair_id=pair_id,
        configuration_id=sr_cfg_id, tag="m5_spatial",
        fn=lambda: service.run(pair_id, spatial_config_id=sr_cfg_id),
    )


@router.post("/{pair_id}/reset")
def reset_pair(pair_id: str, current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    service.reset(pair_id)
    return {
        "reset": True,
        "pair_id": pair_id,
        "status": service.read_status(pair_id),
        "note": "Only derived spatial artifacts were removed. M4/M3/M2/raw data untouched.",
    }


@router.get("/{pair_id}/manifest")
def pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.manifest(pair_id)
    if "error" in result:
        raise NotFoundError(f"No spatial manifest for pair {pair_id} — run SPATIAL first.")
    return {"pair_id": pair_id, "manifest": result}


@router.get("/{pair_id}/summary")
def pair_summary(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.summary(pair_id)
    if "error" in result:
        raise NotFoundError(f"No spatial summary for pair {pair_id} — run SPATIAL first.")
    return {"pair_id": pair_id, "summary": result}


@router.get("/{pair_id}/map")
def pair_map(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.reliability_map(pair_id)
    if "error" in result:
        raise NotFoundError(f"No reliability map for pair {pair_id}.")
    return {"pair_id": pair_id, "map": result}


@router.get("/{pair_id}/components")
def pair_components(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.components(pair_id)
    if "error" in result:
        raise NotFoundError(f"No components for pair {pair_id}.")
    return {"pair_id": pair_id, "components": result}


@router.get("/{pair_id}/cells")
def pair_cells(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.cells(pair_id)
    if "error" in result:
        raise NotFoundError(f"No cells for pair {pair_id}.")
    return {"pair_id": pair_id, "cells": result}


@router.get("/{pair_id}/mapping")
def pair_mapping(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.mapping(pair_id)
    if "error" in result:
        raise NotFoundError(f"No scene mapping for pair {pair_id}.")
    return {"pair_id": pair_id, "mapping": result}


@router.get("/{pair_id}/selection")
def pair_selection(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.selection(pair_id)
    if "error" in result:
        raise NotFoundError(f"No selection for pair {pair_id}.")
    return {"pair_id": pair_id, "selection": result}


@router.get("/{pair_id}/selected-correspondences")
def pair_selected_correspondences(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    result = service.selected_correspondences(pair_id)
    if "error" in result:
        raise NotFoundError(f"No selected correspondences for pair {pair_id}.")
    return {"pair_id": pair_id, "selected_correspondences": result}