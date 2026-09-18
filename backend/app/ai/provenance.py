"""M9 provenance node builder.

Every successful and failed AI attempt (that reached a request_id) writes a
self-contained provenance record under
    derived/ai/<pair_id>/<request_id>/provenance.json
that is referenced downstream by M9 REPORT.md. Absolute paths, API keys and
prompt/response content are never stored. ``response_digest`` covers exactly
what the model returned (so the user can replay the validation check against
their own copy if needed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import Settings, rfc3339_now
from ..processing.manifest import rel_string
from .config import AIConfig

_INPUT_SCHEMA_VERSION = "M9-EVIDENCE-001"
_OUTPUT_SCHEMA_VERSION = "M9-AUDIT-001"


def build_m9_provenance(
    *,
    settings: Settings,
    ai_config: AIConfig,
    pair_id: str,
    request_id: str,
    task: str,
    model: str,
    experiment_id: str | None,
    evidence_digest: str,
    response_digest: str | None,
    status: str,
    created_at: str | None = None,
    pipeline_state: dict[str, str] | None = None,
    evidence_packet_schema: str | None = None,
    executed_by: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a serializable provenance node (no file I/O)."""
    node: dict[str, Any] = {
        "milestone": "M9",
        "pair_id": pair_id,
        "request_id": request_id,
        "configuration_id": ai_config.configuration_id,
        "configuration_version": ai_config.configuration_version,
        "prompt_version": ai_config.prompt_version,
        "evidence_schema_version": evidence_packet_schema or ai_config.evidence_schema_version,
        "input_evidence_schema": _INPUT_SCHEMA_VERSION,
        "output_schema": _OUTPUT_SCHEMA_VERSION,
        "model": model,
        "task": task,
        "experiment_id": experiment_id,
        "input_evidence_digest": evidence_digest,
        "ai_response_digest": response_digest or "NOT_AVAILABLE",
        "status": status,
        "created_at": created_at or rfc3339_now(),
        "policy": {
            "explanatory_only": True,
            "core_science_source": "backend scientific pipeline (M2..M8)",
            "api_key_exposed": False,
            "stores_prompts": ai_config.store_prompts,
            "stores_responses": ai_config.store_responses,
        },
        "pipeline_state": dict(pipeline_state) if pipeline_state else {},
    }
    if executed_by:
        # identity is contextual provenance, never part of scientific digests
        node["executed_by"] = {
            "user_id": executed_by.get("user_id"),
            "username": executed_by.get("username"),
            "role": executed_by.get("role"),
        }
    return node


def write_m9_provenance(entry: dict[str, Any], settings: Settings) -> Path:
    pair_id = str(entry.get("pair_id", "unknown"))
    request_id = str(entry.get("request_id", "unknown"))
    run_dir = settings.data_root_path / "derived" / "ai" / pair_id / request_id
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "provenance.json"
    path.write_text(json.dumps(entry, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


__all__ = ["build_m9_provenance", "write_m9_provenance"]