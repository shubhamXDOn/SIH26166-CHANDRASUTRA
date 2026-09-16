"""Matching lifecycle states, tile outcomes and measured event stages (M3).

The public state machine covers a MATCH run. BLOCKED is a normal, truthful
outcome (nothing runnable) — reported with a stable code + reason. Tile
outcomes distinguish failure modes explicitly; a failure is never presented
as "zero candidates found".
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any


class MatchingState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


STATE_LABELS: dict[str, str] = {
    "NOT_STARTED": "Not started",
    "BLOCKED": "Blocked",
    "RUNNING": "Matching in progress",
    "COMPLETE": "Matching complete",
    "FAILED": "Failed",
}


class TileOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    NO_FEATURES = "NO_FEATURES"
    NO_CANDIDATES = "NO_CANDIDATES"
    INSUFFICIENT_CANDIDATES = "INSUFFICIENT_CANDIDATES"
    MATCHER_FAILED = "MATCHER_FAILED"
    MATCHER_UNAVAILABLE = "MATCHER_UNAVAILABLE"
    INPUT_INVALID = "INPUT_INVALID"
    BLOCKED = "BLOCKED"
    TIMEOUT = "TIMEOUT"


OUTCOME_LABELS: dict[str, str] = {
    "SUCCESS": "Candidate set accepted",
    "NO_FEATURES": "Features could not be localised",
    "NO_CANDIDATES": "No candidate correspondences survived",
    "INSUFFICIENT_CANDIDATES": "Candidate set below minimum threshold",
    "MATCHER_FAILED": "The matcher raised a failure",
    "MATCHER_UNAVAILABLE": "The selected matcher is unavailable",
    "INPUT_INVALID": "Tile input window was invalid",
    "BLOCKED": "Tile was blocked by preconditions",
    "TIMEOUT": "Tile exceeded the runtime budget",
}


# Order of the RUNNABLE coarse stages during a MATCH run.
STAGE_ORDER: list[str] = [
    "BUILDING_MATCH_TILES",
    "ROUTING_STRATEGY",
    "RUNNING_MATCHERS",
    "WRITING_CANDIDATES",
]

RUN_ID = "run"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def initial_stages() -> list[dict[str, Any]]:
    return [
        {
            "id": RUN_ID,
            "label": "MATCH run",
            "state": "not_run",
            "started_at": None,
            "finished_at": None,
            "detail": "No MATCH run has been attempted.",
        },
        *[
            {
                "id": sid.lower(),
                "label": sid.replace("_", " ").title(),
                "state": "not_run",
                "started_at": None,
                "finished_at": None,
                "detail": "",
            }
            for sid in STAGE_ORDER
        ],
    ]


def synthetic_status(pair_id: str, configuration_id: str, *, blocked: dict[str, Any] | None = None,
                     note: str = "") -> dict[str, Any]:
    """A status snapshot with zero fabricated progress."""
    state = "BLOCKED" if blocked else MatchingState.NOT_STARTED.value
    return {
        "pair_id": pair_id,
        "configuration_id": configuration_id,
        "state": state,
        "state_label": STATE_LABELS[state],
        "progress": 0,
        "started_at": None,
        "finished_at": None,
        "stages": initial_stages(),
        "blocked": blocked,
        "error": None,
        "summary": None,
        "note": note or ("No MATCH run has been executed for this pair." if not blocked else "Nothing was run."),
    }


def make_stage_mapping(stages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in stages}