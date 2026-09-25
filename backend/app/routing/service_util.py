"""M6 adaptive matcher router — small pure helpers shared by service/engine.

Kept dependency-light so the router art-artifact summary and dispatch plan
stay deterministic and JSON-safe.
"""

from __future__ import annotations

from typing import Any

from .contract import (
    ABSTAIN,
    ABSTAIN_STATUS,
    BLOCKED,
    BLOCKED_STATUS,
    EXECUTION_STARTED,
    ROUTED,
    ROUTING_SUCCESS,
)


def execution_status_for_decision(state: str) -> str:
    """Map a routing decision state onto the API decision-status vocabulary."""
    if state == ROUTED:
        return ROUTING_SUCCESS
    if state == BLOCKED:
        return BLOCKED_STATUS
    if state == ABSTAIN:
        return ABSTAIN_STATUS
    return ROUTED


def executable_match_ids(primary: str | None, fallback: str | None) -> list[str]:
    """Ordered execution plan (primary first, fallback after, de-duplicated)."""
    ordered: list[str] = []
    for matcher in (primary, fallback):
        if matcher and matcher not in ordered:
            ordered.append(matcher)
    return ordered


def run_status_summary(payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    return {
        "routing_run_id": payload.get("routing_run_id"),
        "pair_id": payload.get("pair_id"),
        "created_at_utc": payload.get("created_at_utc"),
        "mode": payload.get("mode"),
        "status": "SUCCESS",
        "state": payload.get("decision", {}).get("state"),
        "decision_status": payload.get("decision_status"),
        "matched_rule_id": decision.get("matched_rule_id"),
        "rule_priority": decision.get("rule_priority"),
        "requested_primary_matcher": decision.get("requested_primary_matcher"),
        "primary_matcher": decision.get("primary_matcher"),
        "fallback_matcher": decision.get("fallback_matcher"),
        "fallback_used": bool(decision.get("fallback_used", False)),
        "fallback_reason": decision.get("fallback_reason"),
        "error_code": decision.get("error_code"),
        "decision_hash": decision.get("decision_hash"),
        "experiment_id": payload.get("experiment_id"),
        "executed_routes": (payload.get("execution") or {}).get("executed_routes"),
        "execution_final_route": (payload.get("execution") or {}).get("final_route"),
        "configuration_id": payload.get("configuration_id"),
    }


def deep_runtime_probe() -> dict[str, Any]:
    """torch/torchvision availability for the environment snapshot (no weights)."""
    out: dict[str, Any] = {"torch": False, "torchvision": False}
    try:
        import torch

        out["torch"] = True
        out["torch_version"] = getattr(torch, "__version__", "unknown")
        out["cuda_available"] = bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        pass
    try:
        import torchvision

        out["torchvision"] = True
        out["torchvision_version"] = getattr(torchvision, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        pass
    return out


__all__ = [
    "execution_status_for_decision",
    "executable_match_ids",
    "run_status_summary",
    "deep_runtime_probe",
]