"""M9 REGISTRATION artifact contract + vocabulary guard.

The M9 status is a state (SUCCESS / SUCCESS_WITH_WARNINGS / ABSTAIN /
BLOCKED / FAILED), never a numeric accuracy, a "winner" or "best alignment".
Field names carrying the forbidden vocabulary are scan-rejected anywhere in
the artifact. Registration residuals are geometric observations in the
effective matcher plane, never physical accuracy.
"""

from __future__ import annotations

from typing import Any

from . import states
from .config import RegistrationM9Config


def assert_artifact_vocabulary_safe(
    payload: dict[str, Any],
    forbidden: tuple[str, ...] | None = None,
) -> None:
    forbidden = forbidden or RegistrationM9Config().forbidden_vocabulary
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
        raise ValueError("M9 artifact must carry a decision object")
    if decision.get("state") not in states.STATUS_STATES:
        raise ValueError(
            f"decision.state must be one of {states.STATUS_STATES}; got {decision.get('state')!r}"
        )
    assert_artifact_vocabulary_safe(payload)


def license_text() -> str:
    return (
        "Registration output is a geometric transform computed from the M8-selected "
        "correspondences in the declared effective matcher plane, together with "
        "residual diagnostics and a derived aligned/warped output — never a physical "
        "accuracy, geolocation, map-accuracy or ground-truth claim (reference_status: "
        "REFERENCE_UNAVAILABLE unless independent reference data is registered). The "
        "M7 verdict and the M8 status are preserved and never rewritten."
    )


__all__ = ["assert_artifact_vocabulary_safe", "assert_artifact_valid", "license_text"]