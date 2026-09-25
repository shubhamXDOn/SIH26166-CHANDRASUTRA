"""M5 condition estimator payload contract.

Canonical schema, input validation, and honesty rules for the
condition-estimator artifact. This layer characterizes an image pair; it
never selects, recommends or routes a matcher and never reports a confidence
or a scientific quality verdict.
"""

from __future__ import annotations

from typing import Any

# --- documented error codes ------------------------------------------------
INVALID_INPUT = "INVALID_INPUT"
PROCESSING_NOT_RUN = "PROCESSING_NOT_RUN"
PROCESS_NOT_READY = "PROCESS_NOT_READY"
PRODUCT_MISSING = "PRODUCT_MISSING"
PAIR_NOT_AVAILABLE = "PAIR_NOT_AVAILABLE"
REAL_DATA_BLOCKED = "REAL_DATA_BLOCKED"
CONDITION_ESTIMATION_FAILED = "CONDITION_ESTIMATION_FAILED"
RESOURCE_LIMIT = "RESOURCE_LIMIT"

ERROR_CODES: tuple[str, ...] = (
    INVALID_INPUT,
    PROCESSING_NOT_RUN,
    PROCESS_NOT_READY,
    PRODUCT_MISSING,
    PAIR_NOT_AVAILABLE,
    REAL_DATA_BLOCKED,
    CONDITION_ESTIMATION_FAILED,
    RESOURCE_LIMIT,
)

# --- fields this milestone must never emit ---------------------------------
FORBIDDEN_KEYS: tuple[tuple[str, str], ...] = (
    ("selected_matcher", "insensitive"),
    ("recommended_matcher", "insensitive"),
    ("best_matcher", "insensitive"),
    ("routing_decision", "insensitive"),
    ("confidence", "insensitive"),
)


def forbidden_key_hit(text: str) -> str | None:
    """Return the forbidden key present in ``text`` (or None)."""
    lower = text.lower()
    for key, mode in FORBIDDEN_KEYS:
        if mode == "insensitive" and key in lower:
            return key
    return None


class ConditionInputError(ValueError):
    """Raised for structurally invalid side inputs (code INVALID_INPUT)."""

    code = INVALID_INPUT


def validate_side_input(display, mask) -> None:
    """Validate a single side's display array and invalid mask.

    Rules:
      * display and mask must both be 2-D (image planes only); higher-rank
        or null arrays are rejected loudly.
      * mask must have the same shape as display.
      * mask convention: 0 == VALID, non-zero == INVALID. Callers must NEVER
        invert the mask.
    """
    import numpy as np

    if display is None or mask is None:
        raise ConditionInputError("display and mask are required for a side condition estimate.")
    if not isinstance(display, np.ndarray) or not isinstance(mask, np.ndarray):
        raise ConditionInputError("display and mask must be numpy arrays.")
    if display.ndim != 2:
        raise ConditionInputError(
            f"display must be a 2-D plane, got ndim={display.ndim} (image rank / "
            "multi-band data is not supported by the M5 condition estimator)."
        )
    if mask.ndim != 2:
        raise ConditionInputError(f"mask must be a 2-D plane, got ndim={mask.ndim}.")
    if mask.shape != display.shape:
        raise ConditionInputError(
            f"mask shape {mask.shape} must equal display shape {display.shape}."
        )
    if display.size == 0:
        raise ConditionInputError("display plane is empty.")


def bin_level(value: float | None, low_lt: float, high_ge: float) -> str:
    """Map a factual engineered metric onto an explicit-threshold ordinal.

    Returns "LOW" / "MEDIUM" / "HIGH" using the threshold pair. This is an
    engineering-level bin, never a scientific verdict.
    """
    if value is None:
        return "UNKNOWN"
    if value < low_lt:
        return "LOW"
    if value >= high_ge:
        return "HIGH"
    return "MEDIUM"


def assert_payload_schema_safe(payload: dict[str, Any]) -> None:
    """Loudly reject any payload that leaks matcher-selection vocabulary."""
    import json as _json

    text = _json.dumps(payload)
    hit = forbidden_key_hit(text)
    if hit is not None:
        raise ValueError(
            f"condition-estimator payload must never emit '{hit}' — this layer "
            "does not select, recommend or route matchers."
        )

    # structural guarantees shared by every artifact (blocked/failed runs keep
    # the same top-level shape with their section set to null)
    assert "intrinsic_image_condition" in payload, "missing intrinsic_image_condition"
    assert "pair_comparison" in payload, "missing pair_comparison"
    assert "matcher_derived_observations" in payload, "missing matcher_derived_observations"
    observations = payload.get("matcher_derived_observations")
    assert observations is None or "source" in observations, "labelled observation source required"
    estimated = payload.get("estimated")
    if estimated is not None:
        assert estimated["scientifically_tuned"] is False, "engineering label flag must be false"