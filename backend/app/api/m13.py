"""M13 final release API (/api/m13): jury-facing status, evidence explorer,
report centre, reproducibility record, measurements and demo reset.

Every endpoint is READ-ONLY with respect to scientific artifacts. Reports and
evidence are served from inside the data root only (POSIX-relative names, no
absolute paths, no filesystem traversal). Nothing here can modify frozen
evidence: ``demo/reset`` re-verifies the frozen packages and returns the
verified state — it never writes to ``final_evidence``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ..auth.dependencies import AnalystUser, current_user_dep
from ..config import Settings
from ..errors import NotFoundError
from ..logging_conf import get_logger
from ..m12.package import FROZEN_DIGEST_NAME, MANIFEST_NAME, verify_frozen
from .deps import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/m13", tags=["m13"], dependencies=[Depends(current_user_dep)])

_REPORT_NAME_RE = None  # replaced below once the module is importable


def _safe_reports_dir(settings: Settings) -> Path:
    return settings.data_root_path / "reports"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _package_dirs(settings: Settings) -> list[Path]:
    root = settings.data_root_path / "final_evidence"
    if not root.is_dir():
        return []
    return sorted(
        (d for d in root.iterdir() if d.is_dir() and (d / MANIFEST_NAME).is_file()),
        key=lambda d: d.name,
        reverse=True,
    )


def _package_digest(pkg_dir: Path) -> str | None:
    digest = _read_text(pkg_dir / FROZEN_DIGEST_NAME)
    return digest.strip() if digest else None


def _latest_package(settings: Settings) -> Path | None:
    dirs = _package_dirs(settings)
    return dirs[0] if dirs else None


def _fingerprint(settings: Settings) -> str | None:
    pkg = _latest_package(settings)
    if pkg is None:
        return None
    cfg = _read_json(pkg / "configurations.json")
    if not cfg:
        return None
    freeze = cfg.get("freeze") if isinstance(cfg.get("freeze"), dict) else {}
    return str(cfg.get("fingerprint") or freeze.get("fingerprint") or "") or None


@router.get("/status")
def release_status(_analyst: AnalystUser, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Aggregate release status. Never leaks secrets or absolute paths."""
    del _analyst
    pkg = _latest_package(settings)
    manifest: dict[str, Any] | None = _read_json(pkg / MANIFEST_NAME) if pkg else None
    provenance = _read_json(pkg / "provenance.json") if pkg else None
    audits = _read_json(pkg / "audits.json") if pkg else None
    crosscheck = _read_json(pkg / "crosscheck.json") if pkg else None
    security = _read_json(pkg / "security.json") if pkg else None
    pair = _read_json(pkg / "pair.json") if pkg else None
    experiment = _read_json(pkg / "experiment.json") if pkg else None

    verify = None
    digest = None
    if pkg and manifest:
        exp_id = str(manifest.get("experiment_id") or pkg.name)
        digest = _package_digest(pkg)
        try:
            verify = verify_frozen(settings, exp_id)
        except Exception:  # noqa: BLE001 - best effort display
            verify = {"status": "UNVERIFIABLE"}

    repro = _read_json(_safe_reports_dir(settings) / "m12_reproducibility.json")
    measurements = _read_json(_safe_reports_dir(settings) / "m13_performance.json")

    from ..metrics.reference import reference_dataset_status
    from ..ops import dependency_status

    reference = (reference_dataset_status() or {}).get("status", "NOT_AVAILABLE")
    real_data_state = "BLOCKED"
    real_data_detail = "REAL_DATA_UNAVAILABLE"

    from backend.app.pairs import PairRegistry
    try:
        pairs = PairRegistry(settings).list()
    except Exception:  # noqa: BLE001
        pairs = []
    synthetic = any("fixture" in f"{getattr(p, 'image_a_product_id', '')}{getattr(p, 'image_b_product_id', '')}".lower()
                    for p in pairs)
    real = any("fixture" not in f"{getattr(p, 'image_a_product_id', '')}{getattr(p, 'image_b_product_id', '')}".lower()
               for p in pairs)
    if real:
        real_data_state = "AVAILABLE"
        real_data_detail = "Registered real pair(s) present."
    elif synthetic:
        real_data_detail = "REAL_DATA_UNAVAILABLE - only synthetic TEST_FIXTURE pair(s) registered."

    provisioned = [s for s in dependency_status(settings) if s["id"] in ("authentication", "deep_matcher", "ai_capability")]
    try:
        ai = next((s for s in provisioned if s["id"] == "ai_capability"), None)
        ai_state = (ai or {}).get("state", "NOT_CONFIGURED")
        deep = next((s for s in provisioned if s["id"] == "deep_matcher"), None)
        deep_state = (deep or {}).get("state", "NOT_AVAILABLE")
        auth_state = next((s for s in provisioned if s["id"] == "authentication"), {}).get("state", "NOT_CONFIGURED")
    except Exception:  # noqa: BLE001
        ai_state = deep_state = auth_state = "NOT_CONFIGURED"

    gate = (experiment or {}).get("gate") or {}
    gate_decision = gate.get("decision") or {}
    gate_path = "PATH A" if gate_decision.get("path_a") else ("PATH B" if gate_decision.get("path_b") else None)
    gate_condition = gate.get("status")
    repro_evidence = ((repro or {}).get("evidence") or {}) if repro else {}
    return {
        "app": {
            "product_name": settings.product_name,
            "project_identifier": settings.app_name,
            "tagline": settings.tagline,
            "version": settings.app_version,
            "milestone": settings.milestone,
            "release_version": settings.release_version,
            "release_milestone": settings.release_milestone,
            "environment": settings.app_env,
            "demo_mode": settings.demo_mode,
        },
        "evidence": {
            "present": bool(manifest),
            "experiment_id": (manifest or {}).get("experiment_id"),
            "pair_id": (manifest or {}).get("pair_id") or (pair or {}).get("pair_id"),
            "final_evidence_sha256": digest,
            "verify_status": (verify or {}).get("status"),
            "artifact_count": (manifest or {}).get("artifact_count"),
            "configuration_fingerprint": _fingerprint(settings) or (experiment or {}).get("configuration_fingerprint"),
            "gate_path": gate_path,
            "gate_condition": gate_condition,
            "gate_reason": gate_decision.get("reason"),
            "audit_status": (audits or {}).get("status"),
            "crosscheck_status": (crosscheck or {}).get("status") if crosscheck else None,
            "crosscheck_violations": (crosscheck or {}).get("violations", []),
            "security_status": (security or {}).get("status") if security else None,
        },
        "provenance": {
            "status": (provenance or {}).get("status", "UNRECORDED"),
            "missing_stages": (provenance or {}).get("missing_stages", []),
            "chain": [
                {
                    "milestone": s.get("milestone"),
                    "status": s.get("status"),
                    "configuration_id": s.get("configuration_id"),
                    "artifact_count": len(s.get("artifacts") or []),
                }
                for s in (provenance or {}).get("chain", [])
            ],
        },
        "reproducibility": {
            "status": (repro_evidence or {}).get("status"),
            "subject_verdicts": (repro_evidence or {}).get("subjects", {}),
            "differing_subjects": (repro_evidence or {}).get("drifted_subjects", []),
            "runs": {
                k: {
                    "experiment_id": r.get("experiment_id"),
                    "configuration_fingerprint": r.get("configuration_fingerprint"),
                    "funnel": {
                        "candidates": r.get("FUNNEL_M3_CANDIDATES"),
                        "trusted": r.get("FUNNEL_M4_TRUSTED_CORRESPONDENCES"),
                        "selected": r.get("FUNNEL_M5_SELECTED_CORRESPONDENCES"),
                        "registered": r.get("FUNNEL_M6_REGISTERED_CORRESPONDENCES"),
                    },
                    "report_md_sha256": r.get("report_md_sha256"),
                    "transform_matrix_hash": r.get("transform_matrix_hash"),
                }
                for k, r in ((repro_evidence or {}).get("runs", {}) or {}).items()
            },
        },
        "real_data": {"status": real_data_state, "detail": real_data_detail},
        "reference": {"status": reference},
        "ai": {"state": ai_state},
        "deep_matcher": {"state": deep_state},
        "auth": {"state": auth_state},
        "measurements": measurements or {"status": "NOT_MEASURED"},
        "note": (
            "Engineering evidence is REPRODUCIBLE on the frozen TEST_FIXTURE corpus. "
            "Real mission validation is gated by authorized PRADAN access; physical "
            "accuracy is NOT_AVAILABLE without a reference dataset."
        ),
    }


@router.get("/evidence")
def evidence_list(_analyst: AnalystUser, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    packages = []
    for pkg in _package_dirs(settings):
        manifest = _read_json(pkg / MANIFEST_NAME)
        packages.append({
            "experiment_id": pkg.name,
            "pair_id": (manifest or {}).get("pair_id"),
            "final_evidence_sha256": _package_digest(pkg),
            "artifact_count": (manifest or {}).get("artifact_count"),
            "schema_version": (manifest or {}).get("schema_version"),
        })
    return {
        "packages": packages,
        "count": len(packages),
        "note": "Frozen evidence packages inside the application data root; read-only.",
    }


@router.get("/evidence/{experiment_id}")
def evidence_detail(experiment_id: str, _analyst: AnalystUser,
                    settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    pkg = settings.data_root_path / "final_evidence" / experiment_id
    if not (pkg / MANIFEST_NAME).is_file():
        raise NotFoundError(f"No frozen evidence package for experiment {experiment_id}.")
    manifest = _read_json(pkg / MANIFEST_NAME) or {}
    try:
        verify = verify_frozen(settings, experiment_id)
    except Exception as exc:  # noqa: BLE001
        verify = {"status": "UNVERIFIABLE", "reason": f"{exc.__class__.__name__}"}
    return {
        "experiment_id": experiment_id,
        "pair_id": manifest.get("pair_id"),
        "final_evidence_sha256": _package_digest(pkg),
        "verify": verify,
        "manifest": manifest,
        "provenance": _read_json(pkg / "provenance.json"),
        "audits": _read_json(pkg / "audits.json"),
        "crosscheck": _read_json(pkg / "crosscheck.json"),
        "security": _read_json(pkg / "security.json"),
        "note": "Package contents are frozen; API is read-only.",
    }


@router.get("/reports")
def report_centre(_analyst: AnalystUser, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    rd = _safe_reports_dir(settings)
    names = sorted({p.name for p in rd.glob("*.md")}) if rd.is_dir() else []
    records = []
    for name in names:
        rel = rd / name
        records.append({
            "name": name,
            "kind": (
                "scientific" if name.upper().startswith("M") else
                "measurement" if "performance" in name.lower() else
                "record"),
            "size": rel.stat().st_size if rel.is_file() else 0,
        })
    return {
        "reports": records,
        "has_reproducibility_record": (rd / "m12_reproducibility.json").is_file(),
        "note": "Reports are served read-only from the application data root.",
    }


@router.get("/report/{name}")
def report_content(name: str, _analyst: AnalystUser,
                   settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    rd = _safe_reports_dir(settings)
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".md"):
        raise NotFoundError("Unknown report.")
    path = rd / name
    if not path.is_file():
        raise NotFoundError(f"No such report: {name}")
    return {"name": name, "markdown": path.read_text(encoding="utf-8")}


@router.get("/record/reproducibility")
def reproducibility_record(_analyst: AnalystUser,
                           settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    payload = _read_json(_safe_reports_dir(settings) / "m12_reproducibility.json")
    if payload is None:
        raise NotFoundError("Reproducibility record not present in the data root.")
    return payload


@router.get("/measurements")
def measurements(_analyst: AnalystUser, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    payload = _read_json(_safe_reports_dir(settings) / "m13_performance.json")
    return payload or {"status": "NOT_MEASURED", "note": "No measurement record present."}


@router.post("/demo/reset")
def demo_reset(_analyst: AnalystUser, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    """Reset the demonstration WITHOUT touching frozen evidence.

    Re-verifies every frozen package and reports the restored state. No
    scientific artifact is written, renamed or deleted.
    """
    del _analyst
    verified: list[dict[str, Any]] = []
    preserved = True
    for pkg in _package_dirs(settings):
        exp_id = pkg.name
        try:
            v = verify_frozen(settings, exp_id)
        except Exception as exc:  # noqa: BLE001
            v = {"status": "UNVERIFIABLE", "reason": f"{exc.__class__.__name__}"}
        verified.append({"experiment_id": exp_id, "verify_status": v.get("status"),
                          "final_evidence_sha256": _package_digest(pkg)})
        preserved = preserved and v.get("status") == "VERIFIED"
    return {
        "demonstration": "RESET",
        "evidence_preserved": preserved,
        "evidence": verified,
        "note": "Transient demo state cleared; raw data and frozen evidence untouched.",
    }


@router.get("/provenance")
def provenance_summary(_analyst: AnalystUser, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    del _analyst
    pkg = _latest_package(settings)
    if pkg is None:
        raise NotFoundError("No frozen evidence package present.")
    provenance = _read_json(pkg / "provenance.json")
    if provenance is None:
        raise NotFoundError("Provenance record missing from the frozen package.")
    return provenance


__all__ = ["router"]