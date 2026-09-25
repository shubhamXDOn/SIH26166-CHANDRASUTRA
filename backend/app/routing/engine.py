"""M6 adaptive matcher router — deterministic routing engine (pure).

The engine turns a condition view + capability view + validated rule set into
a routing decision. It is pure and testable: no I/O, no RNG, no time. The
service layer supplies the views; the engine owns rule evaluation, capability
resolution and the decision hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .config import RoutingRule, RoutingConfig
from .contract import (
    ABSTAIN,
    ABSTAIN_STATUS,
    BLOCKED,
    BLOCKED_STATUS,
    DECISION_STATUSES,
    MATCHER_NOT_AVAILABLE,
    NO_AVAILABLE_MATCHER,
    PRIMARY_MATCHER_UNAVAILABLE,
    PROCESSING_NOT_RUN,
    ROUTED,
    ROUTING_SUCCESS,
)
from .predicates import predicate_outcome
from .views import KNOWN_VIEW_FIELDS


@dataclass
class RoutingDecision:
    """A fully-resolved routing decision (pure engine output).

    ``state`` is the routing decision state: ROUTED / BLOCKED / ABSTAIN.
    ``decision_status`` maps to the API vocabulary
    (ROUTING_SUCCESS / BLOCKED / ABSTAIN). ``primary_matcher`` is the
    matcher that WILL be executed first (already capability-resolved);
    ``requested_primary_matcher`` is the matcher the matched rule asked for.
    """

    state: str = BLOCKED
    decision_status: str = BLOCKED_STATUS
    matched_rule_id: str | None = None
    rule_priority: int | None = None
    requested_primary_matcher: str | None = None
    requested_fallback_matcher: str | None = None
    primary_matcher: str | None = None
    fallback_matcher: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    route_explanation: str = ""
    predicate_results: dict[str, Any] = field(default_factory=dict)
    matched_rule: dict[str, Any] = field(default_factory=dict)
    decision_hash: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "decision_status": self.decision_status,
            "matched_rule_id": self.matched_rule_id,
            "rule_priority": self.rule_priority,
            "requested_primary_matcher": self.requested_primary_matcher,
            "requested_fallback_matcher": self.requested_fallback_matcher,
            "primary_matcher": self.primary_matcher,
            "fallback_matcher": self.fallback_matcher,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "error_code": self.error_code,
            "error_detail": self.error_detail,
            "route_explanation": self.route_explanation,
            "predicate_results": self.predicate_results,
            "matched_rule": self.matched_rule,
            "decision_hash": self.decision_hash,
            "capabilities": self.capabilities,
        }


def _rule_matches(rule: RoutingRule, view: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Evaluate a rule's predicates. Returns (matched, evaluated_predicates).

    Evaluated predicates are recorded for every rule checked, in order, so
    the artifact is auditable even when the rule does not match.
    """
    outcomes: list[dict[str, Any]] = []
    if not rule.when:
        return True, outcomes
    for predicate in rule.when:
        outcome = predicate_outcome(view, predicate)
        outcomes.append(outcome)
    if rule.match == "any":
        matched = any(o["result"] for o in outcomes)
    else:  # "all" (default)
        matched = all(o["result"] for o in outcomes)
    return bool(matched), outcomes


def _available(capability_view: dict[str, Any], matcher_id: str | None) -> bool:
    if not matcher_id:
        return False
    return bool(capability_view.get(f"capability.{matcher_id}", False))


def _capability_record(capability_view: dict[str, Any]) -> dict[str, Any]:
    return {
        matcher_id: _available(capability_view, matcher_id)
        for matcher_id in ("sift", "orb", "akaze", "superpoint_superglue", "loftr")
    }


