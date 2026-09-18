"""M8 lifecycle states, block/failure codes and benchmark modes.

The public state machine covers a single M8 benchmark/expansion run over one
or more M3 match tiles. BLOCKED and INSUFFICIENT are normal, truthful outcomes.
Failures keep an explicit stable code (never a generic "FAILED" when something
more precise is known).
"""

from __future__ import annotations

from enum import Enum


class M8RunState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    INSUFFICIENT = "INSUFFICIENT"
    FAILED = "FAILED"


STATE_LABELS: dict[str, str] = {
    "NOT_STARTED": "Not started",
    "BLOCKED": "Blocked",
    "RUNNING": "Benchmark/expansion in progress",
    "COMPLETE": "Complete",
    "INSUFFICIENT": "Insufficient evidence",
    "FAILED": "Failed",
}


class M8BlockCode(str, Enum):
    """Explicit lifecycle block/failure codes (never collapse into generic FAILED)."""

    M3_NOT_AVAILABLE = "M3_NOT_AVAILABLE"
    M3_NOT_COMPLETE = "M3_NOT_COMPLETE"
    NO_ELIGIBLE_MATCHER = "NO_ELIGIBLE_MATCHER"
    DEEP_MATCHER_UNAVAILABLE = "DEEP_MATCHER_UNAVAILABLE"
    MODEL_WEIGHTS_NOT_CONFIGURED = "MODEL_WEIGHTS_NOT_CONFIGURED"
    MODEL_WEIGHTS_INVALID = "MODEL_WEIGHTS_INVALID"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    INPUT_INVALID = "INPUT_INVALID"
    TIMEOUT = "TIMEOUT"
    MATCHER_FAILED = "MATCHER_FAILED"
    NO_CANDIDATES = "NO_CANDIDATES"
    FORBIDDEN_TERMINOLOGY = "FORBIDDEN_TERMINOLOGY"
    MATCHING_FAILED = "MATCHING_FAILED"
    REAL_DATA_UNAVAILABLE = "REAL_DATA_UNAVAILABLE"
    REFERENCE_DATASET_NOT_AVAILABLE = "REFERENCE_DATASET_NOT_AVAILABLE"


BLOCK_CODE_LABELS: dict[str, str] = {
    "M3_NOT_AVAILABLE": "No M3 MATCH run exists — run MATCH first.",
    "M3_NOT_COMPLETE": "M3 MATCH run is not COMPLETE.",
    "NO_ELIGIBLE_MATCHER": "No matcher is eligible under the requested mode.",
    "DEEP_MATCHER_UNAVAILABLE": "Requested deep matcher is not available.",
    "MODEL_WEIGHTS_NOT_CONFIGURED": "Model weights are not configured for this build.",
    "MODEL_WEIGHTS_INVALID": "Model weights are present but unusable.",
    "RUNTIME_UNAVAILABLE": "The matcher's runtime dependency is unavailable.",
    "INPUT_INVALID": "Input windows/masks are invalid.",
    "TIMEOUT": "The run exceeded its runtime budget.",
    "MATCHER_FAILED": "A matcher raised a failure.",
    "NO_CANDIDATES": "No candidate correspondences survived validation.",
    "FORBIDDEN_TERMINOLOGY": "Forbidden scientific-terminology detected in generated payload.",
    "MATCHING_FAILED": "The M8 run failed unexpectedly.",
    "REAL_DATA_UNAVAILABLE": "No real validated lunar pair is available.",
    "REFERENCE_DATASET_NOT_AVAILABLE": "No external reference dataset exists — accuracy is NOT_AVAILABLE.",
}


class M8BenchmarkMode(str, Enum):
    """Controlled benchmark modes for M8 run requests."""

    AUTO = "AUTO"
    CLASSICAL_ONLY = "CLASSICAL_ONLY"
    DEEP_ONLY = "DEEP_ONLY"


BENCHMARK_MODES = tuple(m.value for m in M8BenchmarkMode)
VALID_BENCHMARK_MODES = set(BENCHMARK_MODES)


class TileRunOutcome(str, Enum):
    CANDIDATES = "CANDIDATES"
    NO_CANDIDATES = "NO_CANDIDATES"
    INSUFFICIENT = "INSUFFICIENT"
    MATCHER_UNAVAILABLE = "MATCHER_UNAVAILABLE"
    DEEP_MATCHER_UNAVAILABLE = "DEEP_MATCHER_UNAVAILABLE"
    INPUT_INVALID = "INPUT_INVALID"
    TIMEOUT = "TIMEOUT"
    MATCHER_FAILED = "MATCHER_FAILED"


OUTCOME_LABELS: dict[str, str] = {
    "CANDIDATES": "Candidate correspondences recorded",
    "NO_CANDIDATES": "No candidate correspondences survived validation",
    "INSUFFICIENT": "Candidate set below the usable threshold",
    "MATCHER_UNAVAILABLE": "The selected matcher is unavailable",
    "DEEP_MATCHER_UNAVAILABLE": "The selected deep matcher is unavailable",
    "INPUT_INVALID": "Tile input windows/masks were invalid",
    "TIMEOUT": "Tile exceeded the runtime budget",
    "MATCHER_FAILED": "The matcher raised a failure",
}