"""M6 — Adaptive Matcher Router (deterministic, evidence-based routing).

Routes M2-validated pairs (through their M5 condition profile) to a matcher
under an explicit, recorded policy. This layer:

    * consumes ONLY the M5 condition profile + processing readiness (never a
      matcher itself, never a scientific accuracy verdict);
    * is fully deterministic: the same processed pair, condition profile and
      configuration always produce the same decision hash;
    * records the matched rule, every evaluated predicate and the actual
      route; capability-gated fallback is recorded, never silent;
    * provides a FIXED_BASELINE ablation arm used to normalize ADAPTIVE
      comparisons — it never inspects condition facts.

The Router is the sole place that owns matcher selection. It routes by
DECISION; execution is a separate optional dispatch layer
(``RoutingService.execute``).
"""

from __future__ import annotations

from .service import RoutingService  # noqa: F401
from .engine import RoutingDecision, route, evaluator  # noqa: F401
from .config import RoutingConfig, load_routing_config  # noqa: F401
from .contract import RoutingMode, routing_modes, DECISION_STATUSES  # noqa: F401

__all__ = [
    "RoutingService",
    "RoutingDecision",
    "route",
    "evaluator",
    "RoutingConfig",
    "load_routing_config",
    "RoutingMode",
    "routing_modes",
    "DECISION_STATUSES",
]