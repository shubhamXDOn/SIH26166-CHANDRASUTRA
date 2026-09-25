"""Metric row schema + forbidden vocabulary enforcement.

Every metric row that leaves M10 passes through :func:`build_row`, which
guarantees:

    * a stable, documented set of keys (schema version MET-M10D-001);
    * explicit ``None`` for unobserved measurements (never zero-fill, so an
      absent count is never mistaken for a yielded value);
    * ``state`` carries the settled run state only (COMPLETE / FAILED /
      ABSTAIN / BLOCKED), never a quality verdict;
    * the forbidden vocabulary (winner/best/accuracy/confidence/...) is
      rejected at the boundary, so no downstream report can emit it.
"""

from __future__ import annotations

from typing import Any

from .states import FORBIDDEN_VOCABULARY

SCHEMA_VERSION = "MET-M10D-001"

ROW_KEYS = (
    "pair_id",
    "variant_id",
    "variant_name",
    "state",
    "stage",
    "candidate_count",
    "verified_count",
    "inlier_count",
    "selected_count",
    "registered_count",
    "registration_rmse_px",
    "registration_p95_px",
    "runtime_ms",
    "ablation",
    "availability",
    "notes",
)


class ForbiddenVocabularyError(ValueError):
    """Raised when a metric row would emit a forbidden claim."""


def scan_forbidden(text: str | None, *, field: str = "notes") -> None:
    """Raise if a forbidden vocabulary token is present in arbitrary text."""
    if not text:
        return
    lower = text.lower()
    for token in FORBIDDEN_VOCABULARY:
        if token in lower:
            raise ForbiddenVocabularyError(
                "forbidden vocabulary '%s' in %s" % (token, field)
            )


def build_row(pair_id: str, variant: Any, **fields: Any) -> dict[str, Any]:
    """Build a schema-compliant metric row.

    ``variant`` may be a :class:`~.variants.Variant` or any object exposing
    ``id``/``name``/``ablation``/``availability``.  Values are kept as-is but
    the row only ever keeps the documented key set.
    """
    stage = fields.get("stage") or "input_gate"
    notes = fields.get("notes") or ""
    scan_forbidden(str(fields.get("state", "")), field="state")
    scan_forbidden(notes, field="notes")

    row = {
        "pair_id": pair_id,
        "variant_id": getattr(variant, "id", variant.get("id", "")) if isinstance(variant, dict) else getattr(variant, "id", ""),
        "variant_name": getattr(variant, "name", variant.get("name", "")) if isinstance(variant, dict) else getattr(variant, "name", ""),
        "state": fields.get("state") or "NOT_STARTED",
        "stage": stage,
        "candidate_count": fields.get("candidate_count"),
        "verified_count": fields.get("verified_count"),
        "inlier_count": fields.get("inlier_count"),
        "selected_count": fields.get("selected_count"),
        "registered_count": fields.get("registered_count"),
        "registration_rmse_px": fields.get("registration_rmse_px"),
        "registration_p95_px": fields.get("registration_p95_px"),
        "runtime_ms": fields.get("runtime_ms"),
        "ablation": (getattr(variant, "ablation", None) if not isinstance(variant, dict) else variant.get("ablation")) or "none",
        "availability": (getattr(variant, "availability", None) if not isinstance(variant, dict) else variant.get("availability"))
        or "AVAILABLE",
        "notes": notes or None,
    }
    return {k: row[k] for k in ROW_KEYS}