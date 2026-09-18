"""M7 canonical metric schema + building/allocation helpers.

Every metric is a self-describing record:

    metric_id          stable identifier (REG-001, SPATIAL-002, ...)
    name               human readable label
    value              float | int | bool | str | list | dict | None
    unit               "px" | "count" | "ratio" | "fraction" | "percent" | "degrees" | "seconds" | ...
    category           OBSERVATION | MEASUREMENT | DIAGNOSTIC | VALIDATION | REFERENCE
    source_milestone   M2..M6 (or M7 for recomputation diagnostics)
    source_artifact    POSIX-relative path of the artefact the value was read from (None if none)
    calculation_method explicit text describing how the value was obtained
    interpretation     what the number does/does not mean
    scientific_status  MEASUREMENT | ENGINEERING | DIAGNOSTIC | REFERENCE | NOT_SCIENTIFIC
    status             AVAILABLE | NOT_RUN | BLOCKED | NOT_APPLICABLE | INSUFFICIENT | FAILED | REFERENCE_UNAVAILABLE
    note               optional; never carries a numeric fabrication

Forbidden terminology (see states.FORBIDDEN_TERMINOLOGY) is rejected anywhere in
a metric record, so no metric can ever smuggle in a claim the project has ruled out.
"""

from __future__ import annotations

from typing import Any

from backend.app.metrics.states import (
    FORBIDDEN_TERMINOLOGY,
    MetricCategory,
    MetricStatus,
    ScientificStatus,
)

# Identifiers reserved for recomputation diagnostics (never user metrics).
METRIC_RECOMPUTATION_MISMATCH = "METRIC_RECOMPUTATION_MISMATCH"


def _scan_for_forbidden(value: Any, path: str) -> list[str]:
    hits: list[str] = []
    if isinstance(value, str):
        low = value.lower()
        for token in FORBIDDEN_TERMINOLOGY:
            if token in low:
                hits.append(f"{path} contains forbidden token '{token}'")
    elif isinstance(value, dict):
        for k, v in value.items():
            hits.extend(_scan_for_forbidden(k, f"{path}.{k}"))
            hits.extend(_scan_for_forbidden(v, f"{path}.{k}"))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            hits.extend(_scan_for_forbidden(v, f"{path}[{i}]"))
    return hits


def assert_no_forbidden_terminology(record: dict) -> None:
    """Raise ValueError if any forbidden token leaks into a metric record."""
    hits = _scan_for_forbidden(record, "metric")
    if hits:
        raise ValueError("; ".join(hits))


def metric(
    metric_id: str,
    name: str,
    value: Any,
    unit: str | None,
    category: MetricCategory | str,
    source_milestone: str,
    source_artifact: str | None,
    calculation_method: str,
    interpretation: str,
    scientific_status: ScientificStatus | str,
    status: MetricStatus | str = MetricStatus.AVAILABLE,
    note: str | None = None,
) -> dict:
    record = {
        "metric_id": metric_id,
        "name": name,
        "value": value,
        "unit": unit,
        "category": category.value if isinstance(category, MetricCategory) else str(category),
        "source_milestone": source_milestone,
        "source_artifact": source_artifact,
        "calculation_method": calculation_method,
        "interpretation": interpretation,
        "scientific_status": scientific_status.value if isinstance(scientific_status, ScientificStatus) else str(scientific_status),
        "status": status.value if isinstance(status, MetricStatus) else str(status),
        "note": note,
    }
    assert_no_forbidden_terminology(record)
    return record


def unavailable_metric(
    metric_id: str,
    name: str,
    unit: str | None,
    category: MetricCategory | str,
    source_milestone: str,
    source_artifact: str | None,
    calculation_method: str,
    interpretation: str,
    status: MetricStatus | str,
) -> dict:
    """Build a metric whose value is None because the stage is not available.

    The value is deliberately None — never a fabricated 0/100%, because a
    blocked stage has no measured value to report.
    """
    return metric(
        metric_id=metric_id,
        name=name,
        value=None,
        unit=unit,
        category=category,
        source_milestone=source_milestone,
        source_artifact=source_artifact,
        calculation_method=calculation_method,
        interpretation=interpretation,
        scientific_status=ScientificStatus.NOT_SCIENTIFIC,
        status=status,
        note="No measured value — stage unavailable. Never reported as fabricated zero.",
    )


def as_records(records: list[dict]) -> list[dict]:
    """Validate a whole record set against the canonical schema + terminology."""
    for r in records:
        for key in (
            "metric_id", "name", "value", "unit", "category", "source_milestone",
            "source_artifact", "calculation_method", "interpretation",
            "scientific_status", "status",
        ):
            if key not in r:
                raise ValueError(f"metric record missing required key '{key}': {r.get('metric_id')}")
        assert_no_forbidden_terminology(r)
    return records