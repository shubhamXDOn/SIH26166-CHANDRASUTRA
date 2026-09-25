"""M11 full-pipeline evidence builder (FullEvidenceBuilder).

Mirrors the M9 :class:`EvidenceBuilder` contract but covers the complete
current M1..M10 pipeline ("M11-EVIDENCE-001"):

    M1  intake / pair registry
    M2  processing                       ProcessingService
    M3  classical matching               MatchingService
    M4  deep matcher                     DeepMatcherService
    M5  condition estimation             ConditionEstimationService
    M6  adaptive routing                 RoutingService
    M7  trust gate                       TrustGateService
    M8  spatial selection                SpatialSelectionService
    M9  registration                     RegistrationM9Service
    M10 metrics / benchmark              M10MetricsService

The packet is the ONLY thing the model may reason over. It is built from real
pipeline artifacts (defensively read), sanitized (no secrets / absolute
paths), bounded (ctx-size aware via the prompt layer) and deterministic:
identical pipeline state produces an identical ``sha256:...`` digest, exactly
like the M9 packet.

Honesty rules carried through from the rest of the stack: nothing is
fabricated; a milestone that never ran is honestly NOT_STARTED; reference
accuracy is REFERENCE_UNAVAILABLE because no physical-truth dataset is
provisioned; no milestone asserts a scientific quality verdict.

The legacy M9 ``EvidenceBuilder.build`` is intentionally untouched — this
module adds a second, M11 schema surface alongside it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import Settings
from ..conditions.service import ConditionEstimationService
from ..matching.deep.service import DeepMatcherService
from ..matching.service import MatchingService
from ..metrics_m10.service import M10MetricsService
from ..processing.service import ProcessingService
from ..registration_m9.service import RegistrationM9Service
from ..routing.service import RoutingService
from ..routing.service_util import run_status_summary
from ..spatial_m8.service import SpatialSelectionService
from ..trust_gate.service import TrustGateService
from .config import AIConfig
from .evidence import (
    EvidenceBuild,
    Sanitizer,
    canonical_digest,
    rel_identifier,
    _compact,
)

M11_EVIDENCE_SCHEMA_VERSION = "M11-EVIDENCE-001"

_POSSIBLE_MILESTONES: tuple[str, ...] = (
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10",
)

_NOT_DONE = frozenset({"NOT_STARTED", "NOT_AVAILABLE", "NOT_RUN", "BLOCKED", "FAILED"})


def _state_of(payload: Any, key: str = "state") -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    return str(value) if isinstance(value, str) and value else "NOT_STARTED"


@dataclass
class FullEvidenceBuild(EvidenceBuild):
    """M11 full-pipeline evidence build (superset of the M9 build)."""

    schemas: tuple[str, ...] = (M11_EVIDENCE_SCHEMA_VERSION,)


class FullEvidenceBuilder:
    """Constructs the canonical M11 evidence packet (M1..M10) for a pair."""

    schema_version = M11_EVIDENCE_SCHEMA_VERSION

    def __init__(self, settings: Settings, ai_config: AIConfig):
        self._settings = settings
        self._ai_config = ai_config
        self._data_root = settings.data_root_path
        self._sanitizer = Sanitizer(settings)
        self._services: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # services (lazy, defensive)
    # ------------------------------------------------------------------
    def _svc(self, key: str, factory: Callable[[], Any]) -> Any:
        if key not in self._services:
            try:
                self._services[key] = factory()
            except Exception:  # noqa: BLE001 - evidence must never crash
                self._services[key] = None
        return self._services[key]

    def _processing(self):
        return self._svc("m2", lambda: ProcessingService(self._settings))

    def _matching(self):
        return self._svc("m3", lambda: MatchingService(self._settings))

    def _deep(self):
        return self._svc("m4", lambda: DeepMatcherService(self._settings))

    def _condition(self):
        return self._svc("m5", lambda: ConditionEstimationService(self._settings))

    def _routing(self):
        return self._svc("m6", lambda: RoutingService(self._settings))

    def _trust(self):
        return self._svc("m7", lambda: TrustGateService(self._settings))

    def _spatial(self):
        return self._svc("m8", lambda: SpatialSelectionService(self._settings))

    def _registration(self):
        return self._svc("m9", lambda: RegistrationM9Service(self._settings))

    def _metrics_m10(self):
        return self._svc("m10", lambda: M10MetricsService(self._settings))

    def _read(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return method(*args, **kwargs)
        except Exception:  # noqa: BLE001 - evidence building must never crash
            return {}

    # ------------------------------------------------------------------
    # public build
    # ------------------------------------------------------------------
    def build(self, pair_id: str, *, experiment_id: str | None = None) -> FullEvidenceBuild:
        entries: dict[str, dict[str, Any]] = {}
        for milestone, reader in (
            ("M1", self._read(self._m1_reader, pair_id)),
            ("M2", self._read(self._m2_reader, pair_id)),
            ("M3", self._read(self._m3_reader, pair_id)),
            ("M4", self._read(self._m4_reader, pair_id)),
            ("M5", self._read(self._m5_reader, pair_id)),
            ("M6", self._read(self._m6_reader, pair_id)),
            ("M7", self._read(self._m7_reader, pair_id)),
            ("M8", self._read(self._m8_reader, pair_id)),
            ("M9", self._read(self._m9_reader, pair_id)),
            ("M10", self._read(self._m10_reader, pair_id)),
        ):
            if not isinstance(reader, dict) or "source_milestone" not in reader:
                reader = {
                    "source_milestone": milestone,
                    "source_artifact": None,
                    "status": "NOT_STARTED",
                    "metrics": [],
                    "notes": ["%s evidence could not be read; reported honestly." % milestone],
                    "summary": None,
                }
            entries[milestone] = reader

        pipeline_state = {label: entry["status"] for label, entry in entries.items()}
        if experiment_id is None:
            experiment_id = self._derive_experiment_id(pair_id, entries)

        reference = {
            "status": "REFERENCE_UNAVAILABLE",
            "metric_id": "PHYSICAL_ACCURACY",
            "value": None,
            "reason": (
                "No external physical-truth/reference dataset is provisioned; "
                "the M10 benchmark is REFERENCE_UNAVAILABLE and no calibrated "
                "accuracy can be claimed."
            ),
        }

        limitations = self._derive_limitations(entries)

        packet = {
            "schema_version": self.schema_version,
            "description": "Full-pipeline evidence packet for the AI copilot (M11).",
            "pair_id": pair_id,
            "experiment_id": experiment_id,
            "pipeline_state": pipeline_state,
            "reference": reference,
            "limitations": limitations,
            "provenance": {
                "packet_builder": "FullEvidenceBuilder",
                "evidence_schema_version": self.schema_version,
                "milestones": list(_POSSIBLE_MILESTONES),
                "sources": "current M1..M10 pipeline artifacts (defensive reads)",
            },
            "m1": entries["M1"],
            "m2": entries["M2"],
            "m3": entries["M3"],
            "m4": entries["M4"],
            "m5": entries["M5"],
            "m6": entries["M6"],
            "m7": entries["M7"],
            "m8": entries["M8"],
            "m9": entries["M9"],
            "m10": entries["M10"],
        }

        packet = self._sanitizer.sanitize(packet)
        digest = canonical_digest(packet, algorithm=self._ai_config.digest_algorithm)
        return FullEvidenceBuild(
            packet=packet,
            digest=digest,
            experiment_id=experiment_id,
            pipeline_state=pipeline_state,
            limitations=list(limitations),
        )

    # ------------------------------------------------------------------
    # shared entry helpers
    # ------------------------------------------------------------------
    def _entry(self, milestone: str, source_artifact: str | None,
               status: str, metrics: list[dict[str, Any]],
               notes: list[str], summary: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "source_milestone": milestone,
            "source_artifact": source_artifact,
            "status": status,
            "metrics": metrics,
            "notes": notes,
        }
        if summary:
            entry["summary"] = summary
        return entry

    @staticmethod
    def _obs(metric_id: str, value: Any, status: str = "AVAILABLE", notes: str = "") -> dict[str, Any]:
        return {
            "metric_id": metric_id,
            "value": value,
            "status": status,
            "notes": notes,
        }

    # ------------------------------------------------------------------
    # per-milestone readers (each returns a complete entry dict)
    # ------------------------------------------------------------------
    def _m1_reader(self, pair_id: str) -> dict[str, Any]:
        from ..pairs import PairRegistry

        record = None
        try:
            record = PairRegistry(self._settings).get(pair_id)
        except Exception:  # noqa: BLE001
            record = None
        if record is None:
            return self._entry(
                "M1", None, "NOT_AVAILABLE", [], [
                    "Pair is not registered in the intake registry.",
                ], None,
            )
        record_compact = _compact(record)
        gate = getattr(record, "data_source_gate", None) or "PATH_UNKNOWN"
        metrics = [
            self._obs("PAIR_SENSOR_A", getattr(record, "sensor_a", None)),
            self._obs("PAIR_SENSOR_B", getattr(record, "sensor_b", None)),
            self._obs("PAIR_SOURCE_CLASS_A", getattr(record, "source_class_a", None)),
            self._obs("PAIR_SOURCE_CLASS_B", getattr(record, "source_class_b", None)),
            self._obs("PAIR_DATA_SOURCE_GATE", gate),
            self._obs("PAIR_GSD_A", getattr(record, "nominal_gsd_a", None)),
            self._obs("PAIR_GSD_B", getattr(record, "nominal_gsd_b", None)),
            self._obs("PAIR_OVERLAP_STATUS", getattr(record, "overlap_status", None)),
        ]
        notes = [
            "Data-source gate: %s" % gate
            + (" (PATH_A_REAL_DATA present)" if gate == "PATH_A_REAL_DATA" else "")
            + (" (CASE B: no real PRADAN data available)" if gate == "PATH_UNKNOWN" else ""),
            "Intake metadata; no scientific verdict is asserted.",
        ]
        return self._entry("M1", None, "REGISTERED", metrics, notes, record_compact)

    def _m2_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._processing()
        status = self._read(svc.read_status, pair_id) if svc else {}
        run = svc.find_run_for_pair(pair_id) if svc else None
        state = _state_of(status)
        metrics = [
            self._obs("M2_STATE", state),
            self._obs("M2_PRODUCTS_COUNT", len((status.get("products") or {}) if isinstance(status, dict) else {})),
        ]
        notes = []
        if isinstance(status, dict) and status.get("blocked"):
            notes.append("M2 BLOCKED at stage %s (%s); NO data was guessed or skipped."
                         % (status["blocked"].get("stage") or "?", status["blocked"].get("code") or "?"))
        notes.append("M2 products are validated inputs only; they are never a scientific verdict.")
        return self._entry(
            "M2", rel_identifier(run, self._data_root), state, metrics, notes,
            _compact(status),
        )

    def _m3_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._matching()
        status = self._read(svc.read_status, pair_id) if svc else {}
        summary = self._read(svc.summary, pair_id) if svc else {}
        run = svc.find_run_for_pair(pair_id) if svc else None
        metrics = [
            self._obs("FUNNEL_M3_TILES", (summary or {}).get("tiles") if summary else None),
            self._obs("FUNNEL_M3_CANDIDATES", (summary or {}).get("total_candidates") if summary else None),
        ]
        notes = [(summary or {}).get("note")] if summary and (summary or {}).get("note") else []
        return self._entry(
            "M3", rel_identifier(run, self._data_root), _state_of(status), metrics, notes,
            _compact(summary),
        )

    def _m4_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._deep()
        caps = self._read(svc.capabilities_public) if svc else {}
        latest = self._read(svc.latest_for_pair, pair_id) if svc else None
        latest_state = (latest or {}).get("state") or (latest or {}).get("status")
        state = str(latest_state) if isinstance(latest_state, str) and latest_state else "NOT_STARTED"
        if state in ("NOT_STARTED", "") and not latest:
            state = "AVAILABLE" if bool(caps.get("available")) else "BLOCKED"
        metrics = [
            self._obs("M4_DEEP_AVAILABLE", bool(caps.get("available"))),
            self._obs("M4_DEEP_MATCHER_STATUS", state),
            self._obs("M4_DEEP_CANDIDATES", (latest or {}).get("counts", {}).get("candidates") if latest else None),
            self._obs("M4_DEEP_CHECKPOINT_SHA256",
                      (caps.get("matchers") or [{}])[0].get("checkpoint_sha256") if (caps.get("matchers") or []) else None),
        ]
        notes = [str(caps.get("note"))] if caps.get("note") else []
        if latest:
            notes.insert(0, "Latest deep run %s (matcher %s, runtime %s ms)."
                         % ((latest or {}).get("run_id") or "?", (latest or {}).get("matcher_id") or "?",
                            (latest or {}).get("runtime_ms") or "?"))
        return self._entry(
            "M4", rel_identifier(None, self._data_root), state,
            metrics, notes, _compact({"capabilities": caps, "latest": latest}),
        )

    def _m5_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._condition()
        caps = self._read(svc.capabilities_public) if svc else {}
        latest = self._read(svc.latest_for_pair, pair_id) if svc else None
        state = _state_of(latest or {})
        metrics = [
            self._obs("M5_CONDITION_STATE", state),
            self._obs("M5_CONDITION_RUN_ID", (latest or {}).get("run_id") if latest else None),
        ]
        notes = []
        if caps.get("data_gate"):
            notes.append("Condition data gate: %s" % caps["data_gate"])
        return self._entry(
            "M5", rel_identifier(None, self._data_root), state, metrics, notes,
            _compact({"capabilities": caps, "latest": latest}),
        )

    def _m6_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._routing()
        status = self._read(svc.status, pair_id) if svc else {}
        latest = self._read(svc.latest_for_pair, pair_id) if svc else None
        decision = run_status_summary(latest) if latest else {}
        state = decision.get("state") or _state_of(status if status else {}) or "NOT_STARTED"
        metrics = [
            self._obs("M6_ROUTING_STATE", state),
            self._obs("M6_PRIMARY_MATCHER", decision.get("primary_matcher")),
            self._obs("M6_FALLBACK_MATCHER", decision.get("fallback_matcher")),
            self._obs("M6_FALLBACK_USED", bool(decision.get("fallback_used"))),
            self._obs("M6_DECISION_HASH", decision.get("decision_hash")),
        ]
        notes = [
            "Routing is a deterministic what-to-try order (M5 condition profile); "
            "never a matcher quality or scene-confidence verdict."
        ]
        return self._entry(
            "M6", rel_identifier(None, self._data_root), state, metrics, notes,
            _compact({"status": status, "latest": decision}),
        )

    def _m7_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._trust()
        status = self._read(svc.status, pair_id) if svc else {}
        latest = self._read(svc.latest_for_pair, pair_id) if svc else None
        state = (latest or {}).get("state") or _state_of(status if status else {})
        metrics = [
            self._obs("TRUST_DECISION_HASH", (latest or {}).get("decision_hash")),
            self._obs("TRUST_CANDIDATE_COUNT", (latest or {}).get("candidate_count")),
            self._obs("TRUST_VERIFIED_COUNT", (latest or {}).get("verified_count")),
            self._obs("TRUST_INLIER_COUNT", (latest or {}).get("inlier_count")),
            self._obs("TRUST_INLIER_RATIO", (latest or {}).get("inlier_ratio")),
            self._obs("TRUST_BLOCK_ABSTAIN_CODE",
                      (latest or {}).get("block_code") or (latest or {}).get("abstain_code")),
        ]
        notes = []
        if (latest or {}).get("block_code"):
            notes.append("Trust gate blocked (%s)." % latest["block_code"])
        if (latest or {}).get("abstain_code"):
            notes.append("Trust gate abstained (%s)." % latest["abstain_code"])
        return self._entry(
            "M7", rel_identifier(None, self._data_root), state, metrics, notes,
            _compact({"configured": (status or {}).get("configured"), "latest": latest}),
        )

    def _m8_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._spatial()
        status = self._read(svc.status, pair_id) if svc else {}
        latest = self._read(svc.latest_for_pair, pair_id) if svc else None
        state = (latest or {}).get("state") or _state_of(status if status else {})
        metrics = [
            self._obs("SPATIAL_DECISION_HASH", (latest or {}).get("decision_hash")),
            self._obs("SPATIAL_TRUSTED_COUNT", (latest or {}).get("trusted_count")),
            self._obs("SPATIAL_SELECTED_COUNT", (latest or {}).get("selected_count")),
            self._obs("SPATIAL_EXCLUDED_COUNT", (latest or {}).get("excluded_count")),
            self._obs("SPATIAL_SOURCE_COVERAGE", (latest or {}).get("source_coverage_ratio")),
            self._obs("SPATIAL_TARGET_COVERAGE", (latest or {}).get("target_coverage_ratio")),
        ]
        notes = [str((latest or {}).get("explanation"))] if (latest or {}).get("explanation") else []
        return self._entry(
            "M8", rel_identifier(None, self._data_root), state, metrics, notes,
            _compact({"configured": (status or {}).get("configured"), "latest": latest}),
        )

    def _m9_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._registration()
        status = self._read(svc.status, pair_id) if svc else {}
        latest = self._read(svc.latest_for_pair, pair_id) if svc else None
        state = (latest or {}).get("state") or _state_of(status if status else {})
        metrics = [
            self._obs("REGISTRATION_DECISION_HASH", (latest or {}).get("decision_hash")),
            self._obs("REGISTRATION_ACCEPTED", (latest or {}).get("accepted")),
            self._obs("REGISTRATION_SELECTED_COUNT", (latest or {}).get("selected_count")),
            self._obs("REGISTRATION_RESIDUAL_RMSE_PX", (latest or {}).get("residual_rmse_px")),
            self._obs("REGISTRATION_WARP_AVAILABLE", (latest or {}).get("warp_available")),
        ]
        notes = [str((latest or {}).get("explanation"))] if (latest or {}).get("explanation") else []
        if (latest or {}).get("block_code"):
            notes.append("Registration blocked (%s)." % latest["block_code"])
        if (latest or {}).get("abstain_code"):
            notes.append("Registration abstained (%s)." % latest["abstain_code"])
        return self._entry(
            "M9", rel_identifier(None, self._data_root), state, metrics, notes,
            _compact({"configured": (status or {}).get("configured"), "latest": latest}),
        )

    def _m10_reader(self, pair_id: str) -> dict[str, Any]:
        svc = self._metrics_m10()
        latest = self._read(svc.latest, pair_id) if svc else None
        prereq = self._read(svc.prerequisites, pair_id) if svc else {}
        failures = self._read(svc.failure_analysis, pair_ids=[pair_id]) if svc else {}
        state = (latest or {}).get("state") or "NOT_STARTED"
        metrics = [
            self._obs("M10_STATE", state),
            self._obs("M10_VARIANT", (latest or {}).get("variant_id")),
            self._obs("M10_CANDIDATE_COUNT", (latest or {}).get("metrics", {}).get("candidate_count") if latest else None),
            self._obs("M10_VERIFIED_COUNT", (latest or {}).get("metrics", {}).get("verified_count") if latest else None),
            self._obs("M10_INLIER_COUNT", (latest or {}).get("metrics", {}).get("inlier_count") if latest else None),
            self._obs("M10_SELECTED_COUNT", (latest or {}).get("metrics", {}).get("selected_count") if latest else None),
            self._obs("M10_REGISTERED_COUNT", (latest or {}).get("metrics", {}).get("registered_count") if latest else None),
            self._obs("M10_REGISTRATION_RMSE_PX", (latest or {}).get("metrics", {}).get("registration_rmse_px") if latest else None),
            self._obs("M10_REGISTRATION_P95_PX", (latest or {}).get("metrics", {}).get("registration_p95_px") if latest else None),
            self._obs("M10_FAILED_COUNT", (failures or {}).get("counts", {}).get("failed")),
            self._obs("M10_ABSTAIN_COUNT", (failures or {}).get("counts", {}).get("abstain")),
        ]
        notes = [
            "M10 benchmark is descriptive; reference status is "
            "REFERENCE_UNAVAILABLE (no calibrated accuracy is claimed)."
        ]
        if (latest or {}).get("notes"):
            notes.append(str(latest["notes"]))
        if (latest or {}).get("stage"):
            notes.append("M10 stage: %s" % latest["stage"])
        return self._entry(
            "M10", rel_identifier(None, self._data_root), state, metrics, notes,
            _compact({"latest": latest, "prerequisites": prereq}),
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _derive_experiment_id(self, pair_id: str, entries: dict[str, dict[str, Any]]) -> str | None:
        # The M6 routing run carries the experiment identity; fall back to the
        # latest M10 benchmark run id when no routing run exists yet.
        m6_summary = (entries.get("M6") or {}).get("summary") or {}
        latest_m6 = (m6_summary.get("latest") if isinstance(m6_summary, dict) else None) or {}
        exp = latest_m6.get("experiment_id") if isinstance(latest_m6, dict) else None
        if exp:
            return str(exp)
        m10_summary = (entries.get("M10") or {}).get("summary") or {}
        latest_m10 = (m10_summary.get("latest") if isinstance(m10_summary, dict) else None) or {}
        run_id = latest_m10.get("run_id") if isinstance(latest_m10, dict) else None
        return str(run_id) if run_id else None

    def _derive_limitations(self, entries: dict[str, dict[str, Any]]) -> list[str]:
        limits: list[str] = []
        not_done = {label: entries[label]["status"] in _NOT_DONE for label in _POSSIBLE_MILESTONES}
        for label, is_nd in not_done.items():
            if is_nd:
                limits.append(
                    "M%s has not produced a completed run (state %s); downstream "
                    "milestones are described only from what genuinely exists."
                    % (label[1:], entries[label]["status"])
                )
        limits.append(
            "No external reference (physical-truth) dataset is integrated; "
            "reference/accuracy values are REFERENCE_UNAVAILABLE at M10."
        )
        limits.append(
            "All pipeline thresholds are engineering defaults registered under "
            "Configuration IDs; none are scientifically tuned against real lunar "
            "reference data."
        )
        seen: set[str] = set()
        unique: list[str] = []
        for item in limits:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique


__all__ = [
    "FullEvidenceBuilder",
    "FullEvidenceBuild",
    "M11_EVIDENCE_SCHEMA_VERSION",
]