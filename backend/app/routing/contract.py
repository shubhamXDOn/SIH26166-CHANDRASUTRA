"""M6 adaptive matcher router — payload contract and honesty rules.

Canonical error codes, decision states and the vocabulary guard. The M6
router is the sole layer that owns explicit matcher selection (as a route,
never a scientific confidence); the artifact must be unambiguous about:

    * what was consumed (pair, processing readiness, M5 condition profile),
    * which rule matched and why (every evaluated predicate recorded),
    * what was actually executed (primary / fallback) vs requested,
    * that this is a deterministic policy decision with ``scientifically_tuned
      == false`` and NO confidence/accuracy claim.
"""

from __future__ import annotations

from typing import Any

# --- documented error codes ------------------------------------------------
PROCESSING_NOT_RUN = "PROCESSING_NOT_RUN"
PROCESS_NOT_READY = "PROCESS_NOT_READY"
CONDITION_NOT_AVAILABLE = "CONDITION_NOT_AVAILABLE"
MATCHER_NOT_AVAILABLE = "MATCHER_NOT_AVAILABLE"
NO_AVAILABLE_MATCHER = "NO_AVAILABLE_MATCHER"
INVALID_INPUT = "INVALID_INPUT"
ROUTING_FAILED = "ROUTING_FAILED"

ERROR_CODES: tuple[str, ...] = (
    PROCESSING_NOT_RUN,
    PROCESS_NOT_READY,
    CONDITION_NOT_AVAILABLE,
    MATCHER_NOT_AVAILABLE,
    NO_AVAILABLE_MATCHER,
    INVALID_INPUT,
    ROUTING_FAILED,
)

# --- states ----------------------------------------------------------------
# Routing decision state: what the router decided for this pair+profile.
BLOCKED = "BLOCKED"        # a precondition failed (honest block, never faked)
ABSTAIN = "ABSTAIN"        # no usable matcher for the routed route
ROUTED = "ROUTED"          # a route (primary + fallback) was produced

ROUTING_STATES: tuple[str, ...] = (BLOCKED, ABSTAIN, ROUTED)

# API decision status vocabulary (mirrors the task contract).
ROUTING_SUCCESS = "ROUTING_SUCCESS"
BLOCKED_STATUS = "BLOCKED"
ABSTAIN_STATUS = "ABSTAIN"
EXECUTION_STARTED = "EXECUTION_STARTED"
FAILED = "FAILED"

DECISION_STATUSES: tuple[str, ...] = (
    ROUTING_SUCCESS,
    BLOCKED_STATUS,
    ABSTAIN_STATUS,
    EXECUTION_STARTED,
    FAILED,
)

# --- fallback reasons (recorded, never silent) ------------------------------
PRIMARY_MATCHER_UNAVAILABLE = "PRIMARY_MATCHER_UNAVAILABLE"
EMPTY_CANDIDATE_OUTPUT = "EMPTY_CANDIDATE_OUTPUT"
FAILED_RUN = "FAILED_RUN"

FALLBACK_REASONS: tuple[str, ...] = (
    PRIMARY_MATCHER_UNAVAILABLE,
    EMPTY_CANDIDATE_OUTPUT,
    FAILED_RUN,
)

# --- modes -----------------------------------------------------------------

class RoutingMode:
    """The two routing arms. ADAPTIVE inspects condition facts; the
    FIXED_BASELINE ablation arm never does (matcher predetermined)."""

    ADAPTIVE = "ADAPTIVE"
    FIXED_BASELINE = "FIXED_BASELINE"


def routing_modes() -> tuple[str, ...]:
    return (RoutingMode.ADAPTIVE, RoutingMode.FIXED_BASELINE)


# --- forbidden vocabulary ---------------------------------------------------
# Words the router itself owns: route/primary/fallback are fine; these phrases
# are not (they imply a recommendation, a best pick or a confidence).
FORBIDDEN_VOCABULARY: tuple[str, ...] = (
    "selected_matcher",
    "recommended_matcher",
    "best_matcher",
    "routing_decision",
    "confidence",
)


def forbidden_vocabulary_hit(text: str) -> str | None:
    lower = text.lower()
    for word in FORBIDDEN_VOCABULARY:
        if word in lower:
            return word
    return None


def assert_artifact_vocabulary_safe(payload: dict[str, Any]) -> None:
    """Loudly reject artifacts that leak the router-only vocabulary in a field
    name path. Values such as route_explanation are allowed to quote the rule
    model; the check targets field names only."""
    import json as _json

    def _walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                hit = forbidden_vocabulary_hit(str(key))
                if hit is not None:
                    raise ValueError(
                        f"M6 routing artifact must never emit a field named "
                        f"'{prefix}{key}' (matched forbidden vocabulary "
                        f"'{hit}'). The router owns route/primary/fallback; "
                        "it never emits selection/confidence vocabulary."
                    )
                _walk(value, f"{prefix}{key}.")
        elif isinstance(node, list):
            for item in node:
                _walk(item, prefix)

    _walk(payload)
    # Structural guarantees shared by every M6 artifact (a failed run keeps
    # ``decision`` null but still present).
    assert "decision" in payload, "missing decision"
    decision = payload.get("decision")
    if decision is not None:
        assert isinstance(decision, dict) and "state" in decision, "missing decision.state"
        assert "matched_rule" in decision, "missing decision.matched_rule"


_LICENSE = (
    "Routing decisions are deterministic policy outcomes computed from the M2 "
    "processing readiness state and the M5 condition profile under the "
    "registered AR-M6-001 configuration (scientifically_tuned: false). They "
    "are an engineering routing step, never a scientific accuracy statement, "
    "confidence value or quality verdict. FIXED_BASELINE arms intentionally "
    "ignore condition facts for comparative analysis."
)

# --- license ----------------------------------------------------------------

def license_text() -> str:
    return _LICENSE


__all__ = [
    "PROCESSING_NOT_RUN", "PROCESS_NOT_READY", "CONDITION_NOT_AVAILABLE",
    "MATCHER_NOT_AVAILABLE", "NO_AVAILABLE_MATCHER", "INVALID_INPUT",
    "ROUTING_FAILED", "ERROR_CODES",
    "BLOCKED", "ABSTAIN", "ROUTED", "ROUTING_STATES",
    "ROUTING_SUCCESS", "BLOCKED_STATUS", "ABSTAIN_STATUS", "EXECUTION_STARTED",
    "FAILED", "DECISION_STATUSES",
    "PRIMARY_MATCHER_UNAVAILABLE", "EMPTY_CANDIDATE_OUTPUT", "FAILED_RUN",
    "FALLBACK_REASONS",
    "RoutingMode", "routing_modes",
    "FORBIDDEN_VOCABULARY", "forbidden_vocabulary_hit",
    "assert_artifact_vocabulary_safe", "license_text",
]