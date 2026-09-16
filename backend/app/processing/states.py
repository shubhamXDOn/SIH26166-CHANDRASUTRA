"""Processing lifecycle states and stage tracking (M2).

The public state machine covers the full PREPARE lifecycle. BLOCKED is a
normal, truthful outcome (e.g. real pair without geometry) — it is reported
with a stable code and reason, never as a fake "success".
"""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any


class ProcessingState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    READING = "READING"
    PREPROCESSING = "PREPROCESSING"
    PREPARING_OVERLAP = "PREPARING_OVERLAP"
    GENERATING_CROPS = "GENERATING_CROPS"
    ANALYZING_CONDITION = "ANALYZING_CONDITION"
    READY_FOR_MATCHING = "READY_FOR_MATCHING"
    FAILED = "FAILED"


STATE_LABELS: dict[str, str] = {
    "NOT_STARTED": "Not started",
    "BLOCKED": "Blocked",
    "READING": "Reading raw products",
    "PREPROCESSING": "Preprocessing",
    "PREPARING_OVERLAP": "Preparing overlap",
    "GENERATING_CROPS": "Generating crops",
    "ANALYZING_CONDITION": "Analyzing condition",
    "READY_FOR_MATCHING": "Ready for matching",
    "FAILED": "Failed",
}

# Order of the RUNNABLE stages during a PREPARE run.
STAGE_ORDER: list[str] = [
    "READING",
    "PREPROCESSING",
    "PREPARING_OVERLAP",
    "GENERATING_CROPS",
    "ANALYZING_CONDITION",
]

# Stage id used in status payloads / UI (queued | running | complete | blocked | failed | not_run).
RUN_ID = "run"
BLOCKED_ID = "block"
FAILED_ID = "fail"


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def initial_stages() -> list[dict[str, Any]]:
    return [
        {
            "id": RUN_ID,
            "label": "PREPARE run",
            "state": "not_run",
            "started_at": None,
            "finished_at": None,
            "detail": "No PREPARE run has been attempted.",
        },
        *[
            {
                "id": sid.lower(),
                "label": STATE_LABELS[sid],
                "state": "not_run",
                "started_at": None,
                "finished_at": None,
                "detail": "",
            }
            for sid in STAGE_ORDER
        ],
    ]


def synthetic_status(configuration_id: str, *, pair_id: str | None = None, note: str = "") -> dict[str, Any]:
    """A NOT_STARTED status snapshot (nothing fabricated about progress)."""
    return {
        "pair_id": pair_id or "",
        "configuration_id": configuration_id,
        "state": ProcessingState.NOT_STARTED.value,
        "state_label": STATE_LABELS[ProcessingState.NOT_STARTED.value],
        "progress": 0,
        "started_at": None,
        "finished_at": None,
        "stages": initial_stages(),
        "blocked": None,
        "error": None,
        "matcher_readiness": None,
        "note": note or "No PREPARE run has been executed for this pair/configuration.",
    }


def make_stage_mapping(stages: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {s["id"]: s for s in stages}