"""M8 SPATIAL artifact contract + vocabulary guard.

The M8 status is a state (SELECTED / SELECTED_WITH_WARNINGS / ABSTAIN /
BLOCKED / FAILED), never a numeric confidence or a "winner". Field names
carrying the forbidden vocabulary are scan-rejected anywhere in the artifact.
"""

from __future__ import annotations

from typing import Any

from .config import SpatialSelectionConfig
from . import states


def assert_artifact_vocabulary_safe(
    payload: dict[str, Any],
    forbidden: tuple[str, ...] | None = None,
) -> None:
    forbidden = forbidden or SpatialSelectionConfig().forbidden_vocabulary
    forbidden = tuple(f.lower() for f in forbidden)

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).strip().lower() in forbidden:
                    raise ValueError(
                        f"Forbidden vocabulary field {key!r} at {path or '<root>'}"
                    )
                walk(value, path + "/" + str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(payload, "")


def assert_artifact_valid(payload: dict[str, Any]) -> None:
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        raise ValueError("M8 artifact must carry a decision object")
    if decision.get("state") not in states.STATUS_STATES:
        raise ValueError(
            f"decision.state must be one of {states.STATUS_STATES}; got {decision.get('state')!r}"
        )
    assert_artifact_vocabulary_safe(payload)


def license_text() -> str:
    return (
        "Spatial coverage, occupancy, entropy and extent are deterministic "
        "bookkeeping evidence in the effective matcher plane — never an accuracy, "
        "probability or registration claim (reference_status: "
        "REFERENCE_UNAVAILABLE unless independent reference data is registered). "
        "The selection is a subset of the M7 trusted set and never overrides the "
        "M7 verdict."
    )


__all__ = ["assert_artifact_vocabulary_safe", "assert_artifact_valid", "license_text"]