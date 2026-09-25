"""M6 adaptive matcher router — configuration (registered, explicit).

Parses and validates the registered AR-M6-001 configuration (YAML section
``m6_routing`` via ``m6_routing_config``). Validation is loud: unknown rule
fields, unknown operators, unknown matcher ids and unknown condition-view
fields fail configuration validation instead of silently mis-routing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import m6_routing_config
from .contract import routing_modes
from .predicates import OPERATORS
from .views import KNOWN_VIEW_FIELDS

# documented route actions
ACTION_ROUTED = "ROUTED"
ACTION_BLOCKED = "BLOCKED"
ACTION_ABSTAIN = "ABSTAIN"
ACTIONS: tuple[str, ...] = (ACTION_ROUTED, ACTION_BLOCKED, ACTION_ABSTAIN)

_MATCH_SEMANTICS: tuple[str, ...] = ("all", "any")


@dataclass
class RoutingRule:
    """One deterministic rule. ``when`` is evaluated against the condition
    view; empty ``when`` is an unconditional (always-true) rule."""

    id: str
    priority: int
    modes: list[str]
    match: str  # "all" | "any"
    when: list[dict[str, Any]]
    action: str  # ROUTED | BLOCKED | ABSTAIN
    primary_matcher: str | None = None
    fallback_matcher: str | None = None
    error_code: str | None = None
    explanation: str = ""

    def in_mode(self, mode: str) -> bool:
        return mode in self.modes

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "priority": self.priority,
            "modes": list(self.modes),
            "match": self.match,
            "when": list(self.when),
            "action": self.action,
            "primary_matcher": self.primary_matcher,
            "fallback_matcher": self.fallback_matcher,
            "error_code": self.error_code,
            "explanation": self.explanation,
        }


def _path(params: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    node: Any = params
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


@dataclass
class RoutingConfig:
    """Snapshot of the M6 adaptive router configuration (AR-M6-001).

    ``defaults`` is exactly the policy the router executed with and is
    embedded in every routing artifact for reproducibility.
    """

    configuration_id: str
    configuration_version: int
    name: str
    source_reference: str
    derived_rel: str = "metadata/m6_routing"
    scientifically_tuned: bool = False
    defaults: dict[str, Any] = field(default_factory=dict)
    rules: list[RoutingRule] = field(default_factory=list)

    def p(self, *keys: str, default: Any = None) -> Any:
        return _path(self.defaults, list(keys), default)

    @property
    def modes(self) -> list[str]:
        return [str(m) for m in list(self.p("modes", default=routing_modes()))]

    @property
    def default_mode(self) -> str:
        return str(self.p("default_mode", default="ADAPTIVE"))

    @property
    def max_fallback_attempts(self) -> int:
        return int(self.p("execution", "max_fallback_attempts", default=1))

    @property
    def forbidden_vocabulary(self) -> list[str]:
        return [str(v) for v in list(self.p("forbidden_vocabulary", default=[]))]

    def appearance_policy(self) -> dict[str, float]:
        app = self.p("policy", "appearance", default={}) or {}
        return {
            "difference_low_lt": float(app.get("difference_low_lt", 0.25)),
            "difference_high_ge": float(app.get("difference_high_ge", 0.55)),
        }

    def scale_policy(self) -> dict[str, float]:
        sc = self.p("policy", "scale", default={}) or {}
        return {
            "gsd_ratio_medium_ge": float(sc.get("gsd_ratio_medium_ge", 1.35)),
            "gsd_ratio_large_ge": float(sc.get("gsd_ratio_large_ge", 2.0)),
        }

    def as_manifest_snapshot(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "source_reference": self.source_reference,
            "scientifically_tuned": self.scientifically_tuned,
            "parameters": self.defaults,
        }


def _matcher_ids(cfg: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    matchers = cfg.get("matchers") or {}
    for group in ("classical", "deep"):
        for matcher_id, enabled in (matchers.get(group) or {}).items():
            if bool(enabled):
                ids.add(str(matcher_id))
    return ids


def validate_rules(rules: list[dict[str, Any]], *, known_ids: set[str], mode_list: list[str]) -> list[RoutingRule]:
    """Validate + normalize the configured rules into RoutingRule objects.

    Loud failures (ValueError) for: unknown fields, unknown operators,
    unknown matcher ids, unknown modes, invalid actions, non-numeric
    priorities and empty rule ids.
    """
    if not rules:
        raise ValueError("m6_routing: at least one rule is required.")
    seen_ids: set[str] = set()
    parsed: list[RoutingRule] = []
    for raw in rules:
        rule_id = str(raw.get("id") or "").strip()
        if not rule_id:
            raise ValueError("m6_routing: rule without an id is invalid.")
        if rule_id in seen_ids:
            raise ValueError(f"m6_routing: duplicate rule id {rule_id!r}.")
        seen_ids.add(rule_id)

        modes = [str(m).strip() for m in list(raw.get("modes") or [])]
        for mode in modes:
            if mode not in mode_list:
                raise ValueError(
                    f"m6_routing rule {rule_id!r} lists unknown mode {mode!r}. "
                    f"Allowed: {mode_list}."
                )
        if not modes:
            raise ValueError(f"m6_routing rule {rule_id!r} must list at least one mode.")

        try:
            priority = int(raw.get("priority"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"m6_routing rule {rule_id!r}: priority must be an integer.") from exc

        match = str(raw.get("match") or "all").strip()
        if match not in _MATCH_SEMANTICS:
            raise ValueError(
                f"m6_routing rule {rule_id!r}: match must be one of "
                f"{_MATCH_SEMANTICS}; got {match!r}."
            )

        action = str(raw.get("action") or "").strip().upper()
        if action not in ACTIONS:
            raise ValueError(
                f"m6_routing rule {rule_id!r}: unknown action {action!r}. "
                f"Allowed: {ACTIONS}."
            )

        when = raw.get("when")
        if when is None:
            when = []
        if not isinstance(when, list):
            raise ValueError(f"m6_routing rule {rule_id!r}: 'when' must be a list.")
        for i, predicate in enumerate(when):
            _validate_predicate(predicate, rule_id, i, known_fields=KNOWN_VIEW_FIELDS)

        primary = raw.get("primary_matcher")
        fallback = raw.get("fallback_matcher")
        if action == ACTION_ROUTED:
            if not primary or str(primary) not in known_ids:
                raise ValueError(
                    f"m6_routing rule {rule_id!r}: routed rules require a known "
                    f"primary_matcher; got {primary!r} (known: {sorted(known_ids)})."
                )
            if fallback and str(fallback) not in known_ids:
                raise ValueError(
                    f"m6_routing rule {rule_id!r}: unknown fallback_matcher "
                    f"{fallback!r}."
                )
        else:
            if primary or fallback:
                raise ValueError(
                    f"m6_routing rule {rule_id!r}: non-ROUTED rules must not "
                    "carry primary/fallback matchers."
                )

        error_code = raw.get("error_code")
        if action in (ACTION_BLOCKED, ACTION_ABSTAIN) and not error_code:
            raise ValueError(
                f"m6_routing rule {rule_id!r}: {action} rules require an error_code."
            )

        parsed.append(RoutingRule(
            id=rule_id,
            priority=priority,
            modes=modes,
            match=match,
            when=list(when),
            action=action,
            primary_matcher=str(primary) if primary else None,
            fallback_matcher=str(fallback) if fallback else None,
            error_code=str(error_code) if error_code else None,
            explanation=str(raw.get("explanation") or ""),
        ))

    parsed.sort(key=lambda r: r.priority, reverse=True)
    return parsed


def _validate_predicate(predicate: Any, rule_id: str, index: int, *, known_fields: set[str]) -> None:
    if not isinstance(predicate, dict):
        raise ValueError(
            f"m6_routing rule {rule_id!r}: predicate #{index} must be a dict "
            "with 'field', 'operator' and optionally 'value'."
        )
    field = predicate.get("field")
    if not isinstance(field, str) or field not in known_fields:
        raise ValueError(
            f"m6_routing rule {rule_id!r}: predicate field {field!r} is not a "
            "known condition/capability view field. Allowed fields are the "
            "registered M6 view keys."
        )
    op = predicate.get("operator")
    if op not in OPERATORS:
        raise ValueError(
            f"m6_routing rule {rule_id!r}: unknown operator {op!r}. "
            f"Allowed: {sorted(OPERATORS)}."
        )
    if "value" not in predicate and op not in ("exists",):
        raise ValueError(
            f"m6_routing rule {rule_id!r}: predicate #{index} needs a 'value' "
            f"for operator {op!r}."
        )


def load_routing_config(configuration_id: str | None = None) -> RoutingConfig:
    """Load + validate the registered M6 adaptive router configuration."""
    raw = m6_routing_config()
    known_id = raw.get("configuration_id", "AR-M6-001")
    requested = (configuration_id or known_id).strip()
    if requested != known_id:
        raise ValueError(
            f"Unknown M6 routing configuration '{requested}'. The only "
            f"registered configuration is '{known_id}'."
        )
    defaults = dict(raw.get("defaults") or {})
    mode_list = [str(m) for m in list(defaults.get("modes") or routing_modes())]
    known_ids = _matcher_ids(defaults)

    rules = validate_rules(list(defaults.get("rules") or []),
                           known_ids=known_ids, mode_list=mode_list)

    return RoutingConfig(
        configuration_id=known_id,
        configuration_version=int(raw.get("configuration_version", 1)),
        name=str(raw.get("name", "Adaptive Matcher Router — Deterministic, Evidence-based Matcher Selection")),
        source_reference=str(raw.get("source_reference", "")),
        derived_rel=str(raw.get("derived_rel", "metadata/m6_routing")),
        scientifically_tuned=bool(raw.get("scientifically_tuned", False)),
        defaults=defaults,
        rules=rules,
    )


def configurations_public() -> list[dict[str, Any]]:
    """The runnable M6 configuration exposed by the capabilities endpoint."""
    try:
        cfg = load_routing_config()
    except ValueError:
        return []
    appearance = cfg.appearance_policy()
    scale = cfg.scale_policy()
    return [
        {
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "name": cfg.name,
            "source_reference": cfg.source_reference,
            "display_only": {
                "modes": cfg.modes,
                "rules": [r.snapshot() for r in cfg.rules],
                "appearance_policy": appearance,
                "scale_policy": scale,
                "fallback_policy": cfg.p("fallback", default={}),
                "execution": {"max_fallback_attempts": cfg.max_fallback_attempts},
                "note": (
                    "Deterministic policy routing over M5 condition facts "
                    "(scientifically_tuned: false). Never a scientific "
                    "accuracy claim or confidence value."
                ),
            },
        }
    ]


__all__ = [
    "RoutingConfig",
    "RoutingRule",
    "load_routing_config",
    "configurations_public",
    "validate_rules",
    "ACTIONS",
]