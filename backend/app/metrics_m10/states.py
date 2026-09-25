"""Run states and status vocabulary for M10 benchmark runs.

The M10 milestone preserves a strict three-way outcome policy that the
failure taxonomy (FT-M10-001) is built around:

    * A BLOCKED run is never recorded as an outcome.
    * A FAILED run never abstains.  A failed run is a failed run.
    * An ABSTAIN run never fails.  Insufficient/settled-sparse evidence is
      an abstention, recorded as ABSTAIN (never as a failure, never as a
      success, never as accuracy).

No status in this module asserts a scientific quality verdict.
"""

from __future__ import annotations

# Pipeline states the funnel can observe at any stage.
NOT_STARTED = "NOT_STARTED"
RUNNING = "RUNNING"

# Terminal/guarded states (three-way outcome policy applies).
BLOCKED = "BLOCKED"
FAILED = "FAILED"
ABSTAIN = "ABSTAIN"
COMPLETE = "COMPLETE"

# Optimistic availability labels used purely for variant *run* accounting.
MATCHED = "MATCHED"
SELECTED = "SELECTED"
REGISTERED = "REGISTERED"

# Guard reasons: a variant refused to fabricate an offline ablation result.
AVAILABILITY = "AVAILABILITY"
PREREQUISITES = "PREREQUISITES"
OFFLINE_ABLATION = "OFFLINE_ABLATION"
REFERENCE_UNAVAILABLE = "REFERENCE_UNAVAILABLE"

RUN_STATES = (NOT_STARTED, RUNNING, BLOCKED, FAILED, ABSTAIN, COMPLETE)
OUTCOME_STATES = (FAILED, ABSTAIN, COMPLETE)

FUNNEL_STAGES = (
    "input_gate",
    "processing",
    "matching",
    "trust_gate",
    "spatial_selection",
    "registration",
)

# Words the benchmark must never emit while the reference data is
# REFERENCE_UNAVAILABLE.  Enforced by the schema build (schema.py) so a
# single controlled vocabulary file is the source of truth.
FORBIDDEN_VOCABULARY = (
    "winner",
    "best",
    "superior",
    "optimal",
    "accuracy",
    "success_rate",
    "geolocation",
    "geolocation_accuracy",
    "CE90",
    "LE90",
    "confidence",
    "final_confidence",
    "perfect",
    "outperformed",
)


def is_outcome(state: str | None) -> bool:
    return bool(state and state in OUTCOME_STATES)


def is_terminal(state: str | None) -> bool:
    return bool(state and (state in OUTCOME_STATES or state == BLOCKED))