"""FT-M10-001 failure taxonomy: classification of M10 run outcomes.

The taxonomy has one root (REGISTRATION_FAILURE) with two disjoint branches:

    failed    -- the run actually attempted the downstream work and could not
                 complete it (transform fit error, non-finite values, missing
                 upstream artefact it was designed to consume).
    abstain   -- the run had too little settled evidence to reach the
                 downstream stage at all (sparse residue, marginal evidence,
                 budget exceeded / optimisation aborted).

A failed run is never re-labelled abstain and vice versa; a BLOCKED run is
never recorded as an outcome.  Everything below operates on already-settled
status strings and never invents a label.
"""

from __future__ import annotations

from typing import Any

FAILED_CODES = (
    "TRANSFORM_FIT_ERROR",
    "VALUES_NOT_FINITE",
    "SPATIAL_NOT_AVAILABLE",
    "TRUST_NOT_AVAILABLE",
    "MATCH_RUN_NOT_AVAILABLE",
    "REGISTRATION_FAILED",
)

ABSTAIN_CODES = (
    "SPARSE_EVIDENCE",
    "MARGINAL_EVIDENCE",
    "BUDGET_EXCEEDED",
    "ABSTAIN",
)

ROOT = "REGISTRATION_FAILURE"


def classify(status: str | None, *, stage: str | None = None) -> dict[str, Any] | None:
    """Classify a settled text status into the taxonomy.

    Returns None for statuses that are not failure-taxonomy outcomes
    (e.g. COMPLETE, BLOCKED, running phases).  Never returns both failed and
    abstain for the same input.
    """
    if not status:
        return None
    up = status.upper()
    if up == "FAILED":
        return {"root": ROOT, "branch": "failed", "code": "FAILED", "stage": stage or "registration"}
    if up == "ABSTAIN":
        return {"root": ROOT, "branch": "abstain", "code": "ABSTAIN", "stage": stage or "matching"}
    code = next((c for c in FAILED_CODES if c in up), None)
    if code:
        return {"root": ROOT, "branch": "failed", "code": code, "stage": stage or "registration"}
    code = next((c for c in ABSTAIN_CODES if c in up), None)
    if code:
        return {"root": ROOT, "branch": "abstain", "code": code, "stage": stage or "matching"}
    return None


def is_failed(status: str | None) -> bool:
    if not status:
        return False
    up = status.upper()
    if up == "FAILED":
        return True
    return any(c in up for c in FAILED_CODES)


def is_abstain(status: str | None) -> bool:
    if not status:
        return False
    up = status.upper()
    if up == "ABSTAIN":
        return True
    return any(c in up for c in ABSTAIN_CODES)