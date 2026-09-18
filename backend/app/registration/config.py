"""M6 registration configuration (RG-M6-001).

Engineering/policy defaults only — explicitly documented as NOT scientifically
calibrated. All numeric fields are coerced defensively (YAML may deliver
exponent strings such as ``1e6``).
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
class TransformConfig:
    preferred_type: str = "homography"
    affine_fallback: bool = True
    min_inliers_for_homography: int = 4
    min_inlier_ratio_for_homography: float = 0.5
    ransac_max_iterations: int = 2000
    ransac_inlier_threshold_px: float = 3.0
    ransac_seed: int = 42
    refine: bool = False


@dataclass(frozen=True)
class ValidationConfig:
    max_symmetric_transfer_px: float = 12.0
    max_residual_mean_px: float = 10.0
    max_residual_median_px: float = 6.0
    max_residual_p95_px: float = 15.0
    min_inlier_ratio: float = 0.3
    min_inliers: int = 6
    max_condition_number: float = 1e6
    check_determinant: bool = True
    min_abs_determinant: float = 1e-6


@dataclass(frozen=True)
class WarpConfig:
    method: str = "forward_mapping"
    output_bounds: str = "target_bounds"
    fill_value: int = 0
    dtype: str = "uint16"
    output_interpolation: str = "linear"
    output_image_format: str = "png"
    visualization_normalization: str = "minmax"
    max_output_rows: int = 20000
    max_output_cols: int = 20000


@dataclass(frozen=True)
class RegistrationExecutionConfig:
    max_runtime_seconds: int = 120


@dataclass(frozen=True)
class RegistrationConfig:
    registration_configuration_id: str = "RG-M6-001"
    registration_configuration_version: str = "1"
    transform: TransformConfig = field(default_factory=TransformConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    warp: WarpConfig = field(default_factory=WarpConfig)
    execution: RegistrationExecutionConfig = field(default_factory=RegistrationExecutionConfig)

    @classmethod
    def from_dict(cls, d: dict) -> RegistrationConfig:
        tr = d.get("transform") or {}
        vl = d.get("validation") or {}
        wp = d.get("warp") or {}
        ex = d.get("execution") or {}
        return cls(
            registration_configuration_id=str(
                d.get("registration_configuration_id", "RG-M6-001")),
            registration_configuration_version=str(
                d.get("registration_configuration_version", "1")),
            transform=TransformConfig(
                preferred_type=str(tr.get("preferred_type", "homography")),
                affine_fallback=bool(tr.get("affine_fallback", True)),
                min_inliers_for_homography=_i(tr.get("min_inliers_for_homography"), 4),
                min_inlier_ratio_for_homography=_f(tr.get("min_inlier_ratio_for_homography"), 0.5),
                ransac_max_iterations=_i(tr.get("ransac_max_iterations"), 2000),
                ransac_inlier_threshold_px=_f(tr.get("ransac_inlier_threshold_px"), 3.0),
                ransac_seed=_i(tr.get("ransac_seed"), 42),
                refine=bool(tr.get("refine", False)),
            ),
            validation=ValidationConfig(
                max_symmetric_transfer_px=_f(vl.get("max_symmetric_transfer_px"), 12.0),
                max_residual_mean_px=_f(vl.get("max_residual_mean_px"), 10.0),
                max_residual_median_px=_f(vl.get("max_residual_median_px"), 6.0),
                max_residual_p95_px=_f(vl.get("max_residual_p95_px"), 15.0),
                min_inlier_ratio=_f(vl.get("min_inlier_ratio"), 0.3),
                min_inliers=_i(vl.get("min_inliers"), 6),
                max_condition_number=_f(vl.get("max_condition_number"), 1e6),
                check_determinant=bool(vl.get("check_determinant", True)),
                min_abs_determinant=_f(vl.get("min_abs_determinant"), 1e-6),
            ),
            warp=WarpConfig(
                method=str(wp.get("method", "forward_mapping")),
                output_bounds=str(wp.get("output_bounds", "target_bounds")),
                fill_value=_i(wp.get("fill_value"), 0),
                dtype=str(wp.get("dtype", "uint16")),
                output_interpolation=str(wp.get("output_interpolation", "linear")),
                output_image_format=str(wp.get("output_image_format", "png")),
                visualization_normalization=str(wp.get("visualization_normalization", "minmax")),
                max_output_rows=_i(wp.get("max_output_rows"), 20000),
                max_output_cols=_i(wp.get("max_output_cols"), 20000),
            ),
            execution=RegistrationExecutionConfig(
                max_runtime_seconds=_i(ex.get("max_runtime_seconds"), 120),
            ),
        )


RG_M6_001 = RegistrationConfig()
