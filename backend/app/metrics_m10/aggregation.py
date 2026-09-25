"""Descriptive aggregation over settled M10 rows.

Rules per the milestone spec:

    * descriptive only -- never a winner/best/superior/accuracy claim;
    * median preferred for skewed residuals; mean always reported with median;
    * missing measurements are aggregated over the *observed* sample only and
      reported with their sample count (never zero-filled);
    * deltas between a variant and the baseline (V1) are descriptive
      differences (\"V5 - V1\") with an explicit no-claim note.

``forbidden_vocabulary`` from ``states.py`` is enforced at the row boundary
(schema.build_row); aggregation adds nothing beyond that vocabulary.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

from .states import FORBIDDEN_VOCABULARY
from .variants import Variant

_LOCAL_FORBIDDEN = (
    "winner",
    "best",
    "superior",
    "optimal",
    "accuracy",
    "geolocation",
    "confidence",
    "CE90",
    "LE90",
)


def _assert_safe(label: str) -> None:
    low = label.lower()
    if any(t in low for t in _LOCAL_FORBIDDEN):
        raise ValueError("forbidden aggregation label: %s" % label)


def _metric_values(rows: Iterable[dict[str, Any]], key: str) -> list[Any]:
    values: list[Any] = []
    for row in rows:
        if row.get("stage") != "registration" and key.startswith("registration_"):
            continue
        v = row.get(key)
        if v is not None:
            values.append(v)
    return values


def _stat(values: list[Any], fn) -> float | int | None:
    if not values:
        return None
    try:
        nums = [float(v) for v in values if v is not None]
        if not nums:
            return None
        r = fn(nums)
        if isinstance(r, float) and r.is_integer():
            return int(r)
        return r
    except (TypeError, ValueError, statistics.StatisticsError):
        return None


def p90(values: list[Any]) -> float | None:
    if not values:
        return None
    nums = sorted(float(v) for v in values if v is not None)
    if not nums:
        return None
    i = max(0, int(0.9 * (len(nums) - 1)))
    return nums[i]


def p95(values: list[Any]) -> float | None:
    if not values:
        return None
    nums = sorted(float(v) for v in values if v is not None)
    if not nums:
        return None
    i = max(0, int(0.95 * (len(nums) - 1)))
    return nums[i]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a set of schema rows into median/mean/p90/p95/pMax + counts."""
    out: dict[str, Any] = {"row_count": len(rows), "metrics": {}, "no_claim": True}
    for key in (
        "candidate_count",
        "verified_count",
        "inlier_count",
        "selected_count",
        "registered_count",
        "registration_rmse_px",
        "registration_p95_px",
        "runtime_ms",
    ):
        values = _metric_values(rows, key)
        if not values:
            out["metrics"][key] = None
            continue
        out["metrics"][key] = {
            "n": len(values),
            "min": _stat(values, min),
            "max": _stat(values, max),
            "mean": _stat(values, statistics.mean),
            "median": _stat(values, statistics.median),
            "p90": _stat(values, p90),
            "p95": _stat(values, p95),
            "note": "median-preferred descriptive statistic; no accuracy claim",
        }
    return out


def delta(baseline_rows: list[dict[str, Any]], variant_rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    """Descriptive delta (baseline vs variant) for one variant row-set."""
    _assert_safe(label)
    base = {r["variant_id"]: r for r in baseline_rows}
    var = {r["variant_id"]: r for r in variant_rows}
    keys = {
        "candidate_count",
        "verified_count",
        "inlier_count",
        "selected_count",
        "registered_count",
        "registration_rmse_px",
        "registration_p95_px",
    }
    out: dict[str, Any] = {"variant_label": label, "delta": {}, "scale": "DESCRIPTIVE", "no_claim": True}
    for key in keys:
        a = base.get("V1", {}).get(key) if "V1" in base else None
        b = next(iter(var.values()), {}).get(key) if var else None
        if a is None and b is None:
            out["delta"][key] = None
        elif a is None or b is None:
            out["delta"][key] = {"baseline": a, "variant": b, "diff": None,
                                 "note": "unmatched sample; differential not computed"}
        else:
            try:
                out["delta"][key] = {"baseline": a, "variant": b, "diff": b - a}
            except TypeError:
                out["delta"][key] = {"baseline": a, "variant": b, "diff": None}
    return out