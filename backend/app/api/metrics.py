"""M7 metrics API (/api/metrics).

Reproducible measurement layer over M2..M6. Metrics are measurements of
pipeline evidence, never scientific alignment accuracy claims.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..config import Settings, m4_config, m5_config, m6_config, m7_config
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..metrics.service import MetricsService
from ..pairs import PairRegistry
from .deps import get_settings
from ..auth.dependencies import AnalystUser, current_user_dep

logger = get_logger(__name__)
router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(current_user_dep)])

VALID_METRICS_CONFIG_IDS = {"MT-M7-001"}


def _service(settings: Settings) -> MetricsService:
    return MetricsService(
        settings.data_root_path,
        m7_cfg=m7_config(),
        m6_cfg=m6_config(),
        m5_cfg=m5_config(),
        m4_defaults=(m4_config().get("defaults") or {}),
    )


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


@router.get("/configurations")
def list_configurations() -> dict:
    cfg = m7_config()
    return {
        "configurations": [
            {
                "metrics_configuration_id": cfg.get("metrics_configuration_id", "MT-M7-001"),
                "metrics_configuration_version": cfg.get("metrics_configuration_version", 1),
                "name": cfg.get("name", "Quantitative Metrics, Reproducible Experiment Reports & Scientific Diagnostics"),
                "scientifically_tuned": bool(cfg.get("scientifically_tuned", False)),
                "defaults": cfg.get("defaults", {}),
            },
        ],
        "default_metrics_configuration_id": "MT-M7-001",
        "valid_metrics_configuration_ids": sorted(VALID_METRICS_CONFIG_IDS),
        "note": "Engineering defaults only; no scientifically tuned thresholds exist yet.",
    }


@router.get("/overview")
def overview(settings: Settings = Depends(get_settings)) -> dict:
    service = _service(settings)
    root = service._metrics_root()
    pairs_total = 0
    pairs_complete = 0
    pairs_not_complete = 0
    if root.is_dir():
        for pair_dir in root.iterdir():
            if not pair_dir.is_dir():
                continue
            pairs_total += 1
            run = service.find_run_for_pair(pair_dir.name)
            status_path = run / "status.json" if run is not None else None
            state = None
            if status_path is not None and status_path.is_file():
                try:
                    state = json.loads(status_path.read_text(encoding="utf-8")).get("state")
                except (OSError, json.JSONDecodeError):
                    state = None
            if state == "COMPLETE":
                pairs_complete += 1
            else:
                pairs_not_complete += 1
    return {
        "total_metrics_pairs": pairs_total,
        "complete_pairs": pairs_complete,
        "not_complete_pairs": pairs_not_complete,
        "note": "Metrics summary (M7); measurements, not scientific accuracy.",
    }


class RunRequest(BaseModel):
    metrics_configuration_id: str | None = None


@router.get("/comparison")
def comparison(
    pair_a: str = Query(...),
    pair_b: str = Query(...),
    settings: Settings = Depends(get_settings),
) -> dict:
    _require_pair(settings, pair_a)
    _require_pair(settings, pair_b)
    service = _service(settings)
    return service.comparison(pair_a, pair_b)


@router.get("/{pair_id}/status")
def pair_status(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _service(settings).read_status(pair_id)


@router.post("/{pair_id}/run")
def run_metrics(pair_id: str, current: AnalystUser, req: RunRequest, settings: Settings = Depends(get_settings)) -> dict:
    del current
    _require_pair(settings, pair_id)
    config_id = req.metrics_configuration_id or "MT-M7-001"
    if config_id not in VALID_METRICS_CONFIG_IDS:
        raise NotFoundError(f"Unknown metrics configuration: {config_id}")
    return _service(settings).run(pair_id, metrics_config_id=config_id)


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
        "note": "Only derived metrics artifacts were removed. M6/M5/M4/M3/M2/raw data untouched.",
    }


@router.get("/{pair_id}/summary")
def pair_summary(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    result = _service(settings).summary(pair_id)
    if "error" in result:
        raise NotFoundError(f"No metrics summary for pair {pair_id} — run METRICS first.")
    return {"pair_id": pair_id, "summary": result}


@router.get("/{pair_id}/metrics")
def pair_metrics(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    records = _service(settings).metrics(pair_id)
    return {"pair_id": pair_id, "metrics": records, "count": len(records)}


@router.get("/{pair_id}/metrics/{metric_id}")
def pair_metric(pair_id: str, metric_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    result = _service(settings).metric_by_id(pair_id, metric_id)
    if "error" in result:
        raise NotFoundError(f"No metric '{metric_id}' for pair {pair_id}.")
    return {"pair_id": pair_id, "metric": result}


@router.get("/{pair_id}/experiment")
def pair_experiment(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    result = _service(settings).experiment(pair_id)
    if "error" in result:
        raise NotFoundError(f"No experiment identity for pair {pair_id} — run METRICS first.")
    return {"pair_id": pair_id, "experiment": result}


@router.get("/{pair_id}/report")
def pair_report(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    result = _service(settings).report_json(pair_id)
    if "error" in result:
        raise NotFoundError(f"No metrics report for pair {pair_id} — run METRICS first.")
    return {"pair_id": pair_id, "report": result}


@router.get("/{pair_id}/report/markdown")
def pair_report_markdown(pair_id: str, settings: Settings = Depends(get_settings)) -> PlainTextResponse:
    _require_pair(settings, pair_id)
    try:
        md = _service(settings).report_markdown(pair_id)
    except FileNotFoundError as exc:
        raise NotFoundError(str(exc))
    return PlainTextResponse(md, media_type="text/markdown")


@router.get("/{pair_id}/provenance")
def pair_provenance(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    result = _service(settings).provenance(pair_id)
    if "error" in result:
        raise NotFoundError(f"No metrics provenance for pair {pair_id}.")
    return {"pair_id": pair_id, "provenance": result}


@router.get("/{pair_id}/manifest")
def pair_manifest(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    result = _service(settings).manifest(pair_id)
    if "error" in result:
        raise NotFoundError(f"No metrics manifest for pair {pair_id} — run METRICS first.")
    return {"pair_id": pair_id, "manifest": result}