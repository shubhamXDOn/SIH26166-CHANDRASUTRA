"""M6 adaptive matcher router — safe, deterministic predicate evaluation.

Predicates run against the flat canonical condition/capability view. Missing
data never crashes routing: comparisons against None evaluate False (so a
blocked/abstain path is only ever taken by an explicit gate rule). Only
``exists`` and ``equals``/``not_equals`` with an explicit null value reason
about None on purpose.
"""

from __future__ import annotations

from typing import Any

OPERATORS: frozenset[str] = frozenset({
    "equals",
    "not_equals",
    "greater_than",
    "greater_equal",
    "less_than",
    "less_equal",
    "in",
    "all",
    "any",
    "exists",
})


def get_view_field(view: dict[str, Any], field: str) -> Any:
    """Read a dotted field path from the flat view (``pair.gsd_ratio_large``)."""
    return view.get(field)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate_predicate(view_value: Any, operator: str, expected: Any) -> bool:
    """Evaluate one predicate against a view value. Deterministic + total.

    ``expected`` may be None only for equals/not_equals/exists.
    """
    op = str(operator or "").strip()
    if op == "equals":
        return bool(view_value == expected)
    if op == "not_equals":
        return bool(view_value != expected)
    if op == "exists":
        want = True if expected is None else bool(expected)
        present = view_value is not None
        return present if want else (not present)
    if op == "in":
        return isinstance(expected, (list, tuple, set)) and view_value in tuple(expected)
    if op == "all":
        if not isinstance(view_value, (list, tuple, set)) or not isinstance(expected, (list, tuple, set)):
            return False
        return all(item in tuple(view_value) for item in expected)
    if op == "any":
        if not isinstance(view_value, (list, tuple, set)) or not isinstance(expected, (list, tuple, set)):
            return False
        return any(item in tuple(view_value) for item in expected)

    # numeric comparisons: None never satisfies them (never crashes)
    if not _is_number(view_value) or not _is_number(expected):
        return False
    if op == "greater_than":
        return view_value > expected
    if op == "greater_equal":
        return view_value >= expected
    if op == "less_than":
        return view_value < expected
    if op == "less_equal":
        return view_value <= expected
    raise ValueError(f"unsupported predicate operator {operator!r}")


def predicate_outcome(
    view: dict[str, Any],
    predicate: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one configured predicate, returning (truth, detail)."""
    field = str(predicate.get("field") or "")
    operator = str(predicate.get("operator") or "")
    expected = predicate.get("value") if "value" in predicate else None
    view_value = get_view_field(view, field)
    if operator not in OPERATORS:
        raise ValueError(f"predicate for {field!r} uses unsupported operator {operator!r}")
    truth = evaluate_predicate(view_value, operator, expected)
    return {
        "field": field,
        "operator": operator,
        "value": expected,
        "observed": _json_safe(view_value),
        "result": bool(truth),
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return None


__all__ = [
    "OPERATORS",
    "get_view_field",
    "evaluate_predicate",
    "predicate_outcome",
]