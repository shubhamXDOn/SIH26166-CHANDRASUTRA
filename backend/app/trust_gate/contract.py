"""M7 TRUST GATE artifact contract + vocabulary guard.

The Trust Gate decision field is a *state* (ACCEPT / REJECT / ABSTAIN /
BLOCKED), never a numeric "confidence". The artifact is scan-rejected for
forbidden vocabulary, mirroring the M6 routing guard.
"""

from __future__ import annotations

from typing import Any

from .config import TrustGateConfig
from . import states


def assert_artifact_vocabulary_safe(
    payload: dict[str, Any],
    forbidden: tuple[str, ...] | None = None,
) -> None:
    """Depth-first reject any forbidden field NAME anywhere in the artifact.

    ``confidence`` (and friends) may never appear as a field name: the RANSAC
    probability parameter is persisted as ``confidence_parameter`` inside the
    algorithm block, and the gate output uses explicit decision states.
    """
    forbidden = forbidden or TrustGateConfig().forbidden_vocabulary
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


def assert_decision_present(payload: dict[str, Any]) -> None:
    if not isinstance(payload.get("decision"), dict):
        raise ValueError("M7 artifact must carry a decision object")
    dec = payload["decision"]
    if dec.get("state") not in states.DECISION_STATES:
        raise ValueError(
            f"decision.state must be one of {states.DECISION_STATES}; got {dec.get('state')!r}"
        )


def assert_artifact_valid(payload: dict[str, Any]) -> None:
    assert_decision_present(payload)
    assert_artifact_vocabulary_safe(payload)


def license_text() -> str:
    return (
        "Candidate correspondences are observations, and a Trust Gate decision is "
        "geometric verification under configured thresholds — never a physical-accuracy, "
        "registration-accuracy or scientific ground-truth claim (reference_status: "
        "REFERENCE_UNAVAILABLE unless independent reference data is registered)."
    )