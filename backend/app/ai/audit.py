"""M9 AI audit trail.

A single append-only JSON-lines file records every AI task attempt with the
metadata needed to reproduce the *decision context* — never the full prompt,
never the raw provider response, never any credential. Failures to write the
audit record are swallowed (audit must never break the user-facing request).

Record fields:
    request_id, pair_id, task, experiment_id, model, prompt_version,
    evidence_schema_version, status, latency_ms, created_at
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings, rfc3339_now
from ..logging_conf import get_logger

logger = get_logger(__name__)


class AuditRecorder:
    def __init__(self, settings: Settings, *, subdir: str = "derived/ai/audit"):
        self._path = settings.data_root_path / Path(subdir) / "audit.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        request_id: str,
        pair_id: str,
        task: str,
        experiment_id: str | None,
        model: str,
        prompt_version: str,
        evidence_schema_version: str,
        status: str,
        latency_ms: float | None = None,
        executed_by_user_id: str | None = None,
        executed_by_role: str | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "request_id": request_id,
            "pair_id": pair_id,
            "task": task,
            "experiment_id": experiment_id,
            "model": model,
            "prompt_version": prompt_version,
            "evidence_schema_version": evidence_schema_version,
            "status": status,
            "latency_ms": round(latency_ms, 1) if isinstance(latency_ms, (int, float)) else "NOT_AVAILABLE",
            "created_at": rfc3339_now(),
        }
        if executed_by_user_id:
            entry["executed_by_user_id"] = str(executed_by_user_id)
        if executed_by_role:
            entry["executed_by_role"] = str(executed_by_role)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        except OSError:
            logger.warning("Could not write AI audit record.", extra={"operation": "ai.audit", "status": "failed"})
        return entry

    def read_all(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        out: list[dict[str, Any]] = []
        try:
            with open(self._path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        out.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            return out
        return out


__all__ = ["AuditRecorder"]