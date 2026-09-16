"""M3 matcher configuration (registered, explicit, inspectable).

Reproducibility contract:
    Pair ID + Processing Configuration ID + Matcher Configuration ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import m3_config


def _path(params: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    node: Any = params
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


@dataclass
class MatcherConfig:
    """Snapshot of the M3 engineering configuration.

    ``parameters`` is exactly what the matching run executed with and is
    written into every matching manifest for reproducibility.
    """

    configuration_id: str
    configuration_version: int
    name: str
    source_reference: str
    parameters: dict[str, Any] = field(default_factory=dict)

    # -- typed parameter readers --------------------------------------------
    def p(self, *keys: str, default: Any = None) -> Any:
        return _path(self.parameters, list(keys), default)

    @property
    def max_runtime_seconds(self) -> float:
        return float(self.p("execution", "max_runtime_seconds", default=45.0))

    @property
    def max_features(self) -> int:
        return int(self.p("execution", "max_features", default=4000))

    @property
    def max_tile_area_px(self) -> int:
        return int(self.p("execution", "max_tile_area_px", default=400000))

    @property
    def border_margin_px(self) -> int:
        return int(self.p("execution", "border_margin_px", default=4))

    @property
    def minimum_candidates(self) -> int:
        return int(self.p("minimum_candidates", default=8))

    @property
    def fallback_enabled(self) -> bool:
        return bool(self.p("fallback", "enabled", default=True))

    @property
    def fallback_max_attempts(self) -> int:
        return int(self.p("fallback", "max_attempts", default=2))

    def detector_params(self, strategy: str) -> dict[str, Any]:
        return dict(self.p(strategy, "detector", default={}) or {})

    def matching_params(self, strategy: str) -> dict[str, Any]:
        return dict(self.p(strategy, "matching", default={}) or {})

    def scoring_params(self) -> dict[str, Any]:
        return dict(self.p("routing", "scoring", default={}) or {})

    def constraint_params(self) -> dict[str, Any]:
        return dict(self.p("routing", "constraints", default={}) or {})

    def as_manifest_snapshot(self) -> dict:
        """Public, JSON-safe snapshot recorded in the matching manifest."""
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "source_reference": self.source_reference,
            "parameters": self.parameters,
        }


def load_matcher_config(configuration_id: str | None = None) -> MatcherConfig:
    """Load the registered M3 matcher configuration (MC-M3-001).

    Unknown Configuration IDs are rejected loudly — no silent fallback to a
    different configuration than the one requested.
    """
    raw = m3_config()
    known_id = raw.get("configuration_id", "MC-M3-001")
    requested = (configuration_id or known_id).strip()
    if requested != known_id:
        raise ValueError(
            f"Unknown matcher configuration '{requested}'. The only registered "
            f"M3 configuration is '{known_id}'.",
        )
    return MatcherConfig(
        configuration_id=known_id,
        configuration_version=int(raw.get("configuration_version", 1)),
        name=str(raw.get("name", "Adaptive Matcher Strategy Selection & Candidate Correspondences")),
        source_reference=str(raw.get("source_reference", "")),
        parameters=dict(raw.get("defaults") or {}),
    )


def configurations_public() -> list[dict]:
    """The runnable configurations exposed by /api/matching/configurations.

    Lists every registered strategy (including declared-but-unavailable ones)
    so the honest boundary is visible; ``available`` flags come from the
    adapter registry, never fabricated.
    """
    from .adapters import all_matchers

    try:
        cfg = load_matcher_config()
    except ValueError:
        return []
    return [
        {
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "name": cfg.name,
            "source_reference": cfg.source_reference,
            "display_only": {
                "execution": {
                    "max_runtime_seconds": cfg.max_runtime_seconds,
                    "max_features": cfg.max_features,
                    "max_tile_area_px": cfg.max_tile_area_px,
                },
                "minimum_candidates": cfg.minimum_candidates,
                "fallback": {
                    "enabled": cfg.fallback_enabled,
                    "max_attempts": cfg.fallback_max_attempts,
                },
                "strategies": [
                    a.capability_public()
                    for a in all_matchers()
                ],
                "note": "Routing scores are evidence-based routing decisions (what to try), never a scientific quality verdict.",
            },
        }
    ]