"""M2 processing API (/api/processing).

Exposes the registered configurations and the per-pair PREPARE lifecycle.
BLOCKED is a first-class outcome (real pairs without documented geometry) and
is returned as a normal 200 response carrying status.blocked — it is never
silenced into "success".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import Settings
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep
from ..processing.config import configurations_public
from ..processing.service import ProcessingService, default_configuration_id, processing_overview

logger = get_logger(__name__)
router = APIRouter(prefix="/processing", tags=["processing"], dependencies=[Depends(current_user_dep)])


class PrepareRequest(BaseModel):
    configuration_id: str | None = None
    geometry: dict[str, Any] | None = None


def _service(settings: Settings) -> ProcessingService:
    return ProcessingService(settings)


# Declared before /{pair_id} so route matching never swallows them.
@router.get("/configurations")
def list_configurations() -> dict:
    configs = configurations_public()
    return {
        "configurations": configs,
        "default_configuration_id": default_configuration_id(),
        "note": "Registered M2 processing configurations (engineering defaults, no scientific thresholds).",
    }


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict:
    return processing_overview(settings)


@router.get("/{pair_id}/status")
def pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    status = service.read_status(pair_id, status_configuration(service, pair_id))
    run = service.find_run_for_pair(pair_id)
    if run is not None:
        status["manifest_present"] = (run / "processing_manifest.json").is_file()
        status["conditions_present"] = (run / "diagnostics" / "conditions.json").is_file()
    else:
        status["manifest_present"] = False
        status["conditions_present"] = False
    return status


def status_configuration(service: ProcessingService, pair_id: str) -> str:
    run = service.find_run_for_pair(pair_id)
    if run is not None:
        manifest = service.manifest(pair_id)
        if manifest and manifest.get("configuration", {}).get("configuration_id"):
            return manifest["configuration"]["configuration_id"]
    return default_configuration_id()


@router.post("/{pair_id}/prepare")
def run_prepare(pair_id: str, current: AnalystUser, req: PrepareRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    service = _service(settings)
    status = service.prepare(
        pair_id,
        configuration_id=req.configuration_id,
        geometry=req.geometry,
    )
    status["finished_at"] = status.get("finished_at")
    return status


@router.post("/{pair_id}/reset")
def reset_pair(pair_id: str, current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    service.reset(pair_id)
    return {
        "reset": True,
        "pair_id": pair_id,
        "status": service.read_status(pair_id, default_configuration_id()),
        "note": "Only derived processing artifacts were removed. data/raw is immutable and untouched.",
    }


@router.get("/{pair_id}/manifest")
def pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    manifest = service.manifest(pair_id)
    if manifest is None:
        raise NotFoundError(f"No processing manifest exists for pair {pair_id} — run PREPARE first.")
    return {"pair_id": pair_id, "manifest": manifest}


@router.get("/{pair_id}/conditions")
def pair_conditions(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    conditions = service.conditions(pair_id)
    if conditions is None:
        raise NotFoundError(f"No condition analysis exists for pair {pair_id} — PREPARE did not reach condition analysis.")
    return {"pair_id": pair_id, "conditions": conditions}


@router.get("/{pair_id}/tiles")
def pair_tiles(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    tiles = service.tiles(pair_id)
    if tiles is None:
        raise NotFoundError(f"No tiles exist for pair {pair_id}.")
    return {"pair_id": pair_id, "tiles": tiles}


@router.get("/{pair_id}/tiles/{tile_id}")
def pair_tile(pair_id: str, tile_id: str, settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    tile = service.tile(pair_id, tile_id)
    if tile is None:
        raise NotFoundError(f"No tile with ID {tile_id} for pair {pair_id}.")
    return {"pair_id": pair_id, "tile": tile}


@router.get("/{pair_id}/tiles/{tile_id}/preview")
def pair_tile_preview(pair_id: str, tile_id: str, settings: Settings = Depends(get_settings)) -> FileResponse:
    service = _service(settings)
    registry = PairRegistry(settings)
    if registry.get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")
    preview = service.tile_preview_path(pair_id, tile_id)
    if preview is None or not preview.is_file():
        raise NotFoundError(f"Preview unavailable for tile {tile_id}.")
    return FileResponse(str(preview), media_type="image/png", filename=preview.name)