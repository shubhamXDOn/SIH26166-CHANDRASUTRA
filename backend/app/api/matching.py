"""M3 matching API (/api/matching) + M8 deep-matcher expansion API.

Exposes the adaptive strategy engine + candidate correspondences (M3) and the
M8 benchmark/adaptive-expansion layer. Blocked is a first-class, truthful
outcome; candidate correspondences are explicitly NOT verified truth. Nothing
here claims an accuracy or trust verdict.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from ..config import Settings
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep
from ..matching.config import configurations_public as m3_configurations_public
from ..matching.service import (
    MatchingService,
    default_matcher_configuration_id,
    matching_overview,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/matching", tags=["matching"], dependencies=[Depends(current_user_dep)])


class RunRequest:
    pass


from pydantic import BaseModel


class RunRequest(BaseModel):
    configuration_id: str | None = None
    mode: str | None = None
    benchmark: bool = False


def _service(settings: Settings) -> MatchingService:
    return MatchingService(settings)


def _m8_service(settings: Settings):
    from ..matching.m8.service import M8Service

    return M8Service(settings)


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


# Declared before /{pair_id} so route matching never swallows them.
@router.get("/configurations")
def list_configurations() -> dict:
    configs = m3_configurations_public()
    return {
        "configurations": configs,
        "default_configuration_id": default_matcher_configuration_id(),
        "note": ("Registered M3 matching configurations (engineering defaults, no scientific "
                 "thresholds; routing scores are what-to-try weights, not quality verdicts)."),
    }


@router.get("/capabilities")
def list_capabilities() -> dict:
    from ..matching.m8.capabilities import (capabilities_public,
                                            configurations_public as m8_configs_public,
                                            device_public, reset_registry)

    reset_registry()
    return {
        "matchers": capabilities_public(),
        "device": device_public(),
        "configurations": m8_configs_public(),
        "note": ("Honest capability report: availability is probe-checked at request time; "
                 "deep matchers are only available when their weights are provisioned."),
    }


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict:
    return matching_overview(settings)


@router.get("/{pair_id}/status")
def pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    return service.read_status(pair_id)


@router.post("/{pair_id}/run")
def run_match(pair_id: str, current: AnalystUser, req: RunRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    if req.mode or req.benchmark:
        return _m8_service(settings).run(pair_id, configuration_id=req.configuration_id,
                                         mode=req.mode or "AUTO", benchmark=req.benchmark)
    service = _service(settings)
    return service.run(pair_id, configuration_id=req.configuration_id)


@router.post("/{pair_id}/reset")
def reset_pair(pair_id: str, current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    service.reset(pair_id)
    status = service.read_status(pair_id)
    return {
        "reset": True,
        "pair_id": pair_id,
        "status": status,
        "note": "Only derived matching artifacts were removed. M2 products, raw data and metadata are untouched.",
    }


@router.get("/{pair_id}/decisions")
def pair_decisions(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    decisions = service.decisions(pair_id)
    if decisions is None:
        raise NotFoundError(f"No matching decisions exist for pair {pair_id} — run MATCH first.")
    return {"pair_id": pair_id, "decisions": decisions}


@router.get("/{pair_id}/candidates")
def pair_candidates(
    pair_id: str,
    settings: Settings = Depends(get_settings),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    match_tile_id: str | None = None,
) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    index = service.candidate_index(pair_id)
    if index is None:
        raise NotFoundError(f"No candidate data exists for pair {pair_id} — run MATCH first.")
    tiles = index.get("tiles", [])
    if match_tile_id:
        tiles = [t for t in tiles if t.get("match_tile_id") == match_tile_id]
    total = len(tiles)
    page = tiles[offset:offset + limit]
    return {
        "pair_id": pair_id,
        "configuration_id": index.get("configuration_id"),
        "total": total,
        "offset": offset,
        "limit": limit,
        "counts": index.get("counts"),
        "total_candidates": index.get("total_candidates"),
        "tiles": page,
        "note": "Per-tile candidate summaries only; individual correspondences are available per match tile.",
    }


@router.get("/{pair_id}/tiles")
def pair_match_tiles(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    tiles = service.match_tiles(pair_id)
    if tiles is None:
        raise NotFoundError(f"No match tiles exist for pair {pair_id} — run MATCH first.")
    return {"pair_id": pair_id, "tiles": tiles}


@router.get("/{pair_id}/tiles/{match_tile_id}")
def pair_match_tile(pair_id: str, match_tile_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    tile = service.tile(pair_id, match_tile_id)
    if tile is None:
        raise NotFoundError(f"No match tile {match_tile_id} for pair {pair_id}.")
    return {"pair_id": pair_id, "tile": tile}


@router.get("/{pair_id}/tiles/{match_tile_id}/candidates")
def pair_tile_candidates(pair_id: str, match_tile_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    payload = service.tile_candidates(pair_id, match_tile_id)
    if payload is None:
        raise NotFoundError(f"No candidate data for match tile {match_tile_id} of pair {pair_id}.")
    return {"pair_id": pair_id, "match_tile_id": match_tile_id, "candidates": payload}


@router.get("/{pair_id}/manifest")
def pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    manifest = service.manifest(pair_id)
    if manifest is None:
        raise NotFoundError(f"No matching manifest exists for pair {pair_id} — run MATCH first.")
    return {"pair_id": pair_id, "manifest": manifest}


@router.get("/{pair_id}/summary")
def pair_summary(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _service(settings)
    summary = service.summary(pair_id)
    if summary is None:
        raise NotFoundError(f"No matching summary exists for pair {pair_id} — run MATCH first.")
    return {"pair_id": pair_id, "summary": summary}


# ---------------------------------------------------------------------------
# M8 deep matcher expansion + benchmark routes (under /matching/{pair_id}/m8)
# ---------------------------------------------------------------------------
@router.post("/{pair_id}/m8/run")
def run_m8(pair_id: str, current: AnalystUser, req: RunRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    return _m8_service(settings).run(pair_id, configuration_id=req.configuration_id,
                                     mode=req.mode or "AUTO", benchmark=req.benchmark)


@router.get("/{pair_id}/m8/status")
def m8_pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _m8_service(settings).read_status(pair_id)


@router.get("/{pair_id}/m8/runs")
def m8_pair_runs(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    service = _m8_service(settings)
    run = service.find_run_for_pair(pair_id)
    return {
        "pair_id": pair_id,
        "runs": [{
            "configuration_id": run.name,
            "proc_cfg": run.parent.parent.name if run else None,
            "status": service.read_status(pair_id, run.name if run else "DM-M8-001").get("state"),
        }] if run else [],
        "note": "M8 run directories are never picked up by the M3/M4 read paths.",
    }


@router.post("/{pair_id}/m8/reset")
def m8_reset_pair(pair_id: str, current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _m8_service(settings)
    from ..matching.m8.capabilities import reset_registry

    reset_registry()
    service.reset(pair_id)
    return {
        "reset": True,
        "pair_id": pair_id,
        "status": service.read_status(pair_id),
        "note": "Only derived M8 expansion artifacts were removed (matching/M4 inputs are untouched).",
    }


@router.get("/{pair_id}/m8/routing")
def m8_pair_routing(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    routing = _m8_service(settings).routing(pair_id)
    if routing is None:
        raise NotFoundError(f"No M8 routing data exists for pair {pair_id} — run EXPAND first.")
    return {"pair_id": pair_id, "routing": routing}


@router.get("/{pair_id}/m8/candidates")
def m8_pair_candidates(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    index = _m8_service(settings).candidate_index(pair_id)
    if index is None:
        raise NotFoundError(f"No M8 candidate data exists for pair {pair_id} — run EXPAND first.")
    return {"pair_id": pair_id, "index": index}


@router.get("/{pair_id}/m8/tiles/{match_tile_id}/candidates")
def m8_pair_tile_candidates(pair_id: str, match_tile_id: str,
                            settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    payload = _m8_service(settings).tile_candidates(pair_id, match_tile_id)
    if payload is None:
        raise NotFoundError(f"No M8 candidate data for match tile {match_tile_id} of pair {pair_id}.")
    return {"pair_id": pair_id, "match_tile_id": match_tile_id, "candidates": payload}


@router.get("/{pair_id}/m8/benchmark")
def m8_pair_benchmark(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    payload = _m8_service(settings).benchmark(pair_id)
    if payload is None:
        raise NotFoundError(f"No M8 benchmark data exists for pair {pair_id} — run EXPAND with benchmark mode first.")
    return {"pair_id": pair_id, "benchmark": payload}


@router.get("/{pair_id}/m8/manifest")
def m8_pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    manifest = _m8_service(settings).manifest(pair_id)
    if manifest is None:
        raise NotFoundError(f"No M8 manifest exists for pair {pair_id} — run EXPAND first.")
    return {"pair_id": pair_id, "manifest": manifest}


@router.get("/{pair_id}/m8/provenance")
def m8_pair_provenance(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    provenance = _m8_service(settings).provenance(pair_id)
    if provenance is None:
        raise NotFoundError(f"No M8 provenance exists for pair {pair_id} — run EXPAND first.")
    return {"pair_id": pair_id, "provenance": provenance}


@router.get("/{pair_id}/m8/experiment")
def m8_pair_experiment(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    experiment = _m8_service(settings).experiment(pair_id)
    if experiment is None:
        raise NotFoundError(f"No M8 experiment identity exists for pair {pair_id} — run EXPAND first.")
    return {"pair_id": pair_id, "experiment": experiment}


@router.get("/{pair_id}/m8/summary")
def m8_pair_summary(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    summary = _m8_service(settings).summary(pair_id)
    if summary is None:
        raise NotFoundError(f"No M8 summary exists for pair {pair_id} — run EXPAND first.")
    return {"pair_id": pair_id, "summary": summary}