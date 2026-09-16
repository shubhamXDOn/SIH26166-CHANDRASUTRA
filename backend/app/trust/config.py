from __future__ import annotations

from dataclasses import dataclass, field


def _f(value, default: float) -> float:
    """Coerce config scalars to float (YAML may deliver exponent strings)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RansacConfig:
    max_iterations: int = 2000
    inlier_threshold_px: float = 3.0
    confidence: float = 0.995
    seed: int = 42


@dataclass(frozen=True)
class GeometricModelConfig:
    type: str = "homography"
    ransac: RansacConfig = field(default_factory=RansacConfig)


@dataclass(frozen=True)
class CandidateIntegrityConfig:
    min_usable_candidates: int = 8


@dataclass(frozen=True)
class AcceptanceConfig:
    min_inliers: int = 8
    min_inlier_ratio: float = 0.3
    max_residual_mean: float = 10.0
    max_residual_median: float = 6.0
    max_residual_p95: float = 15.0


@dataclass(frozen=True)
class SpatialConfig:
    grid_cells: int = 4
    min_occupied_cells: int = 4
    max_concentration_ratio: float = 0.6


@dataclass(frozen=True)
class DegeneracyConfig:
    min_unique_points: int = 4
    max_condition_number: float = 1e6


@dataclass(frozen=True)
class CrossCheckConfig:
    enabled: bool = True
    max_symmetric_transfer_px: float = 8.0


@dataclass(frozen=True)
class ExecutionConfig:
    max_runtime_seconds: int = 60


@dataclass(frozen=True)
class TrustConfig:
    trust_configuration_id: str = "TG-M4-001"
    trust_configuration_version: str = "1"
    candidate_integrity: CandidateIntegrityConfig = field(default_factory=CandidateIntegrityConfig)
    geometric_model: GeometricModelConfig = field(default_factory=GeometricModelConfig)
    acceptance: AcceptanceConfig = field(default_factory=AcceptanceConfig)
    spatial: SpatialConfig = field(default_factory=SpatialConfig)
    degeneracy: DegeneracyConfig = field(default_factory=DegeneracyConfig)
    cross_check: CrossCheckConfig = field(default_factory=CrossCheckConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    @classmethod
    def from_dict(cls, d: dict) -> TrustConfig:
        ci = d.get("candidate_integrity") or {}
        gm = d.get("geometric_model") or {}
        rs = gm.get("ransac") or {}
        ac = d.get("acceptance") or {}
        sp = d.get("spatial") or {}
        dg = d.get("degeneracy") or {}
        cc = d.get("cross_check") or {}
        ex = d.get("execution") or {}
        return cls(
            trust_configuration_id=d.get("trust_configuration_id", "TG-M4-001"),
            trust_configuration_version=str(d.get("trust_configuration_version", "1")),
            candidate_integrity=CandidateIntegrityConfig(
                min_usable_candidates=int(ci.get("min_usable_candidates", 8)),
            ),
            geometric_model=GeometricModelConfig(
                type=str(gm.get("type", "homography")),
                ransac=RansacConfig(
                    max_iterations=int(rs.get("max_iterations", 2000)),
                    inlier_threshold_px=_f(rs.get("inlier_threshold_px"), 3.0),
                    confidence=_f(rs.get("confidence"), 0.995),
                    seed=int(rs.get("seed", 42)),
                ),
            ),
            acceptance=AcceptanceConfig(
                min_inliers=int(ac.get("min_inliers", 8)),
                min_inlier_ratio=_f(ac.get("min_inlier_ratio"), 0.3),
                max_residual_mean=_f(ac.get("max_residual_mean"), 10.0),
                max_residual_median=_f(ac.get("max_residual_median"), 6.0),
                max_residual_p95=_f(ac.get("max_residual_p95"), 15.0),
            ),
            spatial=SpatialConfig(
                grid_cells=int(sp.get("grid_cells", 4)),
                min_occupied_cells=int(sp.get("min_occupied_cells", 4)),
                max_concentration_ratio=_f(sp.get("max_concentration_ratio"), 0.6),
            ),
            degeneracy=DegeneracyConfig(
                min_unique_points=int(dg.get("min_unique_points", 4)),
                max_condition_number=_f(dg.get("max_condition_number"), 1e6),
            ),
            cross_check=CrossCheckConfig(
                enabled=bool(cc.get("enabled", True)),
                max_symmetric_transfer_px=_f(cc.get("max_symmetric_transfer_px"), 8.0),
            ),
            execution=ExecutionConfig(
                max_runtime_seconds=int(ex.get("max_runtime_seconds", 60)),
            ),
        )


TG_M4_001 = TrustConfig()
