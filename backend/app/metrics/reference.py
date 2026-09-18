"""Reference dataset abstraction (directive: reference layer, default NOT_AVAILABLE).

M7 never consoles numbers with fabricated ground truth. A reference dataset
provides independent truth observations (e.g. high-grade tie-points or a
controlled test set) against which metrics could be validated. No such dataset
is wired in for CHANDRASUTRA M7: real-data truth requires PRADAN approval, so
every reference comparison reports REFERENCE_UNAVAILABLE instead of a number.
"""

from __future__ import annotations

from dataclasses import dataclass

# No external reference dataset is integrated at M7. Changing this constant is
# the single, discoverable point where real reference data would be enabled.
REFERENCE_DATASET = "NOT_AVAILABLE"
REFERENCE_DATASET_NOTE = (
    "No external reference/ground-truth dataset is integrated. "
    "Real-data truth requires PRADAN approval; until then all reference "
    "comparisons report REFERENCE_UNAVAILABLE and physical_accuracy is NOT_AVAILABLE."
)


@dataclass(frozen=True)
class ReferenceObservation:
    """A single reference truth observation (source documented when present)."""

    source: str
    target_frame: str
    coordinate_unit: str | None
    point_count: int | None


@dataclass(frozen=True)
class ReferenceMetric:
    """A reference-protocol metric. Never a comparison result without a dataset."""

    name: str
    status: str  # MetricStatus
    value: object | None
    unit: str | None
    note: str


def reference_metric(name: str, unit: str | None) -> ReferenceMetric:
    if REFERENCE_DATASET == "NOT_AVAILABLE":
        return ReferenceMetric(
            name=name,
            status="REFERENCE_UNAVAILABLE",
            value=None,
            unit=unit,
            note=REFERENCE_DATASET_NOTE,
        )
    return ReferenceMetric(
        name=name,
        status="NOT_RUN",
        value=None,
        unit=unit,
        note="Reference dataset configured but protocol not executed.",
    )


def reference_dataset_status() -> dict:
    return {
        "reference_dataset": REFERENCE_DATASET,
        "note": REFERENCE_DATASET_NOTE,
    }