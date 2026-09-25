"""M10 METRICS & BENCHMARK API.

Endpoints mounted by ``api/router.py`` under ``/metrics-m10``:

    GET  /api/metrics-m10/overview              (read)
    GET  /api/metrics-m10/variants              (read)
    GET  /api/metrics-m10/pairs/{pair_id}/prerequisites (read)
    POST /api/metrics-m10/runs                  (analyst)  {pair_id, variant_id}
    GET  /api/metrics-m10/runs                  (read)
    GET  /api/metrics-m10/runs/{run_id}         (read)
    GET  /api/metrics-m10/pairs/{pair_id}/latest (read)
    GET  /api/metrics-m10/analyze               (read)
    GET  /api/metrics-m10/deltas                (read)
    GET  /api/metrics-m10/failure-analysis      (read)

Every response carries ``reference_status`` and ``no_claim: true``; the
controller never emits accuracy/geolocation/winner vocabulary.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.dependencies import AnalystUser, current_user_dep
from ..errors import NotFoundError
from .deps import get_settings
from ..config import Settings

router = APIRouter(prefix="/metrics-m10", tags=["metrics-m10"],
                   dependencies=[Depends(current_user_dep)])


def _service(settings: Settings):
    from ..metrics_m10.service import M10MetricsService
    return M10MetricsService(settings)


class BenchmarkRunRequest(BaseModel):
    pair_id: str
    variant_id: str = "V4"


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return _service(settings).overview()


@router.get("/variants")
def variants(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    svc = _service(settings)
    return {"variants": svc.variants(), "no_claim": True}


@router.get("/pairs/{pair_id}/prerequisites")
def prerequisites(pair_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return _service(settings).prerequisites(pair_id)


@router.post("/runs")
def create_run(body: BenchmarkRunRequest, _analyst: AnalystUser,
               settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    try:
        return _service(settings).run(body.pair_id, body.variant_id)
    except ValueError as exc:
        from ..errors import ValidationError
        raise ValidationError(str(exc))


@router.get("/runs")
def list_runs(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    svc = _service(settings)
    return {"runs": svc.list(), "no_claim": True}


@router.get("/runs/{run_id}")
def get_run(run_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    rec = _service(settings).read(run_id)
    if not rec:
        raise NotFoundError("benchmark run %s not found" % run_id)
    return rec


@router.get("/pairs/{pair_id}/latest")
def pair_latest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    rec = _service(settings).latest(pair_id)
    if not rec:
        raise NotFoundError("no benchmark run for pair %s" % pair_id)
    return rec


@router.get("/analyze")
def analyze(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return _service(settings).analyze()


@router.get("/deltas")
def deltas(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return _service(settings).deltas()


@router.get("/failure-analysis")
def failure_analysis(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return _service(settings).failure_analysis()