def _human_route_explanation(
    rule: RoutingRule,
    state: str,
    requested_primary: str | None,
    requested_fallback: str | None,
    primary: str | None,
    fallback_used: bool,
    fallback_reason: str | None,
    outcomes: list[dict[str, Any]],
) -> str:
    bits = [f"Rule {rule.id} (priority {rule.priority}, {rule.action})"]
    if outcomes:
        facts = "; ".join(
            f"{o['field']}={o['observed']} ({o['operator']} {o['value']}) {'TRUE' if o['result'] else 'FALSE'}"
            for o in outcomes
        )
        bits.append(f"predicates: {facts}")
    if state == ROUTED:
        bits.append(f"requested primary={requested_primary}, fallback={requested_fallback}")
        if fallback_used:
            bits.append(f"executed primary={primary} (fallback used: {fallback_reason})")
        else:
            bits.append(f"executed primary={primary}, fallback kept={requested_fallback}")
    elif state == BLOCKED:
        bits.append(f"blocked ({rule.error_code})")
    else:
        bits.append("abstained — no usable matcher for the routed route")
    if rule.explanation:
        bits.append(f"policy rationale: {rule.explanation}")
    return " | ".join(bits)


def _decision_hash(
    config: RoutingConfig,
    mode: str,
    matched_rule: RoutingRule | None,
    decision: "RoutingDecision",
    view: dict[str, Any],
    capability_view: dict[str, Any],
) -> str:
    """Deterministic hash over the routing inputs + decision (not time/RNG).

    Changing ANY of: policy/rules (config), mode, condition view values,
    capability availability or the resolved route changes the hash — useful
    for detecting drift between routing decisions.
    """
    rule_ids = "\n".join(
        f"{r.id}|{r.priority}|{r.action}|{r.primary_matcher}|{r.fallback_matcher}|{json.dumps(r.when, sort_keys=True, default=str)}"
        for r in config.rules
    )
    relevant_fields = sorted(f for f in KNOWN_VIEW_FIELDS if f in view)
    condition_snapshot = {f: view.get(f) for f in relevant_fields}
    capability_snapshot = _capability_record(capability_view)
    payload = {
        "configuration_id": config.configuration_id,
        "configuration_version": config.configuration_version,
        "rules": rule_ids,
        "mode": mode,
        "matched_rule_id": decision.matched_rule_id,
        "state": decision.state,
        "primary_matcher": decision.primary_matcher,
        "fallback_matcher": decision.fallback_matcher,
        "fallback_used": decision.fallback_used,
        "fallback_reason": decision.fallback_reason,
        "condition_snapshot": condition_snapshot,
        "capability_snapshot": capability_snapshot,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def route(
    view: dict[str, Any],
    capability_view: dict[str, Any],
    config: RoutingConfig,
    mode: str,
) -> RoutingDecision:
    """Produce a deterministic routing decision for one mode.

    ``view`` is the canonical condition view; ``capability_view`` the live
    matcher availability view; ``config`` the validated router configuration.
    """
    if mode not in config.modes:
        return RoutingDecision(
            state=BLOCKED,
            decision_status=BLOCKED_STATUS,
            error_code=MATCHER_NOT_AVAILABLE,
            error_detail=f"mode {mode!r} is not enabled in configuration {config.configuration_id}.",
            route_explanation=(
                f"Mode {mode} is not enabled in configuration "
                f"{config.configuration_id}; no rule set applies."
            ),
        )

    enabled = [r for r in sorted(config.rules, key=lambda r: r.priority, reverse=True) if r.in_mode(mode)]
    if not enabled:
        return RoutingDecision(
            state=BLOCKED,
            decision_status=BLOCKED_STATUS,
            error_code=MATCHER_NOT_AVAILABLE,
            error_detail=f"No routing rules are enabled for mode {mode!r}.",
            route_explanation=f"No routing rules are enabled for mode {mode}; routing is blocked.",
        )

    evaluated: dict[str, Any] = {}
    matched_rule: RoutingRule | None = None
    matched_outcomes: list[dict[str, Any]] = []

    for rule in enabled:
        is_match, outcomes = _rule_matches(rule, view)
        evaluated[rule.id] = {
            "matched": bool(is_match),
            "predicates": outcomes,
            "action": rule.action,
        }
        if is_match:
            matched_rule = rule
            matched_outcomes = outcomes
            break

    # capability record captured for hash + artifact even when blocked
    capability_record = _capability_record(capability_view)

    if matched_rule is None:
        return RoutingDecision(
            state=ABSTAIN,
            decision_status=ABSTAIN_STATUS,
            error_code=NO_AVAILABLE_MATCHER,
            error_detail="No routing rule matched the condition profile.",
            route_explanation="No routing rule matched the condition profile; abstaining.",
            predicate_results=evaluated,
            capabilities=capability_record,
        )

    if matched_rule.action == BLOCKED:
        decision = RoutingDecision(
            state=BLOCKED,
            decision_status=BLOCKED_STATUS,
            matched_rule_id=matched_rule.id,
            rule_priority=matched_rule.priority,
            error_code=matched_rule.error_code,
            error_detail=matched_rule.explanation,
            route_explanation=_human_route_explanation(
                matched_rule, BLOCKED, None, None, None, False, None, matched_outcomes
            ),
            predicate_results=evaluated,
            matched_rule=matched_rule.snapshot(),
            capabilities=capability_record,
        )
        decision.decision_hash = _decision_hash(config, mode, matched_rule, decision, view, capability_view)
        return decision

    if matched_rule.action == ABSTAIN:
        decision = RoutingDecision(
            state=ABSTAIN,
            decision_status=ABSTAIN_STATUS,
            matched_rule_id=matched_rule.id,
            rule_priority=matched_rule.priority,
            error_code=matched_rule.error_code or NO_AVAILABLE_MATCHER,
            error_detail=matched_rule.explanation or "Rule chose to abstain.",
            route_explanation=_human_route_explanation(
                matched_rule, ABSTAIN, None, None, None, False, None, matched_outcomes
            ),
            predicate_results=evaluated,
            matched_rule=matched_rule.snapshot(),
            capabilities=capability_record,
        )
        decision.decision_hash = _decision_hash(config, mode, matched_rule, decision, view, capability_view)
        return decision

    # ---- ROUTED: capability resolution ------------------------------------
    requested_primary = matched_rule.primary_matcher
    requested_fallback = matched_rule.fallback_matcher

    primary_ok = _available(capability_view, requested_primary)
    fallback_ok = _available(capability_view, requested_fallback)

    fallback_used = False
    fallback_reason: str | None = None
    primary: str | None = requested_primary
    fallback: str | None = requested_fallback
    state = ROUTED
    status = ROUTING_SUCCESS
    error_code: str | None = None
    error_detail: str | None = None

    if primary_ok:
        fallback = requested_fallback if fallback_ok else None
    elif fallback_ok:
        primary = requested_fallback
        fallback = requested_fallback
        fallback_used = True
        fallback_reason = PRIMARY_MATCHER_UNAVAILABLE
    else:
        state = ABSTAIN
        status = ABSTAIN_STATUS
        primary = None
        fallback = None
        fallback_used = False
        error_code = NO_AVAILABLE_MATCHER
        error_detail = (
            f"Neither requested primary ({requested_primary!r}) nor configured "
            f"fallback ({requested_fallback!r}) is available for pair/mode {mode}."
        )

    decision = RoutingDecision(
        state=state,
        decision_status=status,
        matched_rule_id=matched_rule.id,
        rule_priority=matched_rule.priority,
        requested_primary_matcher=requested_primary,
        requested_fallback_matcher=requested_fallback,
        primary_matcher=primary,
        fallback_matcher=fallback,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        error_code=error_code,
        error_detail=error_detail,
        route_explanation=_human_route_explanation(
            matched_rule, state, requested_primary, requested_fallback,
            primary, fallback_used, fallback_reason, matched_outcomes,
        ),
        predicate_results=evaluated,
        matched_rule=matched_rule.snapshot(),
        capabilities=capability_record,
    )
    decision.decision_hash = _decision_hash(config, mode, matched_rule, decision, view, capability_view)
    return decision


def evaluator(view: dict[str, Any], capability_view: dict[str, Any],
              config: RoutingConfig, mode: str) -> RoutingDecision:
    """Public entry point (alias of :func:`route`)."""
    return route(view, capability_view, config, mode)


__all__ = [
    "RoutingDecision",
    "route",
    "evaluator",
]