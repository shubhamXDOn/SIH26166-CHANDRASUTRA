"""M6 adaptive matcher router API lives partly here.

Endpoints mounted by ``api/router.py``:

    GET  /api/matching/routing/capabilities        (read)
    GET  /api/pairs/{pair_id}/routing/status       (read)
    GET  /api/pairs/{pair_id}/routing/runs         (read)
    POST /api/pairs/{pair_id}/routing/run          (writes one routing artifact)
    POST /api/pairs/{pair_id}/routing/execute      (optional dispatch)
    GET  /api/routing/runs/{run_id}                (read)

Routing is deterministic policy over the M5 condition profile. It is NOT a
matcher itself, never claims an accuracy/quality verdict, and never emits
``selected_matcher``/``confidence`` vocabulary.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Settings
from ..errors import NotFoundError
from ..pairs import PairRegistry
from ..run_guard import guard_run
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep

pair_router = APIRouter(prefix="/pairs", tags=["routing"], dependencies=[Depends(current_user_dep)])
routing_router = APIRouter(prefix="/routing", tags=["routing"], dependencies=[Depends(current_user_dep)])
capability_router = APIRouter(prefix="/matching", tags=["routing"], dependencies=[Depends(current_user_dep)])


class RoutingRunRequest(BaseModel):
    mode: str | None = None
    configuration_id: str | None = None
    rules_override: list[dict] | None = None


class RoutingExecuteRequest(BaseModel):
    run_id: str


def _service(settings: Settings):
    from ..routing.service import RoutingService

    return RoutingService(settings)


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


# ---------------------------------------------------------------------------
# capability / configuration read surface
# ---------------------------------------------------------------------------

@capability_router.get("/routing/capabilities")
def matching_routing_capabilities() -> dict:
    from ..state import get_state

    return _service(get_state().settings).capabilities_public()


# ---------------------------------------------------------------------------
# pair-scoped routing runs
# ---------------------------------------------------------------------------

@pair_router.get("/{pair_id}/routing/status")
def routing_pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _service(settings).status(pair_id)


@pair_router.get("/{pair_id}/routing/runs")
def routing_pair_runs(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return {"pair_id": pair_id, "runs": _service(settings).list_runs(pair_id)}


@pair_router.post("/{pair_id}/routing/run")
def routing_run(pair_id: str, req: RoutingRunRequest,
                current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    return guard_run(
        settings, derived_stage="routing", pair_id=pair_id,
        configuration_id=req.configuration_id or service.config.configuration_id,
        tag="m6_routing",
        fn=lambda: service.run(pair_id, mode=req.mode, rules_override=req.rules_override),
    )


@pair_router.post("/{pair_id}/routing/execute")
def routing_execute(pair_id: str, req: RoutingExecuteRequest,
                    current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    return guard_run(
        settings, derived_stage="routing", pair_id=pair_id,
        configuration_id=None, tag="m6_routing_execute",
        fn=lambda: _service(settings).execute(pair_id, req.run_id),
    )


# ---------------------------------------------------------------------------
# run read surface
# ---------------------------------------------------------------------------

@routing_router.get("/runs/{run_id}")
def routing_run_detail(run_id: str, settings: Settings = Depends(get_settings)) -> dict:
    payload = _service(settings).read(run_id)
    if payload is None:
        raise NotFoundError(f"No M6 routing run with id {run_id}.")
    return payload