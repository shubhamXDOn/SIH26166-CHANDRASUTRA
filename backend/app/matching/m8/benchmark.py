"""M8 benchmark engine (Section 10).

Benchmark mode runs every eligible matcher over every match tile and produces a
per-matcher comparison table with honest outcomes. Downstream columns (M4
trusted, M5 supported, M6 registration reachable) are categorical — ``NOT_RUN``
when no downstream run exists. There is NO ``winner`` and NO accuracy column.
Reference dataset = ``NOT_AVAILABLE`` so no scientific benchmarking claim is
ever made.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .base import M8AdapterOutput, BaseMatcherAdapter
from .contract import ValidatedCandidates, validate_and_normalize
from .states import BENCHMARK_MODES, M8BenchmarkMode, TileRunOutcome

VALID_BENCHMARK_MODES = BENCHMARK_MODES


@dataclass
class BenchmarkRow:
    tile_id: str
    matcher_id: str
    matcher_family: str
    runtime: str = "NOT_RUN"
    candidate_count: int = 0
    finite_count: int = 0
    mask_valid_count: int = 0
    duplicate_count: int = 0
    usable_count: int = 0
    outcome: str = "NOT_RUN"
    m4_trusted: str = "NOT_RUN"
    m5_supported: str = "NOT_RUN"
    m6_registration_reachable: str = "NOT_RUN"
    synthetically_derived: bool = False
    runtime_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tile_id": self.tile_id,
            "matcher_id": self.matcher_id,
            "matcher_family": self.matcher_family,
            "runtime": self.runtime,
            "runtime_ms": round(self.runtime_ms, 3),
            "candidate_count": self.candidate_count,
            "finite_count": self.finite_count,
            "mask_valid_count": self.mask_valid_count,
            "duplicate_count": self.duplicate_count,
            "usable_count": self.usable_count,
            "outcome": self.outcome,
            "m4_trusted": self.m4_trusted,
            "m5_supported": self.m5_supported,
            "m6_registration_reachable": self.m6_registration_reachable,
            "synthetically_derived": self.synthetically_derived,
            "note": "Benchmark row is a measurement table — no winner, no accuracy claim.",
        }


def benchmark_mode_valid(mode: str) -> bool:
    return mode in VALID_BENCHMARK_MODES


def eligible_matchers(registry: dict[str, BaseMatcherAdapter],
                      mode: str) -> list[str]:
    """The matchers a benchmark actually iterates (mode-filtered, honest)."""
    if mode == M8BenchmarkMode.CLASSICAL_ONLY.value:
        return [mid for mid, adapter in registry.items()
                if adapter.family == "classical" and adapter.is_available()]
    if mode == M8BenchmarkMode.DEEP_ONLY.value:
        return [mid for mid, adapter in registry.items()
                if adapter.family == "deep" and adapter.is_available()]
    return [mid for mid, adapter in registry.items() if adapter.is_available()]


def benchmark_row_for(
    adapter: BaseMatcherAdapter,
    candidates: ValidatedCandidates | None,
    output: M8AdapterOutput | None,
    tile_id: str,
    *,
    m4_state: str = "NOT_RUN",
    m5_state: str = "NOT_RUN",
    m6_state: str = "NOT_RUN",
) -> BenchmarkRow:
    row = BenchmarkRow(
        tile_id=tile_id,
        matcher_id=adapter.matcher_id,
        matcher_family=adapter.family,
        m4_trusted=m4_state,
        m5_supported=m5_state,
        m6_registration_reachable=m6_state,
        synthetically_derived=bool(candidates and candidates.synthetically_derived),
    )
    if output is None:
        row.runtime = "NOT_RUN"
        row.outcome = "NOT_RUN"
        return row
    row.runtime = output.runtime_name or adapter.runtime_name or adapter.matcher_id
    row.runtime_ms = output.runtime_ms
    funnel = candidates.funnel if candidates else {}
    row.finite_count = int(max(funnel.get("raw", 0) - funnel.get("nonfinite_rejected", 0), 0))
    row.candidate_count = int(funnel.get("raw", 0))
    row.duplicate_count = int(funnel.get("duplicates_rejected", 0))
    row.usable_count = int(funnel.get("usable", 0))
    row.outcome = candidates.outcome if candidates else TileRunOutcome.NO_CANDIDATES.value
    row.mask_valid_count = int(funnel.get("mask_rejected", 0))
    return row