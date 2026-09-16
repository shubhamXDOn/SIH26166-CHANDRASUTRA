"""M3 — Adaptive Matcher Intelligence & Candidate Correspondences.

The adaptive routing engine observes the M2 scene condition, scores the
strategy adapters against measured evidence, records *why* a strategy was
selected, and produces *candidate correspondences* (never verified truth —
the M4 Trust Gate owns that decision on purpose).
"""

from __future__ import annotations

__all__ = ["MatcherConfig", "load_matcher_config", "configurations_public"]