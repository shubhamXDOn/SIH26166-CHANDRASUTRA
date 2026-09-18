"""M7 comparison engine — compare two pairs side-by-side, never rank or declare winners.

A comparison is a paired, per-metric view. Even when a scalar quantity differs
between pairs, no pair is reported as "better"; difference quantification is
strictly descriptive.
"""

from __future__ import annotations

import math

from backend.app.config import rfc3339_now
from backend.app.metrics.reference import reference_dataset_status


def _scalar_diff(a, b):
    """Absolute + relative difference when both values are scalar numbers."""
    try:
        fa = float(a)
        fb = float(b)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(fa) and math.isfinite(fb)):
        return None
    abs_diff = round(abs(fa - fb), 6)
    rel = None
    if abs(fb) > 1e-12:
        rel = round(abs(fa - fb) / abs(fb), 6)
    return {"absolute": abs_diff, "relative": rel}


def build_comparison(pair_a: str, metrics_a: list[dict], pair_b: str, metrics_b: list[dict]) -> dict:
    index_a = {m["metric_id"]: m for m in metrics_a}
    index_b = {m["metric_id"]: m for m in metrics_b}
    ids = sorted(set(index_a) | set(index_b))

    rows = []
    for mid in ids:
        ma = index_a.get(mid)
        mb = index_b.get(mid)
        diff = _scalar_diff((ma or {}).get("value"), (mb or {}).get("value"))
        rows.append({
            "metric_id": mid,
            "name": (ma or mb or {}).get("name"),
            "unit": (ma or mb or {}).get("unit"),
            "category": (ma or mb or {}).get("category"),
            "scientific_status": (ma or mb or {}).get("scientific_status"),
            "pair_a": {
                "pair_id": pair_a,
                "value": (ma or {}).get("value"),
                "status": (ma or {}).get("status", "NOT_RUN"),
            },
            "pair_b": {
                "pair_id": pair_b,
                "value": (mb or {}).get("value"),
                "status": (mb or {}).get("status", "NOT_RUN"),
            },
            "difference": diff,
        })

    return {
        "pair_a": pair_a,
        "pair_b": pair_b,
        "reference": reference_dataset_status(),
        "metrics_compared": len(ids),
        "metrics_only_in_a": len(sorted(set(index_a) - set(index_b))),
        "metrics_only_in_b": len(sorted(set(index_b) - set(index_a))),
        "rows": rows,
        "generated_at_utc": rfc3339_now(),
        "note": (
            "Side-by-side comparison for inspection only. No ranking and no winner; "
            "differences are descriptive and never a judgement of accuracy."
        ),
    }