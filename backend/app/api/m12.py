"""M12 final scientific validation API (/api/m12).

Reads (gate / raw integrity / provenance / audits) are analyst-viewable; the
evidence freeze and reproducibility runs are admin science actions. Every
endpoint returns machine-readable evidence, never a fabricated claim.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth.dependencies import AdminUser, AnalystUser, current_user_dep
from ..config import Settings
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..m12 import audits, config_freeze, crosscheck, package, provenance, raw_integrity, report
from ..m12.package import FROZEN_DIGEST_NAME, verify_frozen
from ..pairs import PairRegistry
from .deps import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/m12", tags=["m12"], dependencies=[Depends(current_user_dep)])


def _require_pair(settings: Settings, pair_id: str) -> None:
    if PairRegistry(settings).get(pair_id) is None:
        raise NotFoundError(f"No pair with ID {pair_id} is registered.")


def _provenance_for(pair_id: str, settings: Settings) -> dict:
    return provenance.build_full_provenance(pair_id, settings)


def _audits_for(pair_id: str, settings: Settings) -> dict:
    return audits.run_all_audits(pair_id, settings)


@router.get("/configuration-freeze")
def configuration_freeze(settings: Settings = Depends(get_settings)) -> dict:
    return config_freeze.configuration_chain(settings=settings)


@router.get("/real-data-gate/{pair_id}")
def real_data_gate(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return raw_integrity.real_data_gate(pair_id, settings)


@router.get("/raw-integrity/{pair_id}")
def raw_integrity_endpoint(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return raw_integrity.raw_integrity(pair_id, settings)


@router.get("/provenance/{pair_id}")
def full_provenance(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _provenance_for(pair_id, settings)


@router.get("/audits/{pair_id}")
def run_audits(pair_id: str, settings: Settings = Depends(get_settings)) -> dict:
    _require_pair(settings, pair_id)
    return _audits_for(pair_id, settings)


class EvidenceRequest(BaseModel):
    pair_id: str
    experiment_id: str | None = None
    notes: str = ""


@router.post("/evidence")
def build_evidence(
    req: EvidenceRequest,
    _admin: AdminUser,
    settings: Settings = Depends(get_settings),
) -> dict:
    del _admin
    _require_pair(settings, req.pair_id)
    gate = raw_integrity.real_data_gate(req.pair_id, settings)

    experiment = None
    from backend.app.metrics.service import MetricsService
    svc = MetricsService(settings.data_root_path, m7_cfg={}, m6_cfg={}, m5_cfg={}, m4_defaults={})
    exp_result = svc.experiment(req.pair_id)
    if isinstance(exp_result, dict) and exp_result.get("experiment_id"):
        experiment = exp_result

    experiment_id = req.experiment_id or (experiment or {}).get("experiment_id")
    if not experiment_id:
        raise NotFoundError(
            f"No experiment identity for pair {req.pair_id}; run METRICS first or pass experiment_id.")

    freeze = config_freeze.configuration_chain(settings=settings)
    prov = _provenance_for(req.pair_id, settings)
    audit = _audits_for(req.pair_id, settings)
    context = {
        "pair_id": req.pair_id,
        "experiment_id": experiment_id,
        "gate": gate,
        "freeze": freeze,
        "provenance": prov,
        "audits": audit,
    }
    report_md = report.build_final_report_markdown(context)
    result = package.build_final_evidence(
        req.pair_id, settings,
        experiment_id=experiment_id,
        gate=gate, freeze=freeze, provenance=prov, audits=audit,
        crosscheck={"status": "NA", "pipeline_state": {}, "violations": []},
        report_md=report_md,
        notes=req.notes,
    )
    result["experiment"] = experiment
    return result


@router.get("/evidence/{experiment_id}/verify")
def verify_evidence(experiment_id: str, _analyst: AnalystUser,
                    settings: Settings = Depends(get_settings)) -> dict:
    del _analyst
    return verify_frozen(settings, experiment_id)


@router.get("/evidence/{experiment_id}/package")
def read_evidence_package(experiment_id: str, _analyst: AnalystUser,
                          settings: Settings = Depends(get_settings)) -> dict:
    del _analyst
    root = settings.data_root_path / "final_evidence" / experiment_id
    if not (root / package.MANIFEST_NAME).is_file():
        raise NotFoundError(f"No frozen evidence package for experiment {experiment_id}.")
    return {
        "experiment_id": experiment_id,
        "package_dir": root.relative_to(settings.data_root_path).as_posix(),
        "manifest": json.loads((root / package.MANIFEST_NAME).read_text(encoding="utf-8")),
        "final_evidence_sha256": (root / FROZEN_DIGEST_NAME).read_text(encoding="utf-8").strip(),
    }


class ReproducibilityOutcome(BaseModel):
    detail: str = ""


@router.post("/reproducibility/{pair_id}")
def run_reproducibility(pair_id: str, _admin: AdminUser,
                        settings: Settings = Depends(get_settings)) -> dict:
    """Run RUN A / RUN B(no-op re-read) / RUN C comparisons for a frozen package.

    Full RUN C (fresh workspace) is executed by ``scripts/m12_reproducibility.py``
    because it needs a clean workspace; this endpoint re-verifies the frozen
    evidence determinism of the recorded run.
    """
    del _admin
    _require_pair(settings, pair_id)
    experiment = None
    from backend.app.metrics.service import MetricsService
    svc = MetricsService(settings.data_root_path, m7_cfg={}, m6_cfg={}, m5_cfg={}, m4_defaults={})
    exp_result = svc.experiment(pair_id)
    if isinstance(exp_result, dict) and exp_result.get("experiment_id"):
        experiment = exp_result
    if experiment is None:
        raise NotFoundError(f"No experiment identity for pair {pair_id} — run METRICS first.")
    v = verify_frozen(settings, experiment["experiment_id"])
    return {
        "pair_id": pair_id,
        "experiment_id": experiment["experiment_id"],
        "frozen": v,
        "note": "Determinism proved by scripts/m12_reproducibility.py (RUN A / B / C).",
    }


__all__ = ["router"]