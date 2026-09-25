"""M6 adaptive matcher router — service (views, routing runs, dispatch).

Responsibilities:

    * assemble the canonical condition view from M2 processing status + the
      latest full M5 condition profile + the pair record;
    * assemble the live capability view from the M3 baseline and M4-DEEP
      probes;
    * run the deterministic engine and persist a unique, never-overwritten
      routing artifact under ``data/metadata/m6_routing``;
    * expose capabilities, pair status, run history and the optional execute
      dispatch (fallback triggers recorded, never silent).

The router is the SOLE owner of matcher selection in the pipeline; execution
is a separate dispatch step recorded back onto the routing run.
"""

from __future__ import annotations

import json
import platform
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Settings, m6_routing_config, rfc3339_now
from ..hardening import atomic_write_json
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..state import get_state
from .config import RoutingConfig, load_routing_config
from .contract import (
    EMPTY_CANDIDATE_OUTPUT,
    EXECUTION_STARTED,
    FAILED,
    FAILED_RUN,
    PRIMARY_MATCHER_UNAVAILABLE,
    ROUTED,
    assert_artifact_vocabulary_safe,
    license_text,
)
from .engine import route
from .service_util import executable_match_ids, execution_status_for_decision, run_status_summary
from .views import extract_capability_view, extract_condition_view

logger = get_logger(__name__)

_STATUS_SUCCESS = "SUCCESS"
_STATUS_BLOCKED = "BLOCKED"
_STATUS_FAILED = "FAILED"


