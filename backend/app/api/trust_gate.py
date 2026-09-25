"""M7 Trust Gate API.

Endpoints mounted by ``api/router.py``:

    GET  /api/pairs/{pair_id}/trust/status         (read)
    GET  /api/pairs/{pair_id}/trust/runs           (read)
    POST /api/pairs/{pair_id}/trust/run            (writes one trust artifact)
    GET  /api/trust/runs/{run_id}                  (read)

The M7 gate consumes an existing M3/M4 matcher run artifact (optionally the
run the M6 router dispatched) and records a deterministic ACCEPT / REJECT /
ABSTAIN / BLOCKED verdict plus evidence. It never writes into M3/M4/M6
artifacts, never invokes M8 spatial selection or M9 registration, and never
emits ``confidence`` vocabulary.
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

pair_router = APIRouter(prefix="/pairs", tags=["trust-gate"],
                        dependencies=[Depends(current_user_dep)])
trust_router = APIRouter(prefix="/trust", tags=["trust-gate"],
                         dependencies=[Depends(current_user_dep)])


class TrustRunRequest(BaseModel):
    matcher_run_id: str | None = None
    routing_run_id: str | None = None


def _service(settings: Settings):
    from ..trust_gate.service import TrustGateService

    return TrustGateService(settings)


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


# ---------------------------------------------------------------------------
# pair-scoped trust gate
# ---------------------------------------------------------------------------

@pair_router.get("/{pair_id}/trust/status")
def trust_pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _service(settings).status(pair_id)


@pair_router.get("/{pair_id}/trust/runs")
def trust_pair_runs(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return {"pair_id": pair_id, "runs": _service(settings).list_runs(pair_id)}


@pair_router.post("/{pair_id}/trust/run")
def trust_run(pair_id: str, req: TrustRunRequest,
              current: AnalystUser, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    service = _service(settings)
    return guard_run(
        settings, derived_stage="trust-gate", pair_id=pair_id,
        configuration_id=service.config.configuration_id,
        tag="m7_trust_gate",
        fn=lambda: service.run(
            pair_id,
            matcher_run_id=req.matcher_run_id,
            routing_run_id=req.routing_run_id,
        ),
    )


# ---------------------------------------------------------------------------
# run read surface
# ---------------------------------------------------------------------------

@trust_router.get("/runs/{run_id}")
def trust_run_detail(run_id: str, settings: Settings = Depends(get_settings)) -> dict:
    payload = _service(settings).read(run_id)
    if payload is None:
        raise NotFoundError(f"No M7 trust gate run with id {run_id}.")
    return payload