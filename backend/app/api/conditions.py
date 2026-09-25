"""M5 condition-estimator run read API (/api/conditions).

A condition-estimator run is a pair-level, reproducible characterization of
M2 validated products (intrinsic per-side condition + pair comparison). This
router only READs produced artifacts; the run is triggered via
``/api/pairs/{pair_id}/conditions/run``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings
from ..errors import NotFoundError
from .deps import get_settings
from ..auth.dependencies import current_user_dep

router = APIRouter(prefix="/conditions", tags=["conditions"], dependencies=[Depends(current_user_dep)])


def _conditions_service(settings: Settings):
    from ..conditions.service import ConditionEstimationService

    return ConditionEstimationService(settings)


@router.get("/runs/{run_id}")
def condition_run(run_id: str, settings: Settings = Depends(get_settings)) -> dict:
    payload = _conditions_service(settings).read(run_id)
    if payload is None:
        raise NotFoundError(f"No M5 condition-estimator run with id {run_id}.")
    return payload