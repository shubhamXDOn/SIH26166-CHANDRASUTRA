"""M9 AI request/response models.

The user-facing envelope for every successful AI task is stable:

    {
      "status": "COMPLETE",
      "request_id": "AIR-...",
      "task": "explain",
      "pair_id": "...",
      "answer": "...",
      "evidence": [{"claim": ..., "source_milestone": ..., "source_metric": ...}],
      "limitations": ["..."],
      "suggested_inspections": ["..."],
      "usage": {"input_tokens": "NOT_AVAILABLE", ...},
      "ai": {"configuration_id": "AI-M9-001", "prompt_version": "M9-SYSTEM-001",
             "evidence_schema_version": "M9-EVIDENCE-001", "evidence_digest": "sha256:..."},
      "created_at": "..."
    }

Failure, refusal and capability states are surfaced through the unified
backend error envelope (see :mod:`backend.app.errors`) — never as a fabricated
answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .states import AIServiceState


class AIRequest(BaseModel):
    """Flexible request body for all M9 AI tasks.

    Every field is optional at the transport layer so the capability check can
    run first (a NOT_CONFIGURED instance must report its true state regardless
    of the request body). Validation of the fields required for a specific
    task happens inside the handler once the service is configured.
    """

    pair_id: str = Field(default="", max_length=128)
    scope: str = Field(default="", max_length=64)
    question: str = Field(default="", max_length=4000)
    session_id: str = Field(default="", max_length=128)
    experiment_id: str = Field(default="", max_length=128)


@dataclass
class AIAnswer:
    """A validated, evidence-grounded answer (provider output already checked)."""

    answer: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    suggested_inspections: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
            "suggested_inspections": list(self.suggested_inspections),
        }


@dataclass
class AIResponse:
    """Complete result envelope returned to the API layer."""

    status: AIServiceState
    request_id: str
    task: str
    pair_id: str
    answer: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    suggested_inspections: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    ai: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status.value if isinstance(self.status, AIServiceState) else str(self.status),
            "request_id": self.request_id,
            "task": self.task,
            "pair_id": self.pair_id,
            "answer": self.answer,
            "evidence": list(self.evidence),
            "limitations": list(self.limitations),
            "suggested_inspections": list(self.suggested_inspections),
            "usage": dict(self.usage),
            "ai": dict(self.ai),
            "created_at": self.created_at,
        }
        if self.error:
            payload["error"] = dict(self.error)
        return payload


__all__ = ["AIRequest", "AIAnswer", "AIResponse"]
