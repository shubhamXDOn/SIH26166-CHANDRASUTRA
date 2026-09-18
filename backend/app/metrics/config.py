"""M7 metrics configuration (MT-M7-001).

Engineering defaults only — every threshold is explicitly ``scientifically_tuned:
false``. Nothing here is calibrated to real lunar data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

METRICS_CONFIGURATION_ID = "MT-M7-001"
METRICS_CONFIGURATION_VERSION = 1


def _f(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RejectThresholdConfig:
    """Thresholds for rejection/attrition classification (engineering only)."""

    inlier_ratio_minimum: float = 0.3
    residual_mean_max_px: float = 10.0
    selected_fraction_minimum: float = 0.1
    scientifically_tuned: bool = False


@dataclass(frozen=True)
class RecomputeConfig:
    """Independent recomputation policy."""

    enabled: bool = True
    inlier_threshold_px: float = 3.0
    consistency_tolerance: float = 1e-3
    scientifically_tuned: bool = False


@dataclass(frozen=True)
class ReportConfig:
    deterministic_report: bool = True


@dataclass(frozen=True)
class MetricsConfig:
    metrics_configuration_id: str = METRICS_CONFIGURATION_ID
    metrics_configuration_version: str = "1"
    source: str = "engineering defaults"
    scientifically_tuned: bool = False
    rejected: RejectThresholdConfig = field(default_factory=RejectThresholdConfig)
    recompute: RecomputeConfig = field(default_factory=RecomputeConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    execution: dict = field(default_factory=lambda: {"max_runtime_seconds": 60})

    @classmethod
    def from_dict(cls, d: dict) -> MetricsConfig:
        rej = d.get("rejected") or {}
        rec = d.get("recompute") or {}
        rep = d.get("report") or {}
        return cls(
            metrics_configuration_id=str(d.get("metrics_configuration_id", METRICS_CONFIGURATION_ID)),
            metrics_configuration_version=str(d.get("metrics_configuration_version", "1")),
            source=str(d.get("source", "engineering defaults")),
            scientifically_tuned=bool(d.get("scientifically_tuned", False)),
            rejected=RejectThresholdConfig(
                inlier_ratio_minimum=_f(rej.get("inlier_ratio_minimum"), 0.3),
                residual_mean_max_px=_f(rej.get("residual_mean_max_px"), 10.0),
                selected_fraction_minimum=_f(rej.get("selected_fraction_minimum"), 0.1),
                scientifically_tuned=bool(rej.get("scientifically_tuned", False)),
            ),
            recompute=RecomputeConfig(
                enabled=bool(rec.get("enabled", True)),
                inlier_threshold_px=_f(rec.get("inlier_threshold_px"), 3.0),
                consistency_tolerance=_f(rec.get("consistency_tolerance"), 1e-3),
                scientifically_tuned=bool(rec.get("scientifically_tuned", False)),
            ),
            report=ReportConfig(
                deterministic_report=bool(rep.get("deterministic_report", True)),
            ),
            execution=dict(d.get("execution") or {"max_runtime_seconds": 60}),
        )


MT_M7_001 = MetricsConfig()