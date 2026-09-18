"""M7 metric/report vocabulary — states, categories and scientific statuses."""

from __future__ import annotations

from enum import Enum


class MetricsRunState(str, Enum):
    """Top-level state of an M7 metrics run (mirrors pipeline run states)."""

    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"


class MetricCategory(str, Enum):
    """Canonical metric category vocabulary."""

    OBSERVATION = "OBSERVATION"      # what the pipeline produced (counts, outcomes)
    MEASUREMENT = "MEASUREMENT"      # numeric diagnostics measured from evidence
    DIAGNOSTIC = "DIAGNOSTIC"        # derived/numerical-health diagnostics
    VALIDATION = "VALIDATION"        # verdicts/checks against configured thresholds
    REFERENCE = "REFERENCE"          # reference/ground-truth comparison (NOT_AVAILABLE by default)


class MetricStatus(str, Enum):
    """Per-metric status. Blocked stages report NOT_RUN/BLOCKED, never zeros."""

    AVAILABLE = "AVAILABLE"
    NOT_RUN = "NOT_RUN"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"
    REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"


class ScientificStatus(str, Enum):
    """How a metric may be interpreted.

    MEASUREMENT  — numeric value derived from artefacts (a measured quantity).
    ENGINEERING  — engineering/policy denominator or ratio, not scientifically tuned.
    DIAGNOSTIC   — numerical-health check, not an accuracy claim.
    REFERENCE    — reference/ground-truth comparison; requires real data.
    NOT_SCIENTIFIC — explicitly labelled as not a scientific statement.
    """

    MEASUREMENT = "MEASUREMENT"
    ENGINEERING = "ENGINEERING"
    DIAGNOSTIC = "DIAGNOSTIC"
    REFERENCE = "REFERENCE"
    NOT_SCIENTIFIC = "NOT_SCIENTIFIC"


class MetricsBlockCode(str, Enum):
    """Block codes for M7 metrics runs."""

    M6_NOT_AVAILABLE = "M6_NOT_AVAILABLE"
    M6_NOT_COMPLETE = "M6_NOT_COMPLETE"
    REGISTRATION_ARTIFACTS_MISSING = "REGISTRATION_ARTIFACTS_MISSING"
    METRICS_UNKNOWN_CONFIG = "METRICS_UNKNOWN_CONFIG"
    METRICS_FAILED = "METRICS_FAILED"
    FORBIDDEN_TERMINOLOGY = "FORBIDDEN_TERMINOLOGY"
    METRIC_RECOMPUTATION_MISMATCH = "METRIC_RECOMPUTATION_MISMATCH"


# Forbidden terminology anywhere in M7 metric ids/names/units (directive §29).
FORBIDDEN_TERMINOLOGY: tuple[str, ...] = (
    "overall_accuracy",
    "scientific_confidence",
    "registration_confidence",
    "alignment_score",
    "lunar_accuracy",
    "geolocation_accuracy",
    "ce90",
    "le90",
)