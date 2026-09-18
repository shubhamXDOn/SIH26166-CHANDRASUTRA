"""M8 adaptive expansion routing (Section 8/9).

The M8 router extends the M3 routing decision per match tile by consuming:
    * the M3 routing decision (decisions.json) — the selected classical strategy,
    * the M2 condition evidence per tile (texture, contrast, valid fraction),
    * the honest M8 capability probe (which matchers exist and are available).

Routing outcomes are *categorical*: ``FEATURE_SCARCITY``,
``DEEP_MATCHER_AVAILABLE``, ... — never a numerical confidence/quality score.
Every outcome records a deterministic ``strategy_order`` so the runtime layer
tries primary then alternates and records ``fallback_used``/``fallback_reason``
truthfully.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

REASON_FEATURE_SCARCITY = "FEATURE_SCARCITY"
REASON_DEEP_MATCHER_AVAILABLE = "DEEP_MATCHER_AVAILABLE"
REASON_PREFERRED_DEEP = "PREFERRED_DEEP"
REASON_CLASSICAL_ONLY = "CLASSICAL_ONLY"
REASON_DEEP_ONLY = "DEEP_ONLY"
REASON_CLASSICAL_MANDATED = "CLASSICAL_MANDATED"
REASON_DEEP_MANDATED = "DEEP_MANDATED"
REASON_CLASSICAL_ADAPTIVE = "CLASSICAL_ADAPTIVE"
REASON_NO_ELIGIBLE = "NO_ELIGIBLE_MATCHER"


@dataclass
class M8StrategyOrder:
    tile_id: str
    mode: str  # AUTO | CLASSICAL_ONLY | DEEP_ONLY
    available_classical: list[str] = field(default_factory=list)
    available_deep: list[str] = field(default_factory=list)
    strategy_order: list[str] = field(default_factory=list)
    requested_strategy: str = ""
    reason: str = ""
    note: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def primary(self) -> str:
        return self.strategy_order[0] if self.strategy_order else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tile_id": self.tile_id,
            "mode": self.mode,
            "m3_proposed_strategy": self.context.get("m3_proposed_strategy"),
            "available_classical": list(self.available_classical),
            "available_deep": list(self.available_deep),
            "strategy_order": list(self.strategy_order),
            "requested_strategy": self.requested_strategy,
            "reason": self.reason,
            "note": self.note or "Routing is a what-to-try decision, never a confidence/quality verdict.",
        }


def route_tile(
    *,
    tile_id: str,
    m3_decision: dict[str, Any] | None,
    condition_view: dict[str, Any],
    available_classical: list[str],
    available_deep: list[str],
    preferred_matcher: str,
    mode: str,
    allow_classical: bool,
    allow_deep: bool,
    fallback_to_classical: bool,
    feature_scarcity_threshold: float = 0.35,
) -> M8StrategyOrder:
    """Decide the deterministic executed-strategy order for one match tile."""
    proposed = (m3_decision or {}).get("selected_strategy", "")
    classical = [s for s in available_classical]
    deep = [s for s in available_deep]
    order = M8StrategyOrder(
        tile_id=tile_id,
        mode=mode,
        available_classical=classical,
        available_deep=deep,
        context={"m3_proposed_strategy": proposed, "condition_view": condition_view},
    )
    mode = (mode or "AUTO").upper()
    if mode not in ("AUTO", "CLASSICAL_ONLY", "DEEP_ONLY"):
        mode = "AUTO"

    classical_ok = allow_classical and bool(classical)
    deep_ok = allow_deep and bool(deep)

    if mode == "CLASSICAL_ONLY":
        if not classical_ok:
            order.reason = REASON_NO_ELIGIBLE
            return order
        primary = proposed if proposed in classical else classical[0]
        order.requested_strategy = primary
        order.strategy_order = _ordered([primary], classical)
        order.reason = REASON_CLASSICAL_MANDATED
        return order

    if mode == "DEEP_ONLY":
        if not deep_ok:
            order.reason = REASON_NO_ELIGIBLE
            return order
        primary = _pick_deep(deep, preferred_matcher)
        order.requested_strategy = primary
        alternates = [] if not fallback_to_classical else classical
        order.strategy_order = _ordered([primary], deep + alternates)
        order.reason = REASON_DEEP_MANDATED
        return order

    # AUTO -----------------------------------------------------------------
    requested = proposed if proposed in classical else (classical[0] if classical else "")
    valid_fraction = float(condition_view.get("valid_fraction_a") or 0.0)
    scarcity = valid_fraction < feature_scarcity_threshold
    prefers_deep = _prefers_deep(preferred_matcher)
    if deep_ok and (scarcity or (prefers_deep and not classical)):
        primary = _pick_deep(deep, preferred_matcher)
        alternates = classical if fallback_to_classical else []
        order.requested_strategy = primary
        order.strategy_order = _ordered([primary], deep + alternates)
        order.reason = REASON_FEATURE_SCARCITY if scarcity else REASON_DEEP_MATCHER_AVAILABLE
        return order

    if classical_ok:
        primary = requested or classical[0]
        alternates = deep if deep_ok and fallback_to_classical else []
        order.requested_strategy = primary
        order.strategy_order = _ordered([primary], classical + alternates)
        order.reason = REASON_CLASSICAL_ADAPTIVE if requested else REASON_CLASSICAL_MANDATED
        return order

    if deep_ok:
        primary = _pick_deep(deep, preferred_matcher)
        order.requested_strategy = primary
        order.strategy_order = _ordered([primary], deep)
        order.reason = REASON_DEEP_MATCHER_AVAILABLE
        return order

    order.reason = REASON_NO_ELIGIBLE
    return order


def _ordered(primary: list[str], pool: list[str]) -> list[str]:
    out: list[str] = []
    for item in primary + pool:
        if item not in out:
            out.append(item)
    return out


def _pick_deep(available_deep: list[str], preferred_matcher: str) -> str:
    if preferred_matcher in ("superpoint_superglue", "loftr") and preferred_matcher in available_deep:
        return preferred_matcher
    candidates = [m for m in ("superpoint_superglue", "loftr") if m in available_deep]
    return candidates[0] if candidates else available_deep[0]


def _prefers_deep(preferred_matcher: str) -> bool:
    return bool(preferred_matcher in ("superpoint_superglue", "loftr", "auto"))