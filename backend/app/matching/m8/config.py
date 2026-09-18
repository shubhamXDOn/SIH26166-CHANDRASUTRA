"""M8 deep-matching configuration (registered, explicit, inspectable).

Reproducibility contract (extends M7):
    Pair ID + M2..M8 Configuration IDs + matcher identity/model identity +
    input artifact hashes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...config import m8_config

M8_CONFIGURATION_ID_DEFAULT = "DM-M8-001"


def _path(params: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    node: Any = params
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


@dataclass
class DeepMatcherConfig:
    """Snapshot of the M8 engineering configuration.

    ``parameters`` is exactly what the M8 run executed with and is written into
    every M8 manifest for reproducibility.
    """

    configuration_id: str
    configuration_version: int
    name: str
    source_reference: str
    scientifically_tuned: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)

    def p(self, *keys: str, default: Any = None) -> Any:
        return _path(self.parameters, list(keys), default)

    @property
    def enabled(self) -> bool:
        return bool(self.p("enabled", default=True))

    @property
    def preferred_matcher(self) -> str:
        return str(self.p("preferred_matcher", default="auto"))

    @property
    def classical_strategies(self) -> list[str]:
        return list(self.p("classical", "strategies", default=["sift", "orb"]) or [])

    @property
    def deep_strategies(self) -> list[str]:
        return list(self.p("deep", "strategies", default=["superpoint_superglue", "loftr"]) or [])

    @property
    def classical_enabled(self) -> bool:
        return bool(self.p("classical", "enabled", default=True))

    @property
    def deep_enabled(self) -> bool:
        return bool(self.p("deep", "enabled", default=True))

    @property
    def runtime_device(self) -> str:
        return str(self.p("runtime", "device", default="auto"))

    @property
    def max_runtime_seconds(self) -> float:
        return float(self.p("runtime", "max_runtime_seconds", default=120.0))

    @property
    def max_image_dimension(self) -> int:
        return int(self.p("runtime", "max_image_dimension", default=2048))

    @property
    def max_tile_area(self) -> int:
        return int(self.p("runtime", "max_tile_area", default=400000))

    @property
    def batch_size(self) -> int:
        return int(self.p("runtime", "batch_size", default=1))

    @property
    def max_correspondences(self) -> int:
        return int(self.p("candidates", "max_correspondences", default=4000))

    @property
    def require_finite(self) -> bool:
        return bool(self.p("candidates", "require_finite", default=True))

    @property
    def require_mask_valid(self) -> bool:
        return bool(self.p("candidates", "require_mask_valid", default=True))

    @property
    def allow_classical(self) -> bool:
        return bool(self.p("routing", "allow_classical", default=True))

    @property
    def allow_deep(self) -> bool:
        return bool(self.p("routing", "allow_deep", default=True))

    @property
    def fallback_to_classical(self) -> bool:
        return bool(self.p("routing", "fallback_to_classical", default=True))

    @property
    def benchmark_enabled(self) -> bool:
        return bool(self.p("benchmark", "enabled", default=True))

    @property
    def reference_dataset(self) -> str:
        return str(self.p("benchmark", "reference_dataset", default="NOT_AVAILABLE"))

    def deep_strategy_enabled(self, strategy: str) -> bool:
        return self.deep_enabled and strategy in self.deep_strategies

    def classical_strategy_enabled(self, strategy: str) -> bool:
        return self.classical_enabled and strategy in self.classical_strategies

    def as_manifest_snapshot(self) -> dict:
        """Public, JSON-safe snapshot recorded in the M8 manifest."""
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "source_reference": self.source_reference,
            "scientifically_tuned": self.scientifically_tuned,
            "parameters": self.parameters,
        }


def load_deep_matcher_config(configuration_id: str | None = None) -> DeepMatcherConfig:
    """Load the registered M8 deep matcher configuration (DM-M8-001).

    Unknown configuration IDs are rejected loudly — never silently fall back to
    a different configuration than the one requested.
    """
    raw = m8_config()
    known_id = raw.get("configuration_id", M8_CONFIGURATION_ID_DEFAULT)
    requested = (configuration_id or known_id).strip()
    if requested != known_id:
        raise ValueError(
            f"Unknown deep matcher configuration '{requested}'. The only registered "
            f"M8 configuration is '{known_id}'.",
        )
    return DeepMatcherConfig(
        configuration_id=known_id,
        configuration_version=int(raw.get("configuration_version", 1)),
        name=str(raw.get("name", "Deep Matcher Benchmarking, Adaptive Expansion & Trustworthy Matcher Selection")),
        source_reference=str(raw.get("source_reference", "engineering defaults")),
        scientifically_tuned=bool(raw.get("scientifically_tuned", False)),
        parameters=dict(raw.get("defaults") or {}),
    )