"""M7 TRUST GATE configuration (TG-M7-001). Engineering-only thresholds.

Every threshold is explicit and persisted in the artifact; none is tuned
against downstream registration results (``scientifically_tuned: false``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _f(value, default: float) -> float:
    """Coerce config scalars to float (YAML may deliver exponent strings)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RansacGateConfig:
    max_iterations: int = 2000
    inlier_threshold_px: float = 4.0
    confidence_parameter: float = 0.99
    seed: int = 20260923


@dataclass(frozen=True)
class GeometryGateConfig:
    models: tuple[str, ...] = ("affine", "homography")
    preferred_model: str = "affine"
    attempt_hierarchy: bool = True
    ransac: RansacGateConfig = field(default_factory=RansacGateConfig)


@dataclass(frozen=True)
class DecisionGateConfig:
    zero_candidates: str = "ABSTAIN"
    min_candidates: int = 8
    min_inliers: int = 8
    min_inlier_ratio: float = 0.30
    max_residual_rmse_px: float = 8.0
    max_residual_median_px: float = 5.0
    max_residual_p95_px: float = 12.0
    max_runtime_seconds: int = 60


@dataclass(frozen=True)
class DegeneracyGateConfig:
    min_unique_points: int = 6
    max_condition_number: float = 1e6


@dataclass(frozen=True)
class SpatialSanityGateConfig:
    min_extent_px: float = 5.0
    strip_ratio_warn: float = 0.02


@dataclass(frozen=True)
class DuplicatesGateConfig:
    policy: str = "keep_first_record_counts"


@dataclass(frozen=True)
class ResourceGateConfig:
    max_candidates: int = 500000


@dataclass(frozen=True)
class TrustGateConfig:
    configuration_id: str = "TG-M7-001"
    configuration_version: str = "1"
    name: str = "Trust Gate — Geometric Verification of Candidate Correspondences"
    derived_rel: str = "metadata/m7_trust"
    scientifically_tuned: bool = False
    reference_status: str = "REFERENCE_UNAVAILABLE"
    decision: DecisionGateConfig = field(default_factory=DecisionGateConfig)
    geometry: GeometryGateConfig = field(default_factory=GeometryGateConfig)
    degeneracy: DegeneracyGateConfig = field(default_factory=DegeneracyGateConfig)
    spatial_sanity: SpatialSanityGateConfig = field(default_factory=SpatialSanityGateConfig)
    duplicates: DuplicatesGateConfig = field(default_factory=DuplicatesGateConfig)
    resource: ResourceGateConfig = field(default_factory=ResourceGateConfig)
    forbidden_vocabulary: tuple[str, ...] = (
        "confidence",
        "final_confidence",
        "best",
        "winner",
        "superior",
    )

    @classmethod
    def from_dict(cls, d: dict) -> "TrustGateConfig":
        d = d or {}
        dec = d.get("decision") or {}
        g = d.get("geometry") or {}
        rs = g.get("ransac") or {}
        dg = d.get("degeneracy") or {}
        sp = d.get("spatial_sanity") or {}
        du = d.get("duplicates") or {}
        res = d.get("resource") or {}
        models = tuple(str(m) for m in (g.get("models") or ("affine", "homography")))
        return cls(
            configuration_id=str(d.get("configuration_id", "TG-M7-001")),
            configuration_version=str(d.get("configuration_version", "1")),
            name=str(d.get("name", cls.name)),  # type: ignore[arg-type]
            derived_rel=str(d.get("derived_rel", "metadata/m7_trust")),
            scientifically_tuned=bool(d.get("scientifically_tuned", False)),
            reference_status=str(d.get("reference_status", "REFERENCE_UNAVAILABLE")),
            decision=DecisionGateConfig(
                zero_candidates=str(dec.get("zero_candidates", "ABSTAIN")),
                min_candidates=_i(dec.get("min_candidates"), 8),
                min_inliers=_i(dec.get("min_inliers"), 8),
                min_inlier_ratio=_f(dec.get("min_inlier_ratio"), 0.30),
                max_residual_rmse_px=_f(dec.get("max_residual_rmse_px"), 8.0),
                max_residual_median_px=_f(dec.get("max_residual_median_px"), 5.0),
                max_residual_p95_px=_f(dec.get("max_residual_p95_px"), 12.0),
                max_runtime_seconds=_i(dec.get("max_runtime_seconds"), 60),
            ),
            geometry=GeometryGateConfig(
                models=models,
                preferred_model=str(g.get("preferred_model", "affine")),
                attempt_hierarchy=bool(g.get("attempt_hierarchy", True)),
                ransac=RansacGateConfig(
                    max_iterations=_i(rs.get("max_iterations"), 2000),
                    inlier_threshold_px=_f(rs.get("inlier_threshold_px"), 4.0),
                    confidence_parameter=_f(rs.get("confidence_parameter"), 0.99),
                    seed=_i(rs.get("seed"), 20260923),
                ),
            ),
            degeneracy=DegeneracyGateConfig(
                min_unique_points=_i(dg.get("min_unique_points"), 6),
                max_condition_number=_f(dg.get("max_condition_number"), 1e6),
            ),
            spatial_sanity=SpatialSanityGateConfig(
                min_extent_px=_f(sp.get("min_extent_px"), 5.0),
                strip_ratio_warn=_f(sp.get("strip_ratio_warn"), 0.02),
            ),
            duplicates=DuplicatesGateConfig(
                policy=str(du.get("policy", "keep_first_record_counts")),
            ),
            resource=ResourceGateConfig(
                max_candidates=_i(res.get("max_candidates"), 500000),
            ),
            forbidden_vocabulary=tuple(
                str(v) for v in (d.get("forbidden_vocabulary")
                                 or ("confidence", "final_confidence", "best", "winner", "superior"))
            ),
        )


def load_trust_gate_config() -> TrustGateConfig:
    from ..config import m7_trust_gate_config

    return TrustGateConfig.from_dict(m7_trust_gate_config())


TG_M7_001 = TrustGateConfig()