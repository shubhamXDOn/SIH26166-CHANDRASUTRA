"""M9 REGISTRATION configuration (RG-M9-001).

Engineering-only thresholds, explicitly recorded in every artifact and never
tuned against a final benchmark to force acceptance
(``scientifically_tuned: false``). All registration residuals are in px of the
effective matcher plane and are geometric measurements, never physical
accuracy claims.
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


def _s(value, default: str) -> str:
    return str(value) if value not in (None, "") else default


@dataclass(frozen=True)
class ModelConfig:
    preference: str = "smallest_valid"
    min_points_affine: int = 4
    min_points_homography: int = 5
    normalized_dlt: bool = True


@dataclass(frozen=True)
class ValidationConfig:
    max_rmse_px: float = 3.0
    max_p95_px: float = 5.0
    max_residual_max_px: float = 10.0
    max_transform_condition: float = 1e6
    min_abs_determinant: float = 1e-4
    max_abs_coefficient: float = 1e4
    min_homography_denominator: float = 1e-6
    max_scale_change: float = 20.0
    min_scale_factor: float = 1e-3


@dataclass(frozen=True)
class WarpConfig:
    interpolation: str = "linear"
    border_mode: str = "constant"
    fill_value: int = 0
    dtype: str = "uint16"
    output_dimensions: str = "target_b_frame"
    max_output_rows: int = 32768
    max_output_cols: int = 32768


@dataclass(frozen=True)
class ExecutionConfig:
    max_runtime_seconds: int = 120


@dataclass(frozen=True)
class RegistrationM9Config:
    configuration_id: str = "RG-M9-001"
    configuration_version: str = "1"
    name: str = "Registration & Image Alignment — smallest-valid declared transform over M8-selected correspondences"
    derived_rel: str = "metadata/m9_registration"
    scientifically_tuned: bool = False
    reference_status: str = "REFERENCE_UNAVAILABLE"
    model: ModelConfig = field(default_factory=ModelConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    warp: WarpConfig = field(default_factory=WarpConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    forbidden_vocabulary: tuple[str, ...] = (
        "confidence",
        "final_confidence",
        "best",
        "winner",
        "superior",
        "perfect",
        "accurate",
    )

    @classmethod
    def from_dict(cls, d: dict) -> "RegistrationM9Config":
        d = d or {}
        defaults = d.get("defaults") or {}
        model = defaults.get("model") or {}
        val = defaults.get("validation") or {}
        wp = defaults.get("warp") or {}
        exe = defaults.get("execution") or {}
        return cls(
            configuration_id=_s(d.get("configuration_id"), "RG-M9-001"),
            configuration_version=str(d.get("configuration_version", "1")),
            name=str(d.get("name", cls.name)),  # type: ignore[arg-type]
            derived_rel=_s(d.get("derived_rel"), "metadata/m9_registration"),
            scientifically_tuned=bool(d.get("scientifically_tuned", False)),
            reference_status=_s(defaults.get("reference_status"), "REFERENCE_UNAVAILABLE"),
            model=ModelConfig(
                preference=_s(model.get("preference"), "smallest_valid"),
                min_points_affine=_i(model.get("min_points_affine"), 4),
                min_points_homography=_i(model.get("min_points_homography"), 5),
                normalized_dlt=bool(model.get("normalized_dlt", True)),
            ),
            validation=ValidationConfig(
                max_rmse_px=_f(val.get("max_rmse_px"), 3.0),
                max_p95_px=_f(val.get("max_p95_px"), 5.0),
                max_residual_max_px=_f(val.get("max_residual_max_px"), 10.0),
                max_transform_condition=_f(val.get("max_transform_condition"), 1e6),
                min_abs_determinant=_f(val.get("min_abs_determinant"), 1e-4),
                max_abs_coefficient=_f(val.get("max_abs_coefficient"), 1e4),
                min_homography_denominator=_f(val.get("min_homography_denominator"), 1e-6),
                max_scale_change=_f(val.get("max_scale_change"), 20.0),
                min_scale_factor=_f(val.get("min_scale_factor"), 1e-3),
            ),
            warp=WarpConfig(
                interpolation=_s(wp.get("interpolation"), "linear"),
                border_mode=_s(wp.get("border_mode"), "constant"),
                fill_value=_i(wp.get("fill_value"), 0),
                dtype=_s(wp.get("dtype"), "uint16"),
                output_dimensions=_s(wp.get("output_dimensions"), "target_b_frame"),
                max_output_rows=_i(wp.get("max_output_rows"), 32768),
                max_output_cols=_i(wp.get("max_output_cols"), 32768),
            ),
            execution=ExecutionConfig(
                max_runtime_seconds=_i(exe.get("max_runtime_seconds"), 120),
            ),
            forbidden_vocabulary=tuple(
                str(v) for v in (defaults.get("forbidden_vocabulary")
                                 or ("confidence", "final_confidence", "best",
                                     "winner", "superior", "perfect", "accurate"))
            ),
        )


def load_registration_m9_config() -> RegistrationM9Config:
    from ..config import m9_registration_config

    return RegistrationM9Config.from_dict(m9_registration_config())


RG_M9_001 = RegistrationM9Config()