"""M8 SPATIAL SELECTION API.

Endpoints mounted by ``api/router.py`` (namespaced under ``/spatial-m8``; the
legacy M5 router owns ``/api/spatial``):

    GET  /api/pairs/{pair_id}/spatial-m8/status      (read)
    GET  /api/pairs/{pair_id}/spatial-m8/runs        (read)
    POST /api/pairs/{pair_id}/spatial-m8/run         (writes one m8 artifact)
    GET  /api/spatial-m8/runs/{run_id}               (read)

M8 consumes an ACCEPTED M7 trust gate artifact, deterministically recovers the
trusted correspondence set, computes spatial bookkeeping evidence and the
balanced selection, and records evidence only — it never overrides the M7
verdict and never emits ``confidence`` vocabulary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.dependencies import AnalystUser, current_user_dep
from ..config import Settings
from ..errors import NotFoundError
from ..pairs import PairRegistry
from ..run_guard import guard_run
from .deps import get_settings

pair_router = APIRouter(prefix="/pairs", tags=["spatial-m8"],
                        dependencies=[Depends(current_user_dep)])
spatial_router = APIRouter(prefix="/spatial-m8", tags=["spatial-m8"],
                           dependencies=[Depends(current_user_dep)])


class SpatialRunRequest(BaseModel):
    trust_run_id: str | None = None


def _service(settings: Settings):
    from ..spatial_m8.service import SpatialSelectionService

    return SpatialSelectionService(settings)


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


# ---------------------------------------------------------------------------
# pair-scoped spatial selection
# ---------------------------------------------------------------------------

@pair_router.get("/{pair_id}/spatial-m8/status")
def spatial_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _service(settings).status(pair_id)


@pair_router.get("/{pair_id}/spatial-m8/runs")
def spatial_runs(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return {"pair_id": pair_id, "runs": _service(settings).list_runs(pair_id)}


@pair_router.post("/{pair_id}/spatial-m8/run")
def spatial_run(pair_id: str, req: SpatialRunRequest,
                current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    return guard_run(
        settings, derived_stage="spatial-m8", pair_id=pair_id,
        configuration_id=service.config.configuration_id,
        tag="m8_spatial_selection",
        fn=lambda: service.run(pair_id, trust_run_id=req.trust_run_id),
    )


# ---------------------------------------------------------------------------
# run read surface
# ---------------------------------------------------------------------------

@spatial_router.get("/runs/{run_id}")
def spatial_run_detail(run_id: str, settings: Settings = Depends(get_settings)) -> dict:
    payload = _service(settings).read(run_id)
    if payload is None:
        raise NotFoundError(f"No M8 spatial selection run with id {run_id}.")
    return payload