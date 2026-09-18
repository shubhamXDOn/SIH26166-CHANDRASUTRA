"""M9 AI configuration (AI-M9-001).

Runtime bounds come from ``Settings`` (env/.env tunable); the stable
identities (configuration id, prompt version, evidence schema version,
grounding rules, delimiters, forbidden-result terminology) come from the
``m9`` section of ``configs/app.yaml`` via :func:`backend.app.config.m9_config`.

Nothing in here is secret. The Gemini API key is read by the client directly
from ``Settings`` and is never placed on this object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, _M9_DEFAULTS, m9_config

DEFAULT_POSSIBLE_MILESTONES: tuple[str, ...] = ("M2", "M3", "M4", "M5", "M6", "M7", "M8")


@dataclass(frozen=True)
class AIConfig:
    configuration_id: str
    configuration_version: int
    name: str
    provider: str
    prompt_version: str
    evidence_schema_version: str
    begin_delimiter: str
    end_delimiter: str
    forbidden_result_terms: tuple[str, ...]
    grounding_rules: dict[str, str]
    task_ids: tuple[str, ...]
    max_input_chars: int
    max_output_tokens: int
    timeout_seconds: float
    rate_limit_per_minute: int
    max_sessions: int
    session_ttl_seconds: int
    digest_algorithm: str
    store_prompts: bool
    store_responses: bool
    source: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def as_public_dict(self) -> dict[str, Any]:
        """Non-secret, UI-safe view (never includes any credential)."""
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "provider": self.provider,
            "prompt_version": self.prompt_version,
            "evidence_schema_version": self.evidence_schema_version,
            "tasks": list(self.task_ids),
            "forbidden_result_terms": list(self.forbidden_result_terms),
            "constraints": {
                "max_input_chars": self.max_input_chars,
                "max_output_tokens": self.max_output_tokens,
                "timeout_seconds": self.timeout_seconds,
                "rate_limit_per_minute": self.rate_limit_per_minute,
                "session_ttl_seconds": self.session_ttl_seconds,
            },
            "store_prompts": self.store_prompts,
            "store_responses": self.store_responses,
            "source": self.source,
        }


def load_ai_config(settings: Settings | None = None) -> AIConfig:
    """Merge YAML identity with env-tunable runtime bounds.

    ``Settings`` wins for the runtime bounds so deployment can tighten them
    without editing the YAML. The YAML values are still validated against a
    minimum so a mis-set env can never remove the safety bounds entirely.
    """
    raw = m9_config()
    constraints = dict(raw.get("constraints") or {})
    delimiters = dict(raw.get("delimiters") or {})
    tasks = [t.get("id") for t in (raw.get("tasks") or []) if t.get("id")]
    if not tasks:
        tasks = [str(t.get("id")) for t in (_M9_DEFAULTS["tasks"] or [])]

    grounding_raw = raw.get("grounding_rules")
    if grounding_raw is None:
        grounding_raw = list(_M9_DEFAULTS["grounding_rules"].values())
    grounding_rules: dict[str, str] = {}
    if isinstance(grounding_raw, dict):
        grounding_rules = {str(k): str(v) for k, v in grounding_raw.items()}
    elif isinstance(grounding_raw, (list, tuple)):
        for item in grounding_raw:
            text = str(item)
            key, _, value = text.partition(":")
            if key.strip():
                grounding_rules[key.strip()] = value.strip()
            else:
                grounding_rules[f"R{len(grounding_rules) + 1}"] = text.strip()

    forbidden_raw = raw.get("forbidden_result_terms")
    if forbidden_raw is None:
        forbidden_raw = list(_M9_DEFAULTS["forbidden_result_terms"])

    max_input_chars = int(constraints.get("max_input_chars", 50000))
    max_output_tokens = int(constraints.get("max_output_tokens", 2048))
    timeout_seconds = float(constraints.get("timeout_seconds", 45.0))
    max_retries_settings = 1

    if settings is not None:
        max_input_chars = max(1000, int(settings.gemini_max_input_chars))
        max_output_tokens = max(64, int(settings.gemini_max_output_tokens))
        timeout_seconds = max(1.0, float(settings.gemini_timeout_seconds))
        max_retries_settings = max(0, int(settings.gemini_max_retries))

    return AIConfig(
        configuration_id=str(raw.get("ai_configuration_id", "AI-M9-001")),
        configuration_version=int(raw.get("ai_configuration_version", 1)),
        name=str(raw.get("name", "Evidence-Grounded Scientific Copilot")),
        provider=str(raw.get("provider", "gemini")),
        prompt_version=str(raw.get("prompt_version", "M9-SYSTEM-001")),
        evidence_schema_version=str(raw.get("evidence_schema_version", "M9-EVIDENCE-001")),
        begin_delimiter=str(delimiters.get("begin", "BEGIN CHANDRASUTRA EVIDENCE")),
        end_delimiter=str(delimiters.get("end", "END CHANDRASUTRA EVIDENCE")),
        forbidden_result_terms=tuple(str(t) for t in forbidden_raw),
        grounding_rules=grounding_rules,
        task_ids=tuple(tasks),
        max_input_chars=max_input_chars,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        rate_limit_per_minute=max(1, int(constraints.get("rate_limit_per_minute", 30))),
        max_sessions=max(1, int(constraints.get("max_sessions", 200))),
        session_ttl_seconds=max(60, int(constraints.get("session_ttl_seconds", 3600))),
        digest_algorithm=str(constraints.get("evidence_digest_algorithm", "sha256")),
        store_prompts=bool(constraints.get("store_prompts", False)),
        store_responses=bool(constraints.get("store_responses", False)),
        source=str(raw.get("source", "")),
        extras={"max_retries": max_retries_settings},
    )


__all__ = ["AIConfig", "load_ai_config", "DEFAULT_POSSIBLE_MILESTONES"]
