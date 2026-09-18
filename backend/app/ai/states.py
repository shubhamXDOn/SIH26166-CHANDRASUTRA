"""M9 AI layer states and task identifiers.

The AI layer is explanatory only. These states make every real outcome
explicit — there is no ambiguous "maybe" and no fabricated success:

    NOT_CONFIGURED   GEMINI_API_KEY is empty; the AI layer is present but off
    READY            configured and reachable, no request in flight
    RUNNING          a genuine provider request is in flight
    COMPLETE         a validated, evidence-grounded answer was produced
    FAILED           an unrecoverable internal AI-layer failure
    TIMEOUT          the provider did not answer within the configured budget
    RATE_LIMITED     the provider (or local limiter) rejected the request
    PROVIDER_ERROR   the provider returned an error / unreachable
    INVALID_RESPONSE the provider output failed validation and was discarded
    BLOCKED          the request was refused by the evidence-grounding policy
"""

from __future__ import annotations

from enum import Enum


class AIServiceState(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    BLOCKED = "BLOCKED"


# Historical M0 alias: the original service exposed AIServiceStatus with a
# subset of these values. Kept so existing imports keep working.
AIServiceStatus = AIServiceState


class AITask(str, Enum):
    EXPLAIN = "explain"
    EXPLAIN_FAILURE = "explain-failure"
    EXPLAIN_ROUTING = "explain-routing"
    SUMMARIZE_EXPERIMENT = "summarize-experiment"
    CHAT = "chat"


TASK_LABELS: dict[str, str] = {
    AITask.EXPLAIN.value: "Explain pair analysis",
    AITask.EXPLAIN_FAILURE.value: "Explain failure or blocker",
    AITask.EXPLAIN_ROUTING.value: "Explain adaptive matcher routing",
    AITask.SUMMARIZE_EXPERIMENT.value: "Summarize experiment report",
    AITask.CHAT.value: "Ask about a pair",
}

TERMINAL_STATES: frozenset[str] = frozenset({
    AIServiceState.COMPLETE.value,
    AIServiceState.FAILED.value,
    AIServiceState.TIMEOUT.value,
    AIServiceState.RATE_LIMITED.value,
    AIServiceState.PROVIDER_ERROR.value,
    AIServiceState.INVALID_RESPONSE.value,
    AIServiceState.BLOCKED.value,
    AIServiceState.NOT_CONFIGURED.value,
})


def is_terminal(state: AIServiceState | str) -> bool:
    value = state.value if isinstance(state, AIServiceState) else str(state)
    return value in TERMINAL_STATES


__all__ = [
    "AIServiceState",
    "AIServiceStatus",
    "AITask",
    "TASK_LABELS",
    "TERMINAL_STATES",
    "is_terminal",
]
