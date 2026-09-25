"""Variant matrix for M10 benchmarks (V1..V6).

The matrix models *viewpoints over the same settled artefacts* -- it never
re-executes matcher/trust/spatial/registration logic. Each variant selects a
slightly different read/aggregation posture:

    V1 FIXED_CLASSICAL_BASELINE      classic M3 baseline reads
    V2 FIXED_ALTERNATE_CLASSICAL     alternate classical family (availability-gated)
    V3 FIXED_DEEP                    deep matcher family (availability-gated)
    V4 ROUTED_FULL_ADAPTIVE_RELIABILITY  exact routed pipeline chain
    V5 TRUST_DISABLED_ABLATION       ablation: trust gate DISABLED_FOR_ABLATION
    V6 SPATIAL_DISABLED_ABLATION     ablation: spatial selection DISABLED_FOR_ABLATION

V5/V6 are OFFLINE analyses. Their downstream stages are reported as
OFFLINE_ABLATION / NOT_RUN rather than fabricating a registration outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    routing: str = "ROUTED"
    trust_gate: str = "ENABLED"
    spatial_selection: str = "ENABLED"
    pipeline_variant: str = "FULL_ADAPTIVE_RELIABILITY"
    ablation: str = "none"
    availability: str = "AVAILABLE"
    description: str = ""

    def requires_deep(self) -> bool:
        return self.routing == "FIXED_DEEP"

    def requires_alternate_classical(self) -> bool:
        return self.routing == "FIXED_ALTERNATE_CLASSICAL"

    def is_ablation(self) -> bool:
        return self.trust_gate == "DISABLED_FOR_ABLATION" or self.spatial_selection == "DISABLED_FOR_ABLATION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "variant_id": self.id,
            "name": self.name,
            "routing": self.routing,
            "trust_gate": self.trust_gate,
            "spatial_selection": self.spatial_selection,
            "pipeline_variant": self.pipeline_variant,
            "ablation": self.ablation,
            "availability": self.availability,
            "description": self.description,
        }


DEFAULT_VARIANTS: tuple[Variant, ...] = (
    Variant(
        id="V1",
        name="FIXED_CLASSICAL_BASELINE",
        routing="FIXED_CLASSICAL",
        trust_gate="ENABLED",
        spatial_selection="ENABLED",
        pipeline_variant="FIXED_CLASSICAL",
        description="classic M3 baseline read of settled artefacts",
    ),
    Variant(
        id="V2",
        name="FIXED_ALTERNATE_CLASSICAL",
        routing="FIXED_ALTERNATE_CLASSICAL",
        trust_gate="ENABLED",
        spatial_selection="ENABLED",
        pipeline_variant="FIXED_ALTERNATE_CLASSICAL",
        availability="NOT_AVAILABLE",
        description="alternate classical family, availability-gated",
    ),
    Variant(
        id="V3",
        name="FIXED_DEEP",
        routing="FIXED_DEEP",
        trust_gate="ENABLED",
        spatial_selection="ENABLED",
        pipeline_variant="FIXED_DEEP",
        availability="NOT_AVAILABLE",
        description="deep matcher family, availability-gated",
    ),
    Variant(
        id="V4",
        name="ROUTED_FULL_ADAPTIVE_RELIABILITY",
        routing="ROUTED",
        trust_gate="ENABLED",
        spatial_selection="ENABLED",
        pipeline_variant="FULL_ADAPTIVE_RELIABILITY",
        description="exact routed M6->M9 chain",
    ),
    Variant(
        id="V5",
        name="TRUST_DISABLED_ABLATION",
        routing="ROUTED",
        trust_gate="DISABLED_FOR_ABLATION",
        spatial_selection="ENABLED",
        pipeline_variant="FULL_ADAPTIVE_RELIABILITY",
        ablation="trust_gate_disabled",
        description="offline ablation: trust gate disabled",
    ),
    Variant(
        id="V6",
        name="SPATIAL_DISABLED_ABLATION",
        routing="ROUTED",
        trust_gate="ENABLED",
        spatial_selection="DISABLED_FOR_ABLATION",
        pipeline_variant="FULL_ADAPTIVE_RELIABILITY",
        ablation="spatial_selection_disabled",
        description="offline ablation: spatial selection disabled",
    ),
)


def variants_from_config(config_variants: Any) -> list[Variant]:
    """Build the variant matrix from the ``m10_metrics`` config block.

    Configured records override baseline posture; missing configured records
    fall back to the documented defaults.  Ablation records keep their
    offline semantics regardless of config spelling.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for item in config_variants or []:
        vid = str(item.get("id", "")).strip()
        if vid:
            by_id[vid] = dict(item)

    out: list[Variant] = []
    for base in DEFAULT_VARIANTS:
        rec = by_id.get(base.id)
        if not rec:
            out.append(base)
            continue
        trust = str(rec.get("trust_gate", base.trust_gate)).upper()
        spatial = str(rec.get("spatial_selection", base.spatial_selection)).upper()
        if trust == "DISABLED_FOR_ABLATION" or spatial == "DISABLED_FOR_ABLATION":
            ablation = (
                "trust_gate_disabled" if trust == "DISABLED_FOR_ABLATION" else "spatial_selection_disabled"
            )
        else:
            ablation = "none"
        out.append(
            Variant(
                id=base.id,
                name=str(rec.get("name", base.name)),
                routing=str(rec.get("routing", base.routing)).upper(),
                trust_gate=trust,
                spatial_selection=spatial,
                pipeline_variant=str(rec.get("pipeline_variant", base.pipeline_variant)),
                ablation=ablation,
                availability=str(rec.get("availability", base.availability)).upper(),
                description=str(rec.get("description", base.description)),
            )
        )
    return out