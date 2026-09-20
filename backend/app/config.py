"""SIH26166 — configuration foundation.

Two complementary sources:

1. ``Settings``  — environment / runtime configuration loaded from the real
   environment and ``.env`` via pydantic-settings. Used for secrets, runtime
   tuning, CORS, logging, data roots. Secret values are masked.
2. ``PipelineConfig`` — reproducible engineering defaults and *future*
   placeholder parameters for the scientific pipeline, loaded from
   ``configs/app.yaml``. Every placeholder threshold is clearly marked as an
   engineering default to be replaced by experiment-tuned values in later
   milestones (Pair ID / Configuration ID based).

Secrets are never hardcoded here and never logged.
"""

from __future__ import annotations

import dataclasses
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Root of the repository, resolved from the location of this file.
# backend/app/config.py -> backend/app -> backend -> repo root
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_ROOT_DEFAULT = BASE_DIR / "data"
CONFIG_FILE_DEFAULT = BASE_DIR / "configs" / "app.yaml"

# M11 environment separation: the only values APP_ENV may take.
_APP_ENVS = ("development", "demo", "production", "test")


class Settings(BaseSettings):
    """Runtime/environment settings. Values come from env and .env."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "SIH26166"
    product_name: str = "CHANDRASUTRA"
    tagline: str = "Trustworthy Lunar Image Intelligence"
    milestone: str = "M11"
    app_env: str = "development"  # development | demo | production | test
    app_debug: bool = True
    app_version: str = "0.11.0"

    # M13 final release presentation. Kept distinct from app_version on
    # purpose: app_version is the M11 operations stage identity recorded in
    # the frozen configuration chain, so it must not change or the M12
    # configuration freeze reports DRIFT. These release fields are present-
    # ation only and never enter the frozen fingerprint.
    release_version: str = "1.0.0"
    release_milestone: str = "M13"

    # M11 environment separation. ``demo`` is like production but is allowed to
    # show clearly-labelled synthetic workflows (never as real lunar evidence).
    # Normalized/validated by the app_env field validator below.
    http_max_body_bytes: int = 8_000_000

    # M11 operational hygiene: a stale RUNNING run whose lock is older than
    # this many seconds is treated as an interrupted run, never as a live one.
    run_stale_budget_seconds: int = 600

    # M11 demo mode: when true the UI/API add a persistent, explicit
    # "Synthetic demonstration — not a real lunar observation" marker. The
    # scientific pipeline never uses this flag to fabricate real-looking
    # results; it only makes the distinction visible.
    demo_mode: bool = False

    # M11 request correlation: the header we accept/emit for a stable request
    # ID. Incoming values are validated before they are echoed back.
    request_id_header: str = "x-request-id"

    @field_validator("app_env", mode="before")
    @classmethod
    def _normalize_app_env(cls, value: Any) -> str:
        if value is None:
            return "development"
        env = str(value).strip().lower()
        if env not in _APP_ENVS:
            raise ValueError(
                f"APP_ENV must be one of {', '.join(_APP_ENVS)}; got {value!r}"
            )
        return env

    # M8 deep matcher model/location configuration. Weights are NEVER
    # downloaded by the application. When this directory (or the default
    # data_root/models/m8) does not contain the required weight files, the
    # deep matchers truthfully report MODEL_WEIGHTS_NOT_CONFIGURED.
    m8_model_dir: str = ""

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    data_root: str = ""

    # --- Security (M10 real authentication; secret is env-only) ---
    auth_secret_key: str = ""
    auth_token_expire_minutes: int = 60
    auth_algorithm: str = "HS256"

    # M10 authentication runtime configuration. The signing secret is the only
    # secret here; everything else is non-sensitive engineering policy that is
    # also mirrored in configs/app.yaml (AU-M10-001).
    auth_db_path: str = ""  # default: <data_root>/auth/auth.db
    auth_issuer: str = ""  # default: app_name
    auth_audience: str = "chandrasutra-api"
    auth_access_ttl_seconds: int = 0  # 0 -> m10 config default (900)
    auth_refresh_ttl_seconds: int = 0  # 0 -> m10 config default (604800)
    auth_register_enabled: bool = True
    auth_refresh_cookie_name: str = "chandrasutra_refresh"
    auth_cookie_secure: bool = False  # forced on in production by cookie helper
    auth_cookie_samesite: str = "strict"
    auth_bootstrap_admin_username: str = ""
    auth_bootstrap_admin_password: str = ""

    # --- AI / Gemini (optional in M0) ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # M9 AI runtime tuning (non-secret). Bounds are enforced client-side so
    # a request can never grow unbounded or hang the provider indefinitely.
    gemini_timeout_seconds: float = 45.0
    gemini_max_output_tokens: int = 2048
    gemini_max_input_chars: int = 50000
    gemini_max_retries: int = 1

    @property
    def data_root_path(self) -> Path:
        return Path(self.data_root).expanduser() if self.data_root else DATA_ROOT_DEFAULT

    @property
    def m8_model_path(self) -> Path:
        return Path(self.m8_model_dir).expanduser() if self.m8_model_dir else (self.data_root_path / "models" / "m8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auth_configured(self) -> bool:
        return bool(self.auth_secret_key.strip())

    @property
    def auth_db_file(self) -> Path:
        if self.auth_db_path.strip():
            return Path(self.auth_db_path).expanduser()
        return self.data_root_path / "auth" / "auth.db"

    @property
    def auth_issuer_value(self) -> str:
        return self.auth_issuer.strip() or self.app_name

    @property
    def auth_audience_value(self) -> str:
        return self.auth_audience.strip() or "chandrasutra-api"

    @property
    def auth_cookie_secure_effective(self) -> bool:
        return bool(self.auth_cookie_secure) or self.app_env == "production"

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key.strip())

    def public_dict(self) -> dict[str, Any]:
        """Non-secret view of the runtime settings, safe to send to the UI."""
        return {
            "app_name": self.app_name,
            "product_name": self.product_name,
            "tagline": self.tagline,
            "milestone": self.milestone,
            "app_env": self.app_env,
            "app_debug": self.app_debug,
            "demo_mode": self.demo_mode,
            "app_version": self.app_version,
            "cors_origins": self.cors_origin_list,
            "log_level": self.log_level,
            "data_root": str(self.data_root_path),
            "http_max_body_bytes": self.http_max_body_bytes,
            "run_stale_budget_seconds": self.run_stale_budget_seconds,
            "auth": {
                "configured": self.auth_configured,
                "algorithm": self.auth_algorithm,
                "configuration_id": "AU-M10-001",
                "registration_enabled": self.auth_register_enabled,
                "issuer": self.auth_issuer_value,
                "audience": self.auth_audience_value,
                "access_token_ttl_seconds": self.auth_access_ttl_seconds or 900,
                "refresh_cookie_secure": self.auth_cookie_secure_effective,
            },
            "ai": {
                "service": "Gemini",
                "configured": self.gemini_configured,
                "model": self.gemini_model,
                "timeout_seconds": self.gemini_timeout_seconds,
                "max_output_tokens": self.gemini_max_output_tokens,
                "max_input_chars": self.gemini_max_input_chars,
            },
        }


class PipelineConfig(BaseModel):
    """YAML-driven placeholder configuration (configs/app.yaml).

    ``source`` records which file the values came from so that every
    configuration is reproducible. Placeholder thresholds are engineering
    defaults only; they hold no scientific meaning until validated against
    real data (M1+) and registered under a Configuration ID.
    """

    source: str = ""
    pipeline_stages: list[dict[str, str]] = Field(default_factory=list)
    engineering_defaults_placeholder: dict[str, Any] = Field(default_factory=dict)
    m1: dict[str, Any] = Field(default_factory=dict)
    m2: dict[str, Any] = Field(default_factory=dict)
    m3: dict[str, Any] = Field(default_factory=dict)
    m4: dict[str, Any] = Field(default_factory=dict)
    m5: dict[str, Any] = Field(default_factory=dict)
    m6: dict[str, Any] = Field(default_factory=dict)
    m7: dict[str, Any] = Field(default_factory=dict)
    m8: dict[str, Any] = Field(default_factory=dict)
    m9: dict[str, Any] = Field(default_factory=dict)
    m10: dict[str, Any] = Field(default_factory=dict)

    def model_dump_public(self) -> dict[str, Any]:
        data = self.model_dump()
        data["note"] = (
            "Engineering defaults only. No scientifically tuned thresholds "
            "exist yet; they will be introduced with real-data experiments "
            "and Configuration IDs in later milestones."
        )
        return data


def load_pipeline_config(path: Path | None = None) -> PipelineConfig:
    """Load pipeline placeholder configuration from a YAML file.

    Raises AppConfigError if the file is missing or malformed, so the
    startup path can report the exact blocker instead of guessing.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    if not config_path.is_file():
        raise AppConfigError(f"Missing configuration file: {config_path}")

    try:
        with open(config_path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise AppConfigError(f"Could not parse {config_path}: {exc}") from exc

    raw.setdefault("pipeline_stages", [])
    raw.setdefault("engineering_defaults_placeholder", {})
    raw.setdefault("m1", {})
    raw.setdefault("m2", {})
    raw.setdefault("m3", {})
    raw.setdefault("m4", {})
    raw.setdefault("m5", {})
    raw.setdefault("m6", {})
    raw.setdefault("m7", {})
    raw.setdefault("m8", {})
    raw.setdefault("m9", {})
    raw.setdefault("m10", {})
    return PipelineConfig(source=str(config_path), **raw)


_M1_DEFAULTS: dict[str, Any] = {
    "allowed_raw_locations": ["raw/ohrc", "raw/tmc2", "raw/iirs", "raw/lroc"],
    "preview_max_width": 640,
    "preview_dir_rel": "derived/visualizations/previews",
    "preview_png_mode": "L",
    "pairs_json_rel": "metadata/pairs.json",
    "pairs_csv_rel": "metadata/pairs.csv",
    "validation_record_rel": "metadata/pair_validation.json",
    "parser_require_pds4_label": True,
    "unknown_fill": "UNKNOWN",
    "hash_algorithm": "sha256",
}


@lru_cache(maxsize=1)
def m1_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M1 settings from configs/app.yaml.

    Cached per process; falls back to documented defaults when the YAML is
    unavailable so the services stay usable, and never raises on parse.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m1") or {}
        except (OSError, yaml.YAMLError):
            section = {}
    merged = dict(_M1_DEFAULTS)
    merged.update(section or {})
    merged["source"] = str(config_path)
    return merged


@lru_cache(maxsize=1)
def m2_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M2 settings from configs/app.yaml.

    The embedded ``configuration_id`` is the stable M2 Configuration ID.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m2") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "configuration_id": _M2_DEFAULTS["configuration_id"],
        "configuration_version": _M2_DEFAULTS["configuration_version"],
        "name": _M2_DEFAULTS["name"],
        "derived_rel": _M2_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M2_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    return merged


_M2_DEFAULTS: dict[str, Any] = {
    "configuration_id": "PC-M2-001",
    "configuration_version": 1,
    "name": "Trustworthy Preprocessing and Lunar Scene Conditioning",
    "derived_rel": "derived/processing",
    "defaults": {
        "overlap": {"min_overlap_px": 64, "strategy": "footprint_intersection", "require_geometry": True},
        "crops": {
            "size_px": 512, "stride_px": 256,
            "min_tile_width_px": 16, "min_tile_height_px": 16,
            "min_valid_fraction": 0.5,
        },
        "normalization": {
            "display": "percentile_1_99",
            "display_low_percentile": 1.0,
            "display_high_percentile": 99.0,
            "radiometric": "not_applicable",
            "radiometric_reason": "Label carries no radiometric calibration metadata for this product.",
        },
        "masking": {
            "nan_inf": True, "saturated": True, "saturation_dn": 65535,
            "negative": True, "zero_valid": True,
        },
        "orientation": {"source": "record_footprint_or_request", "fallback": "block"},
        "resampling": {
            "applied": False,
            "rationale": (
                "Sensors differ in native GSD. No documented camera model exists in M2 labels, "
                "so no geometric resampling is applied; tiles are sensor-native."
            ),
        },
        "condition": {"texture_low_dn": 8.0, "texture_high_dn": 60.0, "empty_valid_fraction": 0.02},
        "matcher_readiness": {
            "required": [
                "raw_integrity_ok", "preprocess_ok", "overlap_valid",
                "tiles_generated", "tiles_usable", "condition_evaluated",
            ]
        },
        "execution": {"max_runtime_seconds": 300},
    },
}


@lru_cache(maxsize=1)
def m3_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M3 settings from configs/app.yaml.

    Mirrors ``m2_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``configuration_id`` is the stable M3 Matcher
    Configuration ID.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m3") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "configuration_id": _M3_DEFAULTS["configuration_id"],
        "configuration_version": _M3_DEFAULTS["configuration_version"],
        "name": _M3_DEFAULTS["name"],
        "derived_rel": _M3_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M3_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    return merged


_M3_DEFAULTS: dict[str, Any] = {
    "configuration_id": "MC-M3-001",
    "configuration_version": 1,
    "name": "Adaptive Matcher Strategy Selection & Candidate Correspondences",
    "derived_rel": "derived/matches",
    "defaults": {
        "execution": {
            "max_runtime_seconds": 45, "max_features": 4000,
            "max_tile_area_px": 400000, "border_margin_px": 4,
        },
        "minimum_candidates": 8,
        "fallback": {"enabled": True, "max_attempts": 2},
        "sift": {
            "detector": {"nfeatures": 2000, "contrast_threshold": 0.04, "edge_threshold": 10, "sigma": 1.6},
            "matching": {"cross_check": True, "ratio_threshold": 0.8, "max_distance": 350},
        },
        "orb": {
            "detector": {"nfeatures": 2000, "scale_factor": 1.2, "nlevels": 8, "edge_threshold": 31, "fast_threshold": 20},
            "matching": {"cross_check": True, "ratio_threshold": 0.85, "max_distance": 60},
        },
        "routing": {
            "scoring": {
                "classical_local": {
                    "base": 0.5, "texture_normal": 0.25, "texture_high": 0.1,
                    "valid_fraction": 0.2, "scale_gap_small": 0.1,
                    "scale_gap_medium": 0.0, "scale_gap_large": -0.3,
                },
                "robust_local": {
                    "base": 0.5, "texture_low": 0.2, "texture_high": 0.15,
                    "contrast_high": 0.15, "valid_fraction": 0.15,
                    "scale_gap_large": 0.15, "scale_gap_medium": 0.05,
                },
                "deep_optional": {
                    "base": 0.6, "texture_normal": 0.1, "scale_gap_large": 0.1,
                },
            },
            "constraints": {
                "classical_local": {"min_valid_fraction": 0.3},
                "robust_local": {"min_valid_fraction": 0.15},
                "deep_optional": {"requires_availability": True},
            },
        },
    },
}


_M4_DEFAULTS: dict[str, Any] = {
    "trust_configuration_id": "TG-M4-001",
    "trust_configuration_version": 1,
    "name": "Independent Geometric Verification & Trust Gate",
    "derived_rel": "derived/trust",
    "defaults": {
        "candidate_integrity": {"min_usable_candidates": 8},
        "geometric_model": {
            "type": "homography",
            "ransac": {
                "max_iterations": 2000, "inlier_threshold_px": 3.0,
                "confidence": 0.995, "seed": 42,
            },
        },
        "acceptance": {
            "min_inliers": 8, "min_inlier_ratio": 0.3,
            "max_residual_mean": 10.0, "max_residual_median": 6.0, "max_residual_p95": 15.0,
        },
        "spatial": {
            "grid_cells": 4, "min_occupied_cells": 4, "max_concentration_ratio": 0.6,
        },
        "degeneracy": {"min_unique_points": 4, "max_condition_number": 1e6},
        "cross_check": {"enabled": True, "max_symmetric_transfer_px": 8.0},
        "execution": {"max_runtime_seconds": 60},
    },
}


@lru_cache(maxsize=1)
def m4_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M4 settings from configs/app.yaml.

    Mirrors ``m3_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``trust_configuration_id`` is the stable M4 Trust
    Configuration ID.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m4") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "trust_configuration_id": _M4_DEFAULTS["trust_configuration_id"],
        "trust_configuration_version": _M4_DEFAULTS["trust_configuration_version"],
        "name": _M4_DEFAULTS["name"],
        "derived_rel": _M4_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M4_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    return merged


_M5_DEFAULTS: dict[str, Any] = {
    "spatial_reliability_configuration_id": "SR-M5-001",
    "spatial_reliability_configuration_version": 1,
    "name": "Spatial Reliability & Reliability-Aware Selection",
    "derived_rel": "derived/spatial",
    "defaults": {
        "coordinate_space": "pair_overlap_normalized",
        "grid": {"rows": 8, "cols": 8, "edge_tolerance_px": 0.5},
        "reliability": {"min_verified_inliers_per_cell": 4, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "fragmentation": {"enabled": True},
        "boundary": {"edge_policy": "REPORT_ONLY"},
        "connected_components": {"connectivity": 8},
        "selection": {
            "mode": "SUPPORTED_REGION",
            "min_component_cells": 4,
            "min_component_correspondences": 16,
            "min_selected_region_cells": 4,
            "max_selected_correspondences": 4000,
            "deterministic_ordering": "largest_evidence_first",
        },
        "execution": {"max_runtime_seconds": 60},
    },
}


@lru_cache(maxsize=1)
def m5_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M5 settings from configs/app.yaml.

    Mirrors ``m4_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``spatial_reliability_configuration_id`` is the stable M5
    Spatial Reliability Configuration ID.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m5") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "spatial_reliability_configuration_id": _M5_DEFAULTS["spatial_reliability_configuration_id"],
        "spatial_reliability_configuration_version": _M5_DEFAULTS["spatial_reliability_configuration_version"],
        "name": _M5_DEFAULTS["name"],
        "derived_rel": _M5_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M5_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    return merged


_M6_DEFAULTS: dict[str, Any] = {
    "registration_configuration_id": "RG-M6-001",
    "registration_configuration_version": 1,
    "name": "Registration Engine, Verified Alignment & Jury-Ready Registration Workspace",
    "derived_rel": "derived/registration",
    "defaults": {
        "transform": {
            "preferred_type": "homography",
            "affine_fallback": True,
            "min_inliers_for_homography": 4,
            "min_inlier_ratio_for_homography": 0.5,
            "ransac_max_iterations": 2000,
            "ransac_inlier_threshold_px": 3.0,
            "ransac_seed": 42,
            "refine": False,
        },
        "validation": {
            "max_symmetric_transfer_px": 12.0,
            "max_residual_mean_px": 10.0,
            "max_residual_median_px": 6.0,
            "max_residual_p95_px": 15.0,
            "min_inlier_ratio": 0.3,
            "min_inliers": 6,
            "max_condition_number": 1e6,
            "check_determinant": True,
            "min_abs_determinant": 1e-6,
        },
        "warp": {
            "method": "forward_mapping",
            "output_bounds": "target_bounds",
            "fill_value": 0,
            "dtype": "uint16",
            "output_interpolation": "linear",
            "output_image_format": "png",
            "visualization_normalization": "minmax",
            "max_output_rows": 20000,
            "max_output_cols": 20000,
        },
        "execution": {"max_runtime_seconds": 120},
    },
}


@lru_cache(maxsize=1)
def m6_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M6 settings from configs/app.yaml.

    Mirrors ``m5_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``registration_configuration_id`` is the stable M6
    Registration Configuration ID.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m6") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "registration_configuration_id": _M6_DEFAULTS["registration_configuration_id"],
        "registration_configuration_version": _M6_DEFAULTS["registration_configuration_version"],
        "name": _M6_DEFAULTS["name"],
        "derived_rel": _M6_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M6_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    return merged


_M7_DEFAULTS: dict[str, Any] = {
    "metrics_configuration_id": "MT-M7-001",
    "metrics_configuration_version": 1,
    "name": "Quantitative Metrics, Reproducible Experiment Reports & Scientific Diagnostics",
    "derived_rel": "derived/metrics",
    "defaults": {
        "rejected": {
            "inlier_ratio_minimum": 0.3,
            "residual_mean_max_px": 10.0,
            "selected_fraction_minimum": 0.1,
            "scientifically_tuned": False,
        },
        "recompute": {
            "enabled": True,
            "inlier_threshold_px": 3.0,
            "consistency_tolerance": 1e-3,
            "scientifically_tuned": False,
        },
        "report": {
            "deterministic_report": True,
        },
        "execution": {"max_runtime_seconds": 60},
    },
}


@lru_cache(maxsize=1)
def m7_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M7 settings from configs/app.yaml.

    Mirrors ``m6_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``metrics_configuration_id`` is the stable M7 Metrics
    Configuration ID. All thresholds carry ``scientifically_tuned: false``.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m7") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "metrics_configuration_id": _M7_DEFAULTS["metrics_configuration_id"],
        "metrics_configuration_version": _M7_DEFAULTS["metrics_configuration_version"],
        "name": _M7_DEFAULTS["name"],
        "derived_rel": _M7_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M7_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
    return merged


_M8_DEFAULTS: dict[str, Any] = {
    "configuration_id": "DM-M8-001",
    "configuration_version": 1,
    "name": "Deep Matcher Benchmarking, Adaptive Expansion & Trustworthy Matcher Selection",
    "source_reference": "SIH26166 M8 spec - engineering defaults; no scientifically tuned thresholds.",
    "derived_rel": "derived/matches",
    "scientifically_tuned": False,
    "defaults": {
        "enabled": True,
        "preferred_matcher": "auto",
        "classical": {
            "enabled": True,
            "strategies": ["sift", "orb"],
        },
        "deep": {
            "enabled": True,
            "strategies": ["superpoint_superglue", "loftr"],
        },
        "runtime": {
            "device": "auto",
            "max_runtime_seconds": 120,
            "max_image_dimension": 2048,
            "max_tile_area": 400000,
            "batch_size": 1,
        },
        "candidates": {
            "max_correspondences": 4000,
            "require_finite": True,
            "require_mask_valid": True,
        },
        "routing": {
            "allow_classical": True,
            "allow_deep": True,
            "fallback_to_classical": True,
        },
        "benchmark": {
            "enabled": True,
            "reference_dataset": "NOT_AVAILABLE",
        },
    },
}


@lru_cache(maxsize=1)
def m8_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M8 settings from configs/app.yaml.

    Mirrors ``m7_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``configuration_id`` is the stable M8 Deep Matcher
    Configuration ID.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m8") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "configuration_id": _M8_DEFAULTS["configuration_id"],
        "configuration_version": _M8_DEFAULTS["configuration_version"],
        "name": _M8_DEFAULTS["name"],
        "derived_rel": _M8_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M8_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
    return merged


_M9_DEFAULTS: dict[str, Any] = {
    "ai_configuration_id": "AI-M9-001",
    "ai_configuration_version": 1,
    "name": "Real Gemini AI Assistant — Evidence-Grounded Scientific Copilot & Explainable Analysis",
    "source_reference": "SIH26166 M9 spec - engineering defaults; no scientifically tuned thresholds.",
    "provider": "gemini",
    "prompt_version": "M9-SYSTEM-001",
    "evidence_schema_version": "M9-EVIDENCE-001",
    "delimiters": {"begin": "BEGIN CHANDRASUTRA EVIDENCE", "end": "END CHANDRASUTRA EVIDENCE"},
    "forbidden_result_terms": [
        "overall_accuracy", "scientific_confidence", "registration_confidence",
        "alignment_score", "lunar_accuracy", "geolocation_accuracy", "CE90", "LE90",
    ],
    "grounding_rules": {
        "R1": "Claims must come only from the supplied evidence packet.",
        "R2": "When reference (physical-truth) data is NOT_AVAILABLE, reference accuracy is never reported and never guessed.",
        "R3": "A BLOCKED stage is described as blocked; it is never described as completed or estimated.",
        "R4": "A metric absent from the evidence packet is 'not available'; it is never invented or estimated.",
        "R5": "Matcher confidence or matcher scores are observations, never scientific confidence.",
        "R6": "Residuals are quantitative diagnostics, not physical lunar accuracy.",
        "R7": "The M4 Trust Gate verdict is never overridden or reclassified.",
        "R8": "An unexplained cause must be reported as 'Cause is not established by the recorded evidence.'",
    },
    "constraints": {
        "max_input_chars": 50000,
        "max_output_tokens": 2048,
        "timeout_seconds": 45.0,
        "rate_limit_per_minute": 30,
        "max_sessions": 200,
        "session_ttl_seconds": 3600,
        "evidence_digest_algorithm": "sha256",
        "store_prompts": False,
        "store_responses": False,
    },
}


@lru_cache(maxsize=1)
def m9_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M9 settings from configs/app.yaml.

    Mirrors ``m8_config``: cached per process, falls back to documented
    defaults, and never raises on parse. ``prompt_version`` and
    ``evidence_schema_version`` are the stable identities used in audit
    records and M9 provenance.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m9") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged = dict(_M9_DEFAULTS)
    merged.update(section or {})
    merged["source"] = str(config_path)
    return merged


_M10_DEFAULTS: dict[str, Any] = {
    "authentication_configuration_id": "AU-M10-001",
    "authentication_configuration_version": 1,
    "name": "Full Authentication, Authorization & User Security",
    "source_reference": "SIH26166 M10 spec — engineering defaults; no enterprise IAM claims.",
    "access_token_ttl_seconds": 900,
    "refresh_token_ttl_seconds": 604800,
    "session_idle_ttl_seconds": 86400,
    "password_policy": {
        "min_length": 12,
        "require_letter": True,
        "require_digit": True,
        "disallow_username": True,
    },
    "login_rate_limit": {
        "max_attempts": 5,
        "window_seconds": 300,
        "lockout_seconds": 900,
    },
    "refresh_rotation": True,
    "registration_enabled": True,
    "policy": {
        "no_plaintext_passwords": True,
        "passwords_never_in_logs": True,
        "passwords_never_in_responses": True,
        "passwords_never_in_audit": True,
        "secret_from_environment_only": True,
        "authorization_server_side_only": True,
        "no_fake_login": True,
        "protected_routes_enforced": True,
    },
    "roles": {
        "viewer": "read results, datasets, and use explanatory AI",
        "analyst": "execute permitted processing and analysis workflows",
        "admin": "manage users, roles, security audit and administrative config",
    },
}


@lru_cache(maxsize=1)
def m10_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M10 settings from configs/app.yaml.

    Mirrors ``m9_config``: cached per process, falls back to documented
    defaults, and never raises on parse. Exposed via ``GET /api/auth/status``
    and ``GET /api/meta`` as ``m10_config``.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m10") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged = dict(_M10_DEFAULTS)
    merged.update(section or {})
    merged["source"] = str(config_path)
    return merged


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge nested dicts (overlay wins; no type coercion)."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def rfc3339_now() -> str:
    """Small helper producing a UTC timestamp string (no external deps)."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class AppConfigError(Exception):
    """Raised when application configuration cannot be loaded."""


def validate_runtime_config(settings: "Settings") -> None:
    """Fail fast on unsafe runtime configurations.

    M11 environment separation: ``production`` and ``demo`` must never run
    with debug behaviour, permissive CORS, or insecure auth cookies enabled.
    ``development``/``test`` keep full flexibility. Raises ``AppConfigError``
    with an explicit, non-secret reason so deployment mistakes are loud.
    """
    if settings.app_env not in ("production", "demo"):
        return
    problems: list[str] = []
    if settings.app_debug:
        problems.append("APP_DEBUG must be false (debug responses are disabled here)")
    if any(origin == "*" for origin in settings.cors_origin_list):
        problems.append("CORS_ORIGINS must not contain '*' (permissive cross-origin is disabled)")
    if settings.log_level and settings.log_level.strip().upper() == "DEBUG":
        problems.append("LOG_LEVEL must not be DEBUG in this environment")
    if settings.auth_cookie_secure is False and settings.app_env == "production":
        problems.append("AUTH_COOKIE_SECURE cannot be forced off in production")
    if problems:
        raise AppConfigError(
            "Unsafe runtime configuration for environment '%s': %s"
            % (settings.app_env, "; ".join(problems))
        )


# ---- Pydantic JSON serialization helpers --------------------------------

def to_jsonable(value: Any) -> Any:
    """Recursively convert non-JSON values (paths, sets, bytes, dataclasses) to JSON-safe."""
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(dataclasses.asdict(value))
    if isinstance(value, (set, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump())
    return value


def env_value_as_json(value: str) -> Any:
    """Parse a JSON-ish env value, e.g. CORS_ORIGINS='["a","b"]'."""
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value