class RoutingService:
    """Run, read, list and (optionally) dispatch M6 routing runs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_state().settings
        self.config: RoutingConfig = load_routing_config()
        self.metadata_root = (
            self.settings.data_root_path / Path(self.config.derived_rel)
        )
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def _new_run_id(self, pair_id: str) -> str:
        return f"r6-{pair_id}-{uuid.uuid4().hex[:8]}"

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            # Never overwrite: a run id is unique by construction; if it
            # exists this is a defensive halt, not a silent clobber.
            raise OSError(f"Refusing to overwrite existing M6 routing artifact {path.name}")
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
            rows.append(run_status_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ probe
    def _pair_record(self, pair_id: str) -> Any | None:
        return PairRegistry(self.settings).get(pair_id)

    def _processing_status(self, pair_id: str) -> dict[str, Any] | None:
        from ..processing.service import ProcessingService

        try:
            return ProcessingService(self.settings).read_status(pair_id) or {}
        except Exception:  # noqa: BLE001
            return None

    def _condition_full_payload(self, pair_id: str) -> dict[str, Any] | None:
        """Return the latest FULL M5 condition artifact for the pair."""
        from ..conditions.service import ConditionEstimationService

        service = ConditionEstimationService(self.settings)
        latest = service.latest_for_pair(pair_id)
        if not latest:
            return None
        run_id = (latest or {}).get("run_id")
        if not run_id:
            return None
        return service.read(str(run_id))

    def _classical_capabilities(self) -> dict[str, Any] | None:
        from ..matching.baseline import BaselineMatcherService

        try:
            return BaselineMatcherService(self.settings).capabilities_public()
        except Exception:  # noqa: BLE001
            return None

    def _deep_capabilities(self) -> dict[str, Any] | None:
        from ..matching.deep.service import DeepMatcherService

        try:
            return DeepMatcherService(self.settings).capabilities_public()
        except Exception:  # noqa: BLE001
            return None

    def capability_view(self) -> dict[str, Any]:
        return extract_capability_view(
            self._classical_capabilities(),
            self._deep_capabilities(),
        )

    def capabilities_public(self) -> dict[str, Any]:
        from .config import configurations_public
        from ..conditions.service import real_data_gate

        return {
            "configuration_id": self.config.configuration_id,
            "configuration_version": self.config.configuration_version,
            "name": self.config.name,
            "configuration": configurations_public()[0] if configurations_public() else None,
            "capabilities": {
                "classical": {k: self.capability_view().get(f"capability.{k}") for k in ("sift", "orb", "akaze")},
                "deep": {k: self.capability_view().get(f"capability.{k}") for k in ("superpoint_superglue", "loftr")},
            },
            "device": {"cuda_available": bool(self.capability_view().get("device.cuda_available"))},
            "data_gate": real_data_gate(self.settings),
            "note": (
                "Routing decisions are deterministic policy outcomes over the "
                "M5 condition profile (scientifically_tuned: false). Never a "
                "scientific accuracy or quality verdict. The router is the "
                "sole owner of matcher selection in the pipeline."
            ),
        }

    # ------------------------------------------------------------------ run
    def _environment_snapshot(self) -> dict[str, Any]:
        import cv2

        probe = {}
        try:
            from .service_util import deep_runtime_probe

            probe = deep_runtime_probe()
        except Exception:  # noqa: BLE001
            probe = {}
        return {
            "numpy_version": getattr(np, "__version__", "unknown"),
            "opencv_version": getattr(cv2, "__version__", "unknown"),
            "python": platform.python_version(),
            "platform": platform.system(),
            "deep_runtime": probe,
        }

    def _disposition_note(self, mode: str) -> str:
        if mode.upper() == "FIXED_BASELINE":
            return (
                "FIXED_BASELINE ablation arm: the matcher route is "
                "predetermined and condition facts are intentionally not "
                "inspected. Used to normalize ADAPTIVE comparisons."
            )
        return "ADAPTIVE arm: the route is selected deterministically from the M5 condition profile."

    def run(
        self,
        pair_id: str,
        mode: str | None = None,
        *,
        rules_override: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Produce + persist one routing decision for ``pair_id`` in ``mode``.

        Deterministic in mode/inputs; run_id + created_at are the only
        non-deterministic fields (excluded from the decision hash).
        """
        mode = (mode or self.config.default_mode).upper()
        if mode not in self.config.modes:
            raise ValueError(
                f"Routing mode {mode!r} is not enabled in configuration "
                f"{self.config.configuration_id}; enabled: {self.config.modes}."
            )

        record = self._pair_record(pair_id)
        processing_status = self._processing_status(pair_id)
        condition_payload = self._condition_full_payload(pair_id)

        run_id = self._new_run_id(pair_id)
        created_at = rfc3339_now()
        started = time.perf_counter()

        capability_view = self.capability_view()

        # configuration with (test-supplied) rule override; default = the full
        # registered configuration
        config = self.config
        if rules_override is not None:
            try:
                config = load_routing_config()
            except ValueError:
                config = self.config
            from .config import validate_rules

            from dataclasses import replace

            from .contract import routing_modes

            known_ids = set()
            matchers = config.p("matchers", default={}) or {}
            for group in ("classical", "deep"):
                known_ids.update(
                    str(k) for k, v in (matchers.get(group) or {}).items() if bool(v)
                )
            mode_list = config.modes
            rules = validate_rules(rules_override, known_ids=known_ids, mode_list=mode_list)
            config = replace(config, rules=rules)

        view = extract_condition_view(
            condition_payload,
            processing_status,
            record,
            appearance_policy=config.appearance_policy(),
            scale_policy=config.scale_policy(),
        )

        try:
            decision = route(view, capability_view, config, mode)
        except Exception as exc:  # noqa: BLE001
            payload = self._failed_payload(
                run_id=run_id, pair_id=pair_id, created_at=created_at,
                mode=mode, message=f"Routing raised: {exc}",
            )
            self.write_artifact(run_id, payload)
            return payload

        decision_status = execution_status_for_decision(decision.state)

        payload = {
            "routing_run_id": run_id,
            "run_id": run_id,
            "experiment_id": f"EXP-M6-{mode}-{config.configuration_id}",
            "pair_id": pair_id,
            "created_at_utc": created_at,
            "mode": mode,
            "configuration_id": config.configuration_id,
            "configuration_version": config.configuration_version,
            "configuration": config.as_manifest_snapshot(),
            "policy": {
                "rules": [r.snapshot() for r in config.rules],
                "appearance": config.appearance_policy(),
                "scale": config.scale_policy(),
                "fallback": config.p("fallback", default={}),
                "match_semantics": "any-of / all-of as configured per rule",
            },
            "scientifically_tuned": config.scientifically_tuned,
            "input": {
                "pair_id": pair_id,
                "processing_state": (processing_status or {}).get("state") or "NOT_RUN",
                "processing_configuration_id": (processing_status or {}).get("configuration_id"),
                "condition_run_id": view.get("condition_run_id"),
                "condition_configuration_id": (condition_payload or {}).get("configuration_id"),
                "ready_for_matching": bool(view.get("processing_ready")),
                "condition_profile_success": bool(view.get("condition_profile_available")),
                "synthetically_derived": bool(view.get("synthetically_derived")),
                "source_gate": view.get("data_source_gate"),
                "source_class_a": view.get("source_class_a"),
                "source_class_b": view.get("source_class_b"),
            },
            "condition_snapshot": {
                k: view.get(k) for k in (
                    "a.textural_complexity", "b.textural_complexity",
                    "pair.appearance_difference", "pair.appearance_difference_low",
                    "pair.appearance_difference_high", "pair.gsd_ratio",
                    "pair.gsd_ratio_large", "pair.gsd_ratio_medium",
                    "pair.texture_complexity_high", "pair.texture_complexity_low",
                    "pair.worst_invalid_fraction", "pair.absolute_pixel_ratio",
                )
            },
            "capability_snapshot": capability_view,
            "decision": decision.as_dict(),
            "decision_status": decision_status,
            "execution": None,
            "runtime_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "provenance": {
                "chain": "raw -> M2 processing (validated) -> M5 condition profile -> M6 routing",
                "m2": {"processing_configuration_id": (processing_status or {}).get("configuration_id")},
                "m5": {"condition_configuration_id": (condition_payload or {}).get("configuration_id")},
                "m6": {"routing_configuration_id": config.configuration_id},
            },
            "disposition_note": self._disposition_note(mode),
            "environment": self._environment_snapshot(),
            "license": license_text(),
        }

        if decision.state == ROUTED:
            payload["next_actions"] = executable_match_ids(
                decision.primary_matcher, decision.fallback_matcher
            )

        self.write_artifact(run_id, payload)
        return payload

    def _failed_payload(self, *, run_id: str, pair_id: str, created_at: str,
                        mode: str, message: str) -> dict[str, Any]:
        return {
            "routing_run_id": run_id,
            "run_id": run_id,
            "experiment_id": f"EXP-M6-{mode}-{self.config.configuration_id}",
            "pair_id": pair_id,
            "created_at_utc": created_at,
            "mode": mode,
            "configuration_id": self.config.configuration_id,
            "configuration_version": self.config.configuration_version,
            "configuration": self.config.as_manifest_snapshot(),
            "scientifically_tuned": self.config.scientifically_tuned,
            "decision_status": FAILED,
            "state": _STATUS_FAILED,
            "error_code": "ROUTING_FAILED",
            "error_detail": message,
            "decision": None,
            "execution": None,
            "runtime_ms": 0.0,
        }

    # ------------------------------------------------------------------ status
    def status(self, pair_id: str) -> dict[str, Any]:
        from ..conditions.service import real_data_gate

        record = self._pair_record(pair_id)
        processing = self._processing_status(pair_id)
        condition = self._condition_full_payload(pair_id)
        latest = self.latest_for_pair(pair_id)
        return {
            "pair_id": pair_id,
            "configuration_id": self.config.configuration_id,
            "has_routing_run": latest is not None,
            "latest_run": latest,
            "processing_state": (processing or {}).get("state") or None,
            "ready_for_matching": bool(processing and (processing or {}).get("state") == "READY_FOR_MATCHING"),
            "condition_profile_available": bool(condition and condition.get("status") == "SUCCESS"),
            "condition_run_id": (condition or {}).get("run_id"),
            "data_gate": real_data_gate(self.settings),
            "note": (
                "Routing is deterministic policy over the M5 condition profile "
                "(scientifically_tuned: false); never a scientific verdict."
            ),
        }

    # ------------------------------------------------------------------ execute
    def execute(self, pair_id: str, run_id: str) -> dict[str, Any]:
        """Optionally dispatch the routed matcher(s) for an existing routing run.

        Fallback triggers (primary unavailable / empty candidate output /
        failed run) are predeclared, per-trigger and recorded — a fallback is
        attempted at most ``max_fallback_attempts`` times.
        """
        artifact = self.read(run_id)
        if artifact is None:
            return {
                "execution": None,
                "decision_status": FAILED,
                "error_code": "ROUTING_RUN_NOT_FOUND",
                "error_detail": f"No routing run {run_id!r} exists.",
            }
        if artifact.get("pair_id") != pair_id:
            return {
                "execution": None,
                "decision_status": FAILED,
                "error_code": "ROUTING_RUN_PAIR_MISMATCH",
                "error_detail": f"Routing run {run_id!r} belongs to a different pair.",
            }
        if artifact.get("execution"):
            return {
                "execution": artifact.get("execution"),
                "decision_status": artifact.get("decision_status"),
                "note": "This routing run was already dispatched; returning the recorded execution.",
            }

        decision = artifact.get("decision") or {}
        if decision.get("state") != ROUTED:
            return {
                "execution": None,
                "decision_status": artifact.get("decision_status"),
                "error_code": decision.get("error_code"),
                "error_detail": "Only ROUTED decisions can be executed.",
            }

        primary = decision.get("primary_matcher")
        fallback = decision.get("fallback_matcher")
        max_attempts = self.config.max_fallback_attempts

        execution: dict[str, Any] = {}
        current = primary
        executed_routes: list[str] = []
        attempts = 0
        reason: str | None = None
        result: dict[str, Any] | None = None

        while current and attempts <= max_attempts:
            attempts += 1
            executed_routes.append(current)
            result = self._dispatch_matcher(pair_id, current)
            run_meta = _matcher_run(result)
            execution[current] = run_meta
            if run_meta.get("status") == "SUCCESS" and int(run_meta.get("candidate_match_count", 0) or 0) > 0:
                break
            reason = _fallback_reason_for(result, run_meta)
            current = fallback if attempts == 1 else None

        fallback_used = bool(reason)
        execution_status = "EXECUTION_STARTED"
        final_route = executed_routes[-1] if executed_routes else None

        updated = dict(artifact)
        updated["execution"] = {
            "executed_routes": executed_routes,
            "final_route": final_route,
            "fallback_used": fallback_used,
            "fallback_reason": reason,
            "max_fallback_attempts": max_attempts,
            "runs": execution,
            "executed_at_utc": rfc3339_now(),
            "note": (
                "Execution dispatch. When the primary matcher returns an empty "
                "candidate output or fails under declared conditions, the "
                "configured fallback is attempted (predeclared triggers; "
                "never silent)."
            ),
        }
        updated["decision_status"] = execution_status

        # overwrite is allowed here because the routing run already exists and
        # we are appending the execution dispatch to the SAME run.
        path = self.artifact_path(run_id)
        assert_artifact_vocabulary_safe(updated)
        atomic_write_json(path, updated)

        return {
            "execution": updated["execution"],
            "decision_status": execution_status,
            "note": "Dispatched the routing decision; execution recorded on the routing run.",
        }

    def _dispatch_matcher(self, pair_id: str, matcher_id: str) -> dict[str, Any]:
        from ..matching.baseline import BaselineMatcherService
        from ..matching.baseline import BASELINE_MATCHER_IDS
        from ..matching.deep.service import DeepMatcherService

        if matcher_id in BASELINE_MATCHER_IDS:
            return BaselineMatcherService(self.settings).run(pair_id, matcher_id)
        return DeepMatcherService(self.settings).run(pair_id, matcher_id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _safe_run_id(run_id: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id or ""))


def _matcher_run(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"status": "FAILED", "candidate_match_count": 0}
    # baseline artifacts expose the full MatcherOutput under ``matcher``
    matcher = result.get("matcher") or {}
    status = result.get("status") or matcher.get("status") or _STATUS_FAILED
    candidates = result.get("candidate_match_count")
    if candidates is None:
        candidates = matcher.get("candidate_match_count")
    return {
        "status": status,
        "candidate_match_count": candidates,
        "keypoint_count_a": result.get("keypoint_count_a") or matcher.get("keypoint_count_a"),
        "keypoint_count_b": result.get("keypoint_count_b") or matcher.get("keypoint_count_b"),
        "runtime_ms": result.get("runtime_ms") or matcher.get("runtime_ms"),
        "matcher_id": result.get("matcher_id") or matcher.get("matcher_id"),
        "run_id": result.get("run_id"),
    }


def _fallback_reason_for(result: dict[str, Any] | None, run_meta: dict[str, Any]) -> str:
    status = run_meta.get("status")
    if status == "SUCCESS" and int(run_meta.get("candidate_match_count", 0) or 0) == 0:
        return EMPTY_CANDIDATE_OUTPUT
    if status != "SUCCESS":
        code = (result or {}).get("error_code")
        return FAILED_RUN if code not in (PRIMARY_MATCHER_UNAVAILABLE,) else code
    return ""


def _execution_status_for_decision_legacy(state: str) -> str:
    return execution_status_for_decision(state)


# re-export for the API
__all__ = [
    "RoutingService",
    "run_status_summary",
]