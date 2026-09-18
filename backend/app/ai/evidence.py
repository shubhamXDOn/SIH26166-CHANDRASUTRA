"""M9 evidence builder, sanitizer and deterministic packet digest.

The evidence packet is the ONLY thing the Gemini model may reason over. It is
built from real pipeline artifacts (``status.json`` / ``summary.json`` /
``report.json`` reads), sanitized (no secrets, no absolute paths), bounded
(ctx-size aware) and deterministic: identical pipeline state produces an
identical serialized digest (``sha256:...``).

The packet itself is data, never instructions — the prompt relies on the
delimiter contract in :mod:`backend.app.ai.prompts`.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..config import Settings, m4_config, m5_config, m6_config, m7_config
from ..matching.m8.service import M8Service
from ..matching.service import MatchingService
from ..metrics.service import MetricsService
from ..processing.manifest import rel_string
from ..processing.service import ProcessingService
from ..registration.service import RegistrationService
from ..spatial.service import SpatialService
from ..trust.service import TrustService
from .config import AIConfig

_VOLATILE_KEYS: frozenset[str] = frozenset({
    "generated_at", "updated_at", "started_at", "finished_at",
    "timestamp", "created_at", "ended_at",
})

_ABS_WINDOWS = re.compile(r"[A-Za-z]:[\\/][^\s\",{}]+")
_ABS_POSIX = re.compile(r"(?<![\w.])/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+){1,}")
_GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_CREDENTIAL = re.compile(r"(?i)(access_token|api_key|apikey|authorization|auth)\s*[:=]\s*\S+")


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _compact(value: Any, depth: int = 0, max_items: int = 60) -> Any:
    """Keep only safe, bounded, deterministic (non-volatile) JSON values."""
    if depth > 3:
        return None
    if _is_scalar(value):
        if isinstance(value, str):
            return value[:400]
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in _VOLATILE_KEYS and _is_scalar(item):
                continue
            reduced = _compact(item, depth + 1, max_items)
            if reduced is not None:
                out[str(key)] = reduced
            if len(out) >= max_items:
                break
        return out
    if isinstance(value, (list, tuple)):
        out_list: list[Any] = []
        for item in value:
            reduced = _compact(item, depth + 1, max_items)
            if reduced is not None:
                out_list.append(reduced)
            if len(out_list) >= max_items:
                break
        return out_list
    return None


class Sanitizer:
    """Strips secrets and absolute paths from evidence before it leaves the box."""

    def __init__(self, settings: Settings):
        self._literal_secrets = {
            s for s in (settings.gemini_api_key.strip(), settings.auth_secret_key.strip())
            if s
        }

    def _scan(self, text: str) -> str:
        out = text
        for secret in self._literal_secrets:
            if secret and secret in out:
                out = out.replace(secret, "[REDACTED]")
        out = _GOOGLE_KEY.sub("[REDACTED_API_KEY]", out)
        out = _CREDENTIAL.sub(lambda m: m.group(1) + ": [REDACTED]", out)
        out = _ABS_WINDOWS.sub("[ABSOLUTE_PATH]", out)
        out = _ABS_POSIX.sub("[ABSOLUTE_PATH]", out)
        return out

    def sanitize(self, value: Any) -> Any:
        if _is_scalar(value):
            return self._scan(value) if isinstance(value, str) else value
        if isinstance(value, dict):
            return {str(k): self.sanitize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize(v) for v in value]
        return str(value)


def rel_identifier(path: Path | None, data_root: Path) -> str | None:
    """Turn an artifact path into a stable relative identifier (never absolute)."""
    if path is None:
        return None
    try:
        path = Path(path).resolve()
        root = Path(data_root).resolve()
        return path.relative_to(root).as_posix()
    except (ValueError, OSError):
        return Path(path).name or None


@dataclass
class EvidenceBuild:
    packet: dict[str, Any]
    digest: str
    experiment_id: str | None
    pipeline_state: dict[str, str]
    limitations: list[str] = field(default_factory=list)


class EvidenceBuilder:
    """Constructs the canonical M9 evidence packet for a pair."""

    def __init__(self, settings: Settings, ai_config: AIConfig):
        self._settings = settings
        self._ai_config = ai_config
        self._data_root = settings.data_root_path
        self._sanitizer = Sanitizer(settings)
        self._services: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # services (lazy)
    # ------------------------------------------------------------------
    def _svc(self, key: str, factory: Callable[[], Any]) -> Any:
        if key not in self._services:
            self._services[key] = factory()
        return self._services[key]

    def _processing(self) -> ProcessingService:
        return self._svc("m2", lambda: ProcessingService(self._settings))

    def _matching(self) -> MatchingService:
        return self._svc("m3", lambda: MatchingService(self._settings))

    def _trust(self) -> TrustService:
        return self._svc("m4", lambda: TrustService(self._data_root, m4_config()))

    def _spatial(self) -> SpatialService:
        return self._svc("m5", lambda: SpatialService(self._data_root, m5_config(), m4_config()))

    def _registration(self) -> RegistrationService:
        return self._svc("m6", lambda: RegistrationService(
            self._data_root, m6_config(), m5_config(), m4_config()))

    def _metrics(self) -> MetricsService:
        return self._svc("m7", lambda: MetricsService(
            self._data_root, m7_config(), m6_config(), m5_config(), m4_config()))

    def _m8(self) -> M8Service:
        return self._svc("m8", lambda: M8Service(self._settings))

    # ------------------------------------------------------------------
    # public build
    # ------------------------------------------------------------------
    def build(self, pair_id: str) -> EvidenceBuild:
        m2 = self._read(self._processing().read_status, pair_id)
        m3 = self._read(self._matching().read_status, pair_id)
        m4 = self._read(self._trust().read_status, pair_id)
        m5 = self._read(self._spatial().read_status, pair_id)
        m6 = self._read(self._registration().read_status, pair_id)
        m7 = self._read(self._metrics().read_status, pair_id)
        m8 = self._read(self._m8().read_status, pair_id)

        entries = {
            "M2": self._m2_entry(pair_id, m2),
            "M3": self._m3_entry(pair_id, m3),
            "M4": self._m4_entry(pair_id, m4),
            "M5": self._m5_entry(pair_id, m5),
            "M6": self._m6_entry(pair_id, m6),
            "M7": self._m7_entry(pair_id, m7),
            "M8": self._m8_entry(pair_id, m8),
        }

        pipeline_state = {label: entry["status"] for label, entry in entries.items()}

        experiment_id = self._m7_experiment_id(pair_id)

        limitations = self._derive_limitations(entries)

        reference = {
            "status": "NOT_AVAILABLE",
            "metric_id": "PHYSICAL_ACCURACY",
            "reason": (
                "No external physical-truth/reference dataset is integrated "
                "(M7 policy: PHYSICAL_ACCURACY = REFERENCE_UNAVAILABLE)."
            ),
        }

        packet = {
            "schema_version": self._ai_config.evidence_schema_version,
            "pair_id": pair_id,
            "experiment_id": experiment_id,
            "pipeline_state": pipeline_state,
            "m2": entries["M2"],
            "m3": entries["M3"],
            "m4": entries["M4"],
            "m5": entries["M5"],
            "m6": entries["M6"],
            "m7": entries["M7"],
            "m8": entries["M8"],
            "reference": reference,
            "limitations": limitations,
        }

        packet = self._sanitizer.sanitize(packet)
        digest = canonical_digest(packet, algorithm=self._ai_config.digest_algorithm)
        return EvidenceBuild(
            packet=packet,
            digest=digest,
            experiment_id=experiment_id,
            pipeline_state=pipeline_state,
            limitations=list(limitations),
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _read(method: Callable[[str], dict], pair_id: str) -> dict:
        try:
            payload = method(pair_id)
            return payload if isinstance(payload, dict) else {}
        except Exception:  # noqa: BLE001 - evidence building must never crash
            return {}

    @staticmethod
    def _state_of(status: dict, key: str = "state") -> str:
        value = status.get(key)
        return str(value) if isinstance(value, str) and value else "NOT_AVAILABLE"

    def _entry(self, milestone: str, run: Path | None, status: dict,
               metrics: list[dict[str, Any]], notes: list[str]) -> dict[str, Any]:
        return {
            "source_milestone": milestone,
            "source_artifact": rel_identifier(run, self._data_root),
            "status": self._state_of(status),
            "metrics": metrics,
            "notes": notes,
        }

    @staticmethod
    def _obs(metric_id: str, value: Any, status: str = "AVAILABLE", notes: str = "") -> dict[str, Any]:
        return {
            "metric_id": metric_id,
            "value": value,
            "status": status,
            "notes": notes,
        }

    # ------------------------------------------------------------------
    # per-milestone
    # ------------------------------------------------------------------
    def _m2_entry(self, pair_id: str, status: dict) -> dict:
        run = self._processing().find_run_for_pair(pair_id)
        compact = _compact(status)
        notes = []
        stages = status.get("stages")
        if isinstance(stages, list):
            states = {str(s.get("id")): str(s.get("state")) for s in stages if isinstance(s, dict)}
            if states:
                notes.append("stage summary: " + json.dumps(states, sort_keys=True))
        return self._entry_id("M2", run, status, compact, notes)

    def _entry_id(self, milestone: str, run: Path | None, status: dict,
                  compact: Any, notes: list[str]) -> dict[str, Any]:
        entry = self._entry(milestone, run, status, [], notes)
        if compact:
            entry["summary"] = compact
        return entry

    def _m3_entry(self, pair_id: str, status: dict) -> dict:
        summary = self._read(self._matching().summary, pair_id)
        metrics = []
        if isinstance(summary, dict) and "error" not in summary:
            metrics.append(self._obs("FUNNEL_M3_TILES", summary.get("tiles")))
            metrics.append(self._obs("FUNNEL_M3_CANDIDATES", summary.get("total_candidates")))
        run = self._matching().find_run_for_pair(pair_id)
        notes = [summary.get("note")] if isinstance(summary, dict) and summary.get("note") else []
        return self._entry_id("M3", run, status, _compact(summary), notes)

    def _m4_entry(self, pair_id: str, status: dict) -> dict:
        summary = self._read(self._trust().summary, pair_id)
        metrics = []
        if isinstance(summary, dict) and "error" not in summary:
            metrics.append(self._obs("FUNNEL_M4_TRUSTED_TILES", summary.get("trusted_tiles")))
            metrics.append(self._obs("FUNNEL_M4_REJECTED_TILES", summary.get("rejected_tiles")))
            metrics.append(self._obs("FUNNEL_M4_TRUSTED_CORRESPONDENCES", summary.get("total_trusted_correspondences")))
        run = self._trust().find_run_for_pair(pair_id)
        return self._entry_id("M4", run, status, _compact(summary), [])

    def _m5_entry(self, pair_id: str, status: dict) -> dict:
        summary = self._read(self._spatial().summary, pair_id)
        run = self._spatial().find_run_for_pair(pair_id)
        return self._entry_id("M5", run, status, _compact(summary), [])

    def _m6_entry(self, pair_id: str, status: dict) -> dict:
        summary = self._read(self._registration().summary, pair_id)
        run = self._registration().find_run_for_pair(pair_id)
        notes = []
        verdict = summary.get("verdict") if isinstance(summary, dict) else None
        if verdict:
            notes.append(f"registration validation verdict: {verdict}")
        return self._entry_id("M6", run, status, _compact(summary), notes)

    def _m7_entry(self, pair_id: str, status: dict) -> dict:
        summary = self._read(self._metrics().summary, pair_id)
        run = self._metrics().find_run_for_pair(pair_id)
        records = self._metrics().metrics(pair_id) or []
        sanitized_records = _compact(self._sanitizer.sanitize(records[:80]))
        return self._entry_id("M7", run, status, _compact(summary), []) | {
            "metrics": sanitized_records or [],
        }

    def _m8_entry(self, pair_id: str, status: dict) -> dict:
        summary = self._read(self._m8().summary, pair_id)
        run = self._m8().find_run_for_pair(pair_id)
        metrics = []
        if isinstance(summary, dict) and "error" not in summary:
            metrics.append(self._obs("M8_TILES", summary.get("tiles")))
            metrics.append(self._obs("M8_TOTAL_CANDIDATES", summary.get("total_candidates")))
            downstream = summary.get("downstream")
            if isinstance(downstream, dict):
                metrics.append(self._obs(
                    "M8_DOWNSTREAM", {k: v for k, v in downstream.items() if k != "note"},
                    status="OBSERVATION",
                    notes="Categorical downstream maturity from the M8 run."))
        notes = [summary.get("note")] if isinstance(summary, dict) and summary.get("note") else []
        return self._entry_id("M8", run, status, _compact(summary), notes) | {
            "metrics": metrics,
        }

    def _m7_experiment_id(self, pair_id: str) -> str | None:
        experiment = self._read(self._metrics().experiment, pair_id)
        exp_id = experiment.get("experiment_id") if isinstance(experiment, dict) else None
        return str(exp_id) if exp_id else None

    def _derive_limitations(self, entries: dict[str, dict]) -> list[str]:
        limits: list[str] = []
        if entries["M4"]["status"] in ("NOT_STARTED", "NOT_AVAILABLE", "BLOCKED", "FAILED", "NOT_RUN"):
            limits.append("M4 Trust Gate has not produced an accepted, verified registration verdict.")
        if entries["M7"]["status"] in ("NOT_STARTED", "NOT_AVAILABLE", "NOT_RUN", "BLOCKED", "FAILED"):
            limits.append("M7 metrics have not produced a complete experiment report.")
        if entries["M8"]["status"] in ("NOT_STARTED", "NOT_AVAILABLE", "NOT_RUN", "BLOCKED"):
            limits.append("M8 deep-matcher expansion has not produced candidate evidence.")
        m8_caps = (entries["M8"].get("summary") or {}).get("downstream") if isinstance(entries["M8"].get("summary"), dict) else None
        if m8_caps:
            limits.append("M8 downstream columns are categorical maturity states, not quality verdicts.")
        limits.append(
            "No external reference (physical-truth) dataset is integrated; "
            "reference/physical accuracy values are not available at this milestone.")
        limits.append(
            "All pipeline thresholds are engineering defaults registered under Configuration IDs; "
            "none are scientifically tuned against real lunar reference data.")
        seen: set[str] = set()
        unique: list[str] = []
        for item in limits:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique


def canonical_digest(packet: dict[str, Any], algorithm: str = "sha256") -> str:
    """Deterministic digest over a volatile-free, sorted serialization."""
    try:
        digest = hashlib.new(algorithm)
    except (ValueError, TypeError):
        digest = hashlib.sha256()
        algorithm = "sha256"
    serialized = json.dumps(
        packet, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    digest.update(serialized)
    return f"{algorithm}:{digest.hexdigest()}"


__all__ = [
    "EvidenceBuild",
    "EvidenceBuilder",
    "Sanitizer",
    "canonical_digest",
    "rel_identifier",
    "_compact",
]