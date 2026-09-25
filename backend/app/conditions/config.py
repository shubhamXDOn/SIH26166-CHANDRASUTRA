"""M5 condition estimator configuration (registered, explicit, inspectable).

Reproducibility contract:
    Pair ID + Processing Configuration ID (M2) + Condition Configuration ID.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import m5_condition_config


def _path(params: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    node: Any = params
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


@dataclass
class ConditionConfig:
    """Snapshot of the M5 condition estimator engineering configuration.

    ``parameters`` is exactly what the estimator executed with and is written
    into every condition-estimator artifact for reproducibility.
    """

    configuration_id: str
    configuration_version: int
    name: str
    source_reference: str
    derived_rel: str = "metadata/m5_condition"
    scientifically_tuned: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)

    # -- typed parameter readers --------------------------------------------
    def p(self, *keys: str, default: Any = None) -> Any:
        return _path(self.parameters, list(keys), default)

    @property
    def max_runtime_seconds(self) -> float:
        return float(self.p("execution", "max_runtime_seconds", default=120.0))

    @property
    def window_size_px(self) -> int:
        return int(self.p("sampling", "window_size_px", default=256))

    @property
    def stride_px(self) -> int:
        return int(self.p("sampling", "stride_px", default=128))

    @property
    def sampling_seed(self) -> int:
        return int(self.p("sampling", "seed", default=20260922))

    @property
    def max_windows(self) -> int:
        return int(self.p("sampling", "max_windows", default=1024))

    @property
    def require_full_windows(self) -> bool:
        return bool(self.p("sampling", "require_full_windows", default=False))

    @property
    def sobel_kernel_size_px(self) -> int:
        return int(self.p("texture", "sobel_kernel_size_px", default=3))

    @property
    def laplacian_kernel_size_px(self) -> int:
        return int(self.p("texture", "laplacian_kernel_size_px", default=3))

    @property
    def canny_enabled(self) -> bool:
        return bool(self.p("texture", "canny", "enabled", default=True))

    @property
    def histogram_bins(self) -> int:
        return int(self.p("appearance", "histogram_bins", default=256))

    @property
    def robust_percentiles(self) -> list[float]:
        return [float(v) for v in list(self.p("appearance", "robust_percentiles", default=[5.0, 50.0, 95.0]))]

    @property
    def gsd_enabled(self) -> bool:
        return bool(self.p("scale", "gsd", "enabled", default=True))

    @property
    def gsd_fallback(self) -> str:
        return str(self.p("scale", "gsd", "fallback", default="UNKNOWN"))

    @property
    def matcher_observations_enabled(self) -> bool:
        return bool(self.p("matcher_observations", "enabled", default=True))

    @property
    def require_real_data(self) -> bool:
        return bool(self.p("data_gate", "require_real", default=False))

    def classification_key(self, key: str) -> dict[str, Any]:
        return dict((self.p("classification", key, default={}) or {}))

    def as_manifest_snapshot(self) -> dict:
        """Public, JSON-safe snapshot recorded in the condition artifact."""
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "source_reference": self.source_reference,
            "parameters": self.parameters,
        }


def load_condition_config(configuration_id: str | None = None) -> ConditionConfig:
    """Load the registered M5 condition estimator configuration (CE-M5-001).

    Unknown Configuration IDs are rejected loudly — no silent fallback to a
    different configuration than the one requested.
    """
    raw = m5_condition_config()
    known_id = raw.get("configuration_id", "CE-M5-001")
    requested = (configuration_id or known_id).strip()
    if requested != known_id:
        raise ValueError(
            f"Unknown condition estimator configuration '{requested}'. The only "
            f"registered M5 condition configuration is '{known_id}'.",
        )
    return ConditionConfig(
        configuration_id=known_id,
        configuration_version=int(raw.get("configuration_version", 1)),
        name=str(raw.get("name", "Condition Estimator — Pair-Level Condition & Difficulty Characterization (Pre-Matcher-Selection Layer)")),
        source_reference=str(raw.get("source_reference", "")),
        derived_rel=str(raw.get("derived_rel", "metadata/m5_condition")),
        scientifically_tuned=bool(raw.get("scientifically_tuned", False)),
        parameters=dict(raw.get("defaults") or {}),
    )


def configurations_public() -> list[dict]:
    """The runnable configuration exposed by /api/matching/conditions/capabilities."""
    try:
        cfg = load_condition_config()
    except ValueError:
        return []
    return [
        {
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "name": cfg.name,
            "source_reference": cfg.source_reference,
            "display_only": {
                "execution": {"max_runtime_seconds": cfg.max_runtime_seconds},
                "sampling": {
                    "window_size_px": cfg.window_size_px,
                    "stride_px": cfg.stride_px,
                    "seed": cfg.sampling_seed,
                    "max_windows": cfg.max_windows,
                },
                "histogram_bins": cfg.histogram_bins,
                "scales_recorded": ["native", "effective_processing"],
                "matcher_observations_labelled_separately": True,
                "note": (
                    "This layer characterizes the pair; it never selects, "
                    "recommends or routes a matcher and never reports a "
                    "confidence or a scientific quality verdict."
                ),
            },
        }
    ]