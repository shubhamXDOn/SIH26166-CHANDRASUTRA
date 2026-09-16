"""M5 spatial reliability configuration (SR-M5-001).

Engineering/policy defaults only — explicitly documented as NOT scientifically
calibrated lunar thresholds. All numeric fields are coerced defensively
(YAML may deliver exponent strings such as ``1e6``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _f(value, default: float) -> float:
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
class GridConfig:
    rows: int = 8
    cols: int = 8
    edge_tolerance_px: float = 0.5


@dataclass(frozen=True)
class ReliabilityConfig:
    min_verified_inliers_per_cell: int = 4
    min_trusted_tiles_per_cell: int = 1


@dataclass(frozen=True)
class NeighborhoodConfig:
    support_radius_cells: int = 1


@dataclass(frozen=True)
class FragmentationConfig:
    enabled: bool = True


@dataclass(frozen=True)
class BoundaryConfig:
    edge_policy: str = "REPORT_ONLY"  # REPORT_ONLY | EXPOSE | EXCLUDE


@dataclass(frozen=True)
class ConnectedComponentsConfig:
    connectivity: int = 8  # 4 or 8


@dataclass(frozen=True)
class SelectionConfig:
    mode: str = "SUPPORTED_REGION"
    min_component_cells: int = 4
    min_component_correspondences: int = 16
    min_selected_region_cells: int = 4
    max_selected_correspondences: int = 4000
    deterministic_ordering: str = "largest_evidence_first"


@dataclass(frozen=True)
class SpatialExecutionConfig:
    max_runtime_seconds: int = 60


@dataclass(frozen=True)
class SpatialReliabilityConfig:
    spatial_reliability_configuration_id: str = "SR-M5-001"
    spatial_reliability_configuration_version: str = "1"
    coordinate_space: str = "pair_overlap_normalized"
    grid: GridConfig = field(default_factory=GridConfig)
    reliability: ReliabilityConfig = field(default_factory=ReliabilityConfig)
    neighborhood: NeighborhoodConfig = field(default_factory=NeighborhoodConfig)
    fragmentation: FragmentationConfig = field(default_factory=FragmentationConfig)
    boundary: BoundaryConfig = field(default_factory=BoundaryConfig)
    connected_components: ConnectedComponentsConfig = field(default_factory=ConnectedComponentsConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    execution: SpatialExecutionConfig = field(default_factory=SpatialExecutionConfig)

    @classmethod
    def from_dict(cls, d: dict) -> SpatialReliabilityConfig:
        gr = d.get("grid") or {}
        re = d.get("reliability") or {}
        nh = d.get("neighborhood") or {}
        fr = d.get("fragmentation") or {}
        bd = d.get("boundary") or {}
        cc = d.get("connected_components") or {}
        se = d.get("selection") or {}
        ex = d.get("execution") or {}
        return cls(
            spatial_reliability_configuration_id=str(
                d.get("spatial_reliability_configuration_id", "SR-M5-001")),
            spatial_reliability_configuration_version=str(
                d.get("spatial_reliability_configuration_version", "1")),
            coordinate_space=str(d.get("coordinate_space", "pair_overlap_normalized")),
            grid=GridConfig(
                rows=_i(gr.get("rows"), 8),
                cols=_i(gr.get("cols"), 8),
                edge_tolerance_px=_f(gr.get("edge_tolerance_px"), 0.5),
            ),
            reliability=ReliabilityConfig(
                min_verified_inliers_per_cell=_i(re.get("min_verified_inliers_per_cell"), 4),
                min_trusted_tiles_per_cell=_i(re.get("min_trusted_tiles_per_cell"), 1),
            ),
            neighborhood=NeighborhoodConfig(
                support_radius_cells=_i(nh.get("support_radius_cells"), 1),
            ),
            fragmentation=FragmentationConfig(
                enabled=bool(fr.get("enabled", True)),
            ),
            boundary=BoundaryConfig(
                edge_policy=str(bd.get("edge_policy", "REPORT_ONLY")),
            ),
            connected_components=ConnectedComponentsConfig(
                connectivity=_i(cc.get("connectivity"), 8),
            ),
            selection=SelectionConfig(
                mode=str(se.get("mode", "SUPPORTED_REGION")),
                min_component_cells=_i(se.get("min_component_cells"), 4),
                min_component_correspondences=_i(se.get("min_component_correspondences"), 16),
                min_selected_region_cells=_i(se.get("min_selected_region_cells"), 4),
                max_selected_correspondences=_i(se.get("max_selected_correspondences"), 4000),
                deterministic_ordering=str(se.get("deterministic_ordering", "largest_evidence_first")),
            ),
            execution=SpatialExecutionConfig(
                max_runtime_seconds=_i(ex.get("max_runtime_seconds"), 60),
            ),
        )

    def selection_policy(self) -> dict:
        s = self.selection
        return {
            "mode": s.mode,
            "min_component_cells": s.min_component_cells,
            "min_component_correspondences": s.min_component_correspondences,
            "min_selected_region_cells": s.min_selected_region_cells,
            "max_selected_correspondences": s.max_selected_correspondences,
            "deterministic_ordering": s.deterministic_ordering,
        }


SR_M5_001 = SpatialReliabilityConfig()