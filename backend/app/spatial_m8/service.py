"""M8 SPATIAL SELECTION — service (run, read, list, status, persistence).

Consumes one ACCEPTED M7 trust gate artifact (explicit run or the latest
ACCEPT run for the pair), recovers the trusted correspondence set by
deterministic re-verification, computes spatial bookkeeping evidence and the
balanced selection, and records a never-overwritten artifact under
``data/metadata/m8_spatial``.

The M7 verdict is never overridden: a non-ACCEPT trust run, an unrecoverable
matcher artifact, or a synthetic-derived matcher run over a REAL pair are all
recorded as BLOCKED, never re-decided.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import Settings, rfc3339_now
from ..errors import NotFoundError
from ..hardening import atomic_write_json
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..state import get_state
from . import states
from .config import SpatialSelectionConfig, load_spatial_selection_config
from .contract import assert_artifact_vocabulary_safe, license_text
from .engine import analyze_and_select
from .recovery import recover_trusted

logger = get_logger(__name__)

_SPATIAL_CHAIN = ("M2 -> M3/M4 (-> M6 adaptivity) -> M7 trust gate -> M8 spatial selection")


def _safe_run_id(run_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id or ""))


def _synthetic_like(record) -> bool:
    ids = f"{record.source_class_a} {record.source_class_b}"
    if "FIXTURE" in ids.upper() or "fixture" in ids:
        return True
    if record.data_source_gate != "PATH_A_REAL_DATA":
        return True
    return False


def _environment_snapshot() -> dict[str, Any]:
    import numpy  # noqa: PLC0415

    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "numpy_version": numpy.__version__,
        "rng": "NONE",
        "rng_seed_policy": "No random sampling; every step is fully deterministic.",
    }


def _configuration_dict(cfg: SpatialSelectionConfig) -> dict[str, Any]:
    return json.loads(json.dumps(dataclasses.asdict(cfg)))


def _decision_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def m8_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    evidence = payload.get("evidence") or {}
    analysis = evidence.get("analysis") or {}
    block_a = analysis.get("a") or {}
    block_b = analysis.get("b") or {}
    return {
        "run_id": payload.get("run_id"),
        "pair_id": payload.get("pair_id"),
        "created_at_utc": payload.get("created_at_utc"),
        "trust_run_id": payload.get("trust_run_id"),
        "matcher_run_id": payload.get("matcher_run_id"),
        "matcher_id": payload.get("matcher_id"),
        "state": decision.get("state"),
        "reason_codes": decision.get("reasons"),
        "block_code": decision.get("block_code"),
        "abstain_code": decision.get("abstain_code"),
        "explanation": decision.get("explanation"),
        "decision_hash": payload.get("decision_hash"),
        "trusted_count": evidence.get("trusted_count"),
        "selected_count": evidence.get("selected_count"),
        "excluded_count": evidence.get("excluded_count"),
        "source_coverage_ratio": block_a.get("coverage_ratio"),
        "target_coverage_ratio": block_b.get("coverage_ratio"),
        "synthetically_derived": payload.get("synthetically_derived"),
        "configuration_id": payload.get("configuration_id"),
        "experiment_id": payload.get("experiment_id"),
        "runtime_ms": payload.get("runtime_ms"),
        "tone": states.tone(decision.get("state")),
    }


class SpatialSelectionService:
    """Run, read, list and stat M8 spatial selection runs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_state().settings
        self.config: SpatialSelectionConfig = load_spatial_selection_config()
        self.metadata_root = (
            self.settings.data_root_path / Path(self.config.derived_rel)
        )
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def _new_run_id(self, pair_id: str) -> str:
        while True:
            run_id = f"m8s-{pair_id}-{uuid.uuid4().hex[:8]}"
            if not self.artifact_path(run_id).exists():
                return run_id

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            raise OSError(f"Refusing to overwrite existing M8 spatial artifact {path.name}")
        assert_artifact_vocabulary_safe(payload)
        atomic_write_json(path, payload)
        return path

    def read(self, run_id: str) -> dict[str, Any] | None:
        if not _safe_run_id(run_id):
            return None
        path = self.artifact_path(run_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def list_runs(self, pair_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.metadata_root.is_dir():
            return rows
        for p in sorted(self.metadata_root.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("pair_id") != pair_id:
                continue
            rows.append(m8_run_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------ artifact base
    def _base_artifact(self, record, run_id: str, created_at: str) -> dict[str, Any]:
        cfg = self.config
        return {
            "run_id": run_id,
            "m8_spatial_run_id": run_id,
            "pair_id": record.pair_id,
            "experiment_id": None,
            "created_at_utc": created_at,
            "trust_run_id": None,
            "matcher_run_id": None,
            "matcher_id": None,
            "source_gate": {
                "data_source_gate": record.data_source_gate,
                "source_class_a": record.source_class_a,
                "source_class_b": record.source_class_b,
            },
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
            "data_source_gate": record.data_source_gate,
            "synthetically_derived": bool(_synthetic_like(record)),
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "configuration": _configuration_dict(cfg),
            "reference_status": cfg.reference_status,
            "decision": {
                "state": states.BLOCKED, "reasons": [],
                "explanation": "Pre-flight spatial gates not satisfied.",
                "block_code": None, "abstain_code": None,
            },
            "evidence": {},
            "recovery": None,
            "runtime_ms": None,
            "warnings": [],
            "errors": [],
            "environment": _environment_snapshot(),
        }

    # ------------------------------------------------ resolution
    def _resolve_trust_artifact(
        self, pair_id: str, trust_run_id: str | None
    ) -> dict[str, Any] | None:
        from ..trust_gate.service import TrustGateService

        trust = TrustGateService(self.settings)
        if trust_run_id:
            artifact = trust.read(trust_run_id)
            if artifact is None:
                raise NotFoundError(f"No M7 trust gate run with id {trust_run_id}.")
            if artifact.get("pair_id") != pair_id:
                raise NotFoundError(
                    f"M7 trust run {trust_run_id} belongs to a different pair."
                )
            return artifact

        # Latest ACCEPT run for the pair, else the newest run regardless of state
        # (so a non-ACCEPT is recorded honestly as TRUST_NOT_ACCEPTED).
        latest = trust.latest_for_pair(pair_id)
        if latest is None or not latest.get("run_id"):
            return None
        for row in trust.list_runs(pair_id):
            if row.get("state") == states.ACCEPT:
                art = trust.read(str(row["run_id"]))
                if art is not None:
                    return art
        return trust.read(str(latest["run_id"]))

    def _load_matcher(self, trust_artifact: dict[str, Any], pair_id: str) -> dict[str, Any] | None:
        from ..matching.deep.service import DeepMatcherService

        matcher_run_id = trust_artifact.get("matcher_run_id")
        if not matcher_run_id:
            return None
        payload = DeepMatcherService(self.settings).read_any(matcher_run_id)
        if payload is None:
            return None
        if payload.get("pair_id") not in (None, pair_id):
            return None
        return payload

    # ------------------------------------------------ run
    def run(self, pair_id: str, trust_run_id: str | None = None) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        cfg = self.config
        run_id = self._new_run_id(pair_id)
        created_at = rfc3339_now()
        base = self._base_artifact(record, run_id, created_at)
        budget_ms = int(cfg.execution.max_runtime_seconds) * 1000
        t0 = time.monotonic()

        try:
            trust_artifact = self._resolve_trust_artifact(pair_id, trust_run_id)
            if trust_artifact is None:
                self._apply_blocked(base, states.NO_TRUST_RUN,
                                    "No M7 trust gate run exists for this pair; the M8 "
                                    "spatial selection refuses to guess a trusted set.")
            else:
                self._run_with_trust(record, base, trust_artifact)
        except NotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("M8 spatial selection failed for %s", pair_id)
            base["decision"] = {
                "state": states.FAILED, "reasons": [str(type(exc).__name__)],
                "explanation": f"M8 spatial selection failed: {exc}",
                "block_code": None, "abstain_code": None,
            }
            base["errors"] = [str(exc)]

        elapsed_ms = int(round((time.monotonic() - t0) * 1000))
        base["runtime_ms"] = elapsed_ms
        if elapsed_ms > budget_ms and base["decision"]["state"] in (
            states.SELECTED, states.SELECTED_WITH_WARNINGS, states.ABSTAIN,
        ):
            base["decision"] = {
                "state": states.ABSTAIN, "reasons": [states.RESOURCE_LIMIT],
                "explanation": (
                    f"Wall-clock budget {budget_ms} ms exceeded ({elapsed_ms} ms); "
                    "declared RESOURCE_LIMIT. The under-budget result was discarded."
                ),
                "block_code": None, "abstain_code": states.RESOURCE_LIMIT,
            }
            base["warnings"] = base.get("warnings", []) + [
                "Runtime exceeded the declared max_runtime_seconds; result "
                "overridden to ABSTAIN/RESOURCE_LIMIT."
            ]

        base["decision_hash"] = _decision_hash(base["decision"])
        base["provenance"] = {
            "chain": _SPATIAL_CHAIN,
            "m7_run": base.get("trust_run_id"),
            "m3_or_m4_run": base.get("matcher_run_id"),
            "m8_run": run_id,
        }
        base["license"] = license_text()

        path = self.write_artifact(run_id, base)
        logger.info("M8 spatial selection run recorded for %s -> %s [%s]",
                    pair_id, path.name, base["decision"]["state"])
        return base

    def _run_with_trust(self, record, base: dict[str, Any], trust_artifact: dict[str, Any]) -> None:
        decision = trust_artifact.get("decision") or {}
        if decision.get("state") != states.ACCEPT:
            self._apply_blocked(base, states.TRUST_NOT_ACCEPTED,
                                f"The resolved M7 trust run is {decision.get('state')!r}; "
                                "M8 never overrides a non-ACCEPT verdict.")
            base["trust_run_id"] = trust_artifact.get("trust_run_id") or trust_artifact.get("run_id")
            return

        if bool(trust_artifact.get("synthetically_derived", False)) and not _synthetic_like(record):
            self._apply_blocked(base, states.REAL_DATA_BLOCKED,
                                "This pair is REAL data but the resolved M7 trust run is "
                                "synthetically derived; a spatial selection would be "
                                "misleading and is refused.")
            base["trust_run_id"] = trust_artifact.get("trust_run_id") or trust_artifact.get("run_id")
            return

        matcher = self._load_matcher(trust_artifact, record.pair_id)
        if matcher is None:
            self._apply_blocked(base, states.MATCH_RUN_UNRECOVERABLE,
                                "The referenced matcher run artifact is unavailable or "
                                "belongs to a different pair; the trusted set cannot be "
                                "recovered.")
            base["trust_run_id"] = trust_artifact.get("trust_run_id") or trust_artifact.get("run_id")
            return

        recovery = recover_trusted(trust_artifact, matcher)
        base["trust_run_id"] = trust_artifact.get("trust_run_id") or trust_artifact.get("run_id")
        base["matcher_run_id"] = trust_artifact.get("matcher_run_id")
        base["matcher_id"] = trust_artifact.get("matcher_id")
        base["synthetically_derived"] = bool(trust_artifact.get("synthetically_derived", False))
        base["experiment_id"] = (
            f"EXP-M8-{trust_artifact.get('trust_run_id') or trust_artifact.get('run_id')}-"
            f"{str(base.get('matcher_id') or 'MATCHER')}-{self.config.configuration_id}"
        )

        if recovery["state"] != states.RECOVERY_OK:
            base["decision"] = recovery["decision"]
            base["errors"] = [recovery["decision"]["explanation"]]
            base["warnings"] = []
            base["recovery"] = {
                "method": "deterministic_re_verification_M7",
                "state": recovery["state"],
            }
            return

        result = analyze_and_select(recovery["trusted"], recovery["dims_a"],
                                    recovery["dims_b"], self.config)
        base.update({
            "decision": result["decision"],
            "evidence": result["evidence"],
            "warnings": result["warnings"],
            "recovery": {
                "method": "deterministic_re_verification_M7",
                "state": states.RECOVERY_OK,
                "trusted_chain": recovery.get("trusted_chain"),
                "recovered_decision_hash": recovery.get("recovered_decision_hash"),
                "recovered_trusted_count": len(recovery["trusted"]),
                "frame": result["evidence"].get("frame"),
            },
        })

    # ------------------------------------------------ helpers
    def _apply_blocked(self, base: dict[str, Any], code: str, explanation: str) -> None:
        base["decision"] = {
            "state": states.BLOCKED, "reasons": [code],
            "explanation": explanation,
            "block_code": code, "abstain_code": None,
        }
        base["errors"] = [explanation]

    # ------------------------------------------------ status
    def status(self, pair_id: str) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")
        cfg = self.config
        return {
            "pair_id": pair_id,
            "data_source_gate": record.data_source_gate,
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
            "synthetically_derived": bool(_synthetic_like(record)),
            "configured": {
                "configuration_id": cfg.configuration_id,
                "configuration_version": cfg.configuration_version,
                "scientifically_tuned": cfg.scientifically_tuned,
                "reference_status": cfg.reference_status,
                "policy": cfg.selection.policy,
                "grid_rows": cfg.grid.rows,
                "grid_cols": cfg.grid.cols,
                "max_selected": cfg.selection.max_selected,
                "min_trusted": cfg.selection.min_trusted,
                "min_selected": cfg.selection.min_selected,
                "min_per_occupied_cell": cfg.selection.min_per_occupied_cell,
                "min_occupied_cells": cfg.selection.min_occupied_cells,
                "tie_break": cfg.selection.tie_break,
                "max_runtime_seconds": cfg.execution.max_runtime_seconds,
            },
            "latest_run": self.latest_for_pair(pair_id),
        }


__all__ = [
    "SpatialSelectionService",
    "m8_run_summary",
]