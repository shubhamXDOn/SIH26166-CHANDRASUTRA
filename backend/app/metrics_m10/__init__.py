"""M10 -- Metrics & Benchmark / Ablation / Failure Analysis.

Engineering-only, descriptive benchmark controller (MET-M10-001) over the
settled M3..M9 artefacts. The controller NEVER executes matcher/trust/spatial/
registration logic; it reads the artefacts that already exist on disk, applies
the M10 variant matrix, aggregates descriptively (median-preferred, mean,
p90, p95, p95/px) and classifies outcomes through the FT-M10-001 failure
taxonomy. No ``winner`` / ``best`` / ``superior`` / ``optimal`` / ``accuracy`` /
``geolocation`` / ``confidence`` claim is emitted; ``reference_status`` stays
REFERENCE_UNAVAILABLE in this build, so no calibration threshold is applied.
"""

from .service import M10MetricsService

__all__ = ["M10MetricsService"]