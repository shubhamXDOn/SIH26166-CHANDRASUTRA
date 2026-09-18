"""M7 — Quantitative Metrics, Reproducible Experiment Reports & Scientific Diagnostics.

Metrics are measurements of pipeline evidence, never a claim of scientific
alignment accuracy. Every metric records its source artefact, calculation
method and scientific status. Blocked stages report UNKNOWN/NOT_RUN/BLOCKED —
never fabricated zero values. Reference/ground-truth datasets are abstracted
and default to NOT_AVAILABLE (PRADAN real-data truth remain unavailable).
"""

from __future__ import annotations

from backend.app.metrics.config import METRICS_CONFIGURATION_ID, MT_M7_001
from backend.app.metrics.reference import REFERENCE_DATASET

__all__ = ["MT_M7_001", "METRICS_CONFIGURATION_ID", "REFERENCE_DATASET"]