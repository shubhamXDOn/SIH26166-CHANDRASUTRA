"""M8 SPATIAL SELECTION configuration (SR-M8-001).

Engineering-only thresholds, explicitly recorded in every artifact and never
tuned against downstream registration results (``scientifically_tuned: false``).
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
    edge_policy: str = "REPORT_ONLY"


@dataclass(frozen=True)
class SelectionConfig:
    policy: str = "GRID_BALANCED"
    max_selected: int = 4000
    min_trusted: int = 4
    min_selected: int = 1
    min_per_occupied_cell: int = 1
    min_occupied_cells: int = 4
    tie_break: str = "residual_then_original_index"
    limit_applied_warning: bool = True


@dataclass(frozen=True)
class CoverageConfig:
    low_coverage_ratio: float = 0.25
    concentration_ratio: float = 0.60


@dataclass(frozen=True)
class ExecutionConfig:
    max_runtime_seconds: int = 60


@dataclass(frozen=True)
class SpatialSelectionConfig:
    configuration_id: str = "SR-M8-001"
    configuration_version: str = "1"
    name: str = "Spatial Reliability & Balanced Correspondence Selection"
    derived_rel: str = "metadata/m8_spatial"
    scientifically_tuned: bool = False
    reference_status: str = "REFERENCE_UNAVAILABLE"
    grid: GridConfig = field(default_factory=GridConfig)
    selection: SelectionConfig = field(default_factory=SelectionConfig)
    coverage: CoverageConfig = field(default_factory=CoverageConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    forbidden_vocabulary: tuple[str, ...] = (
        "confidence",
        "final_confidence",
        "best",
        "winner",
        "superior",
    )

    @classmethod
    def from_dict(cls, d: dict) -> "SpatialSelectionConfig":
        d = d or {}
        defaults = d.get("defaults") or {}
        grid = defaults.get("grid") or {}
        sel = defaults.get("selection") or {}
        cov = defaults.get("coverage") or {}
        exe = defaults.get("execution") or {}
        return cls(
            configuration_id=str(d.get("configuration_id", "SR-M8-001")),
            configuration_version=str(d.get("configuration_version", "1")),
            name=str(d.get("name", cls.name)),  # type: ignore[arg-type]
            derived_rel=str(d.get("derived_rel", "metadata/m8_spatial")),
            scientifically_tuned=bool(d.get("scientifically_tuned", False)),
            reference_status=str(defaults.get("reference_status", "REFERENCE_UNAVAILABLE")),
            grid=GridConfig(
                rows=_i(grid.get("rows"), 8),
                cols=_i(grid.get("cols"), 8),
                edge_policy=str(grid.get("edge_policy", "REPORT_ONLY")),
            ),
            selection=SelectionConfig(
                policy=str(sel.get("policy", "GRID_BALANCED")),
                max_selected=_i(sel.get("max_selected"), 4000),
                min_trusted=_i(sel.get("min_trusted"), 4),
                min_selected=_i(sel.get("min_selected"), 1),
                min_per_occupied_cell=_i(sel.get("min_per_occupied_cell"), 1),
                min_occupied_cells=_i(sel.get("min_occupied_cells"), 4),
                tie_break=str(sel.get("tie_break", "residual_then_original_index")),
                limit_applied_warning=bool(sel.get("limit_applied_warning", True)),
            ),
            coverage=CoverageConfig(
                low_coverage_ratio=_f(cov.get("low_coverage_ratio"), 0.25),
                concentration_ratio=_f(cov.get("concentration_ratio"), 0.60),
            ),
            execution=ExecutionConfig(
                max_runtime_seconds=_i(exe.get("max_runtime_seconds"), 60),
            ),
            forbidden_vocabulary=tuple(
                str(v) for v in (defaults.get("forbidden_vocabulary")
                                 or ("confidence", "final_confidence", "best", "winner", "superior"))
            ),
        )


def load_spatial_selection_config() -> SpatialSelectionConfig:
    from ..config import m8_spatial_config

    return SpatialSelectionConfig.from_dict(m8_spatial_config())


SR_M8_001 = SpatialSelectionConfig()