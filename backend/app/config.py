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
    m3_baseline: dict[str, Any] = Field(default_factory=dict)
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
    raw.setdefault("m3_baseline", {})
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


@lru_cache(maxsize=1)
def m3_baseline_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M3 BASELINE settings from configs/app.yaml.

    Mirrors ``m3_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
    The embedded ``configuration_id`` is the stable M3 Baseline Matcher
    Configuration ID (MB-M3-001).
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m3_baseline") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "configuration_id": _M3B_DEFAULTS["configuration_id"],
        "configuration_version": _M3B_DEFAULTS["configuration_version"],
        "name": _M3B_DEFAULTS["name"],
        "derived_rel": _M3B_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M3B_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    return merged


_M3B_DEFAULTS: dict[str, Any] = {
    "configuration_id": "MB-M3-001",
    "configuration_version": 1,
    "name": "Classical Baseline Matcher — Candidate Correspondences (SIFT · AKAZE · ORB)",
    "derived_rel": "metadata/m3_matching",
    "defaults": {
        "execution": {
            "max_runtime_seconds": 60,
            "max_image_dimension": 2048,
            "max_features": 4000,
            "border_margin_px": 0,
        },
        "visualization": {
            "enabled": True,
            "max_lines": 120,
            "max_side_px": 960,
        },
        "sift": {
            "detector": {
                "nfeatures": 2000, "n_octave_layers": 3,
                "contrast_threshold": 0.04, "edge_threshold": 10, "sigma": 1.6,
            },
            "matching": {"cross_check": True, "ratio_threshold": 0.8, "max_distance": 350},
        },
        "akaze": {
            "detector": {
                "descriptor": "MLDB", "descriptor_size": 0, "descriptor_channels": 3,
                "threshold": 0.001, "n_octaves": 4, "n_octave_layers": 4,
                "diffusivity": "PM_G2",
            },
            "matching": {"cross_check": True, "ratio_threshold": 0.8, "max_distance": 100},
        },
        "orb": {
            "detector": {
                "nfeatures": 2000, "scale_factor": 1.2, "nlevels": 8,
                "edge_threshold": 31, "fast_threshold": 20,
            },
            "matching": {"cross_check": True, "ratio_threshold": 0.85, "max_distance": 60},
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


_M5C_DEFAULTS: dict[str, Any] = {
    "configuration_id": "CE-M5-001",
    "configuration_version": 1,
    "name": "Condition Estimator — Pair-Level Condition & Difficulty Characterization (Pre-Matcher-Selection Layer)",
    "source_reference": "SIH26166 M5 spec — engineering defaults; no scientifically tuned thresholds. Evaluated before any matcher selection; this layer never selects, recommends or routes a matcher.",
    "derived_rel": "metadata/m5_condition",
    "scientifically_tuned": False,
    "defaults": {
        "execution": {"max_runtime_seconds": 120},
        "sampling": {
            "window_size_px": 256, "stride_px": 128,
            "seed": 20260922, "max_windows": 1024,
            "require_full_windows": False,
        },
        "texture": {
            "sobel_kernel_size_px": 3,
            "canny": {
                "enabled": True, "min_threshold": 50, "max_threshold": 150,
                "aperture_size_px": 3, "l2gradient": False,
            },
            "laplacian_kernel_size_px": 3,
        },
        "appearance": {
            "histogram_bins": 256,
            "robust_percentiles": [5, 50, 95],
            "normalise": "l1",
            "constant_std_dn_tolerance": 1.0,
            "constant_range_dn_tolerance": 4.0,
        },
        "invalid_mask": {"enabled": True},
        "saturation": {"enabled": True},
        "histogram_distance": {"enabled": True, "metric": "chi_square"},
        "scale": {
            "native_dimensions": True,
            "effective_processing_dimensions": True,
            "gsd": {
                "enabled": True,
                "source_order": ["RECORDED_GEOMETRY", "PDS4_LABEL", "NOMINAL_SENSOR"],
                "fallback": "UNKNOWN",
            },
        },
        "matcher_observations": {
            "enabled": True,
            "latest_baseline": True,
            "baseline_configuration": "MB-M3-001",
        },
        "data_gate": {"require_real": False},
        "classification": {
            "scientifically_tuned": False,
            "note": "Engineering-level ordinal bins (LOW/MEDIUM/HIGH) with explicit thresholds recorded in every artifact. Reproducible labels for engineering use only — never a scientific quality verdict and never an input to matcher selection in this layer.",
            "textural_complexity": {
                "enabled": True, "metric": "laplacian_variance",
                "low_lt": 25.0, "high_ge": 150.0,
            },
            "dynamic_range": {
                "enabled": True, "metric": "p95_minus_p5_dn",
                "low_lt": 40.0, "high_ge": 300.0,
            },
            "invalid_fraction": {
                "enabled": True, "low_lt": 0.05, "high_ge": 0.30,
            },
        },
    },
}


@lru_cache(maxsize=1)
def m5_condition_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M5 CONDITION ESTIMATOR settings.

    Mirrors ``m4_deep_config``/``m5_config``: cached per process, falls back
    to documented defaults when the YAML is unavailable, and never raises on
    parse. The embedded ``configuration_id`` is the stable Condition
    Estimator Configuration ID (CE-M5-001), distinct from the M5 spatial
    reliability configuration (SR-M5-001).
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m5_condition") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged: dict[str, Any] = {
        "configuration_id": _M5C_DEFAULTS["configuration_id"],
        "configuration_version": _M5C_DEFAULTS["configuration_version"],
        "name": _M5C_DEFAULTS["name"],
        "derived_rel": _M5C_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M5C_DEFAULTS["defaults"], section.get("defaults") or {}),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
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


_M6R_DEFAULTS: dict[str, Any] = {
    "configuration_id": "AR-M6-001",
    "configuration_version": 1,
    "name": "Adaptive Matcher Router — Deterministic, Evidence-based Matcher Selection",
    "source_reference": "SIH26166 M6 spec - deterministic rule-driven routing over M5 condition facts; engineering/policy defaults (scientifically_tuned: false); never a scientific accuracy claim.",
    "derived_rel": "metadata/m6_routing",
    "scientifically_tuned": False,
    "defaults": {
        "modes": ["ADAPTIVE", "FIXED_BASELINE"],
        "default_mode": "ADAPTIVE",
        "forbidden_vocabulary": [
            "selected_matcher", "recommended_matcher", "best_matcher",
            "routing_decision", "confidence",
        ],
        "execution": {"max_runtime_seconds": 60, "max_fallback_attempts": 1},
        "fallback": {
            "resolved_by": "capability",
            "primary_unavailable_action": "USE_CONFIGURED_FALLBACK",
            "empty_candidate_output_action": "USE_CONFIGURED_FALLBACK",
            "failed_run_action": "USE_CONFIGURED_FALLBACK",
        },
        "policy": {
            "appearance": {"difference_low_lt": 0.25, "difference_high_ge": 0.55},
            "scale": {"gsd_ratio_medium_ge": 1.35, "gsd_ratio_large_ge": 2.0},
        },
        "matchers": {
            "classical": {"sift": True, "orb": True, "akaze": True},
            "deep": {"superpoint_superglue": True, "loftr": True},
        },
        "rules": [
            {
                "id": "R-PRE-A", "priority": 100,
                "modes": ["ADAPTIVE", "FIXED_BASELINE"], "match": "all",
                "when": [{"field": "processing_ready", "operator": "equals", "value": False}],
                "action": "BLOCKED", "error_code": "PROCESSING_NOT_RUN",
                "explanation": "M2 validated products are not READY_FOR_MATCHING; routing cannot consume non-existent validated products.",
            },
            {
                "id": "R-PRE-B", "priority": 90,
                "modes": ["ADAPTIVE"], "match": "all",
                "when": [{"field": "condition_profile_available", "operator": "equals", "value": False}],
                "action": "BLOCKED", "error_code": "CONDITION_NOT_AVAILABLE",
                "explanation": "ADAPTIVE routing requires a SUCCESS M5 condition profile; the decision is blocked until one exists.",
            },
            {
                "id": "R-FX-001", "priority": 70,
                "modes": ["FIXED_BASELINE"], "match": "all",
                "when": [],
                "action": "ROUTED", "primary_matcher": "sift", "fallback_matcher": "orb",
                "explanation": "Fixed-baseline ablation arm: the matcher route is predetermined and condition facts are intentionally not inspected.",
            },
            {
                "id": "R-DEEP-001", "priority": 50,
                "modes": ["ADAPTIVE"], "match": "any",
                "when": [
                    {"field": "pair.texture_complexity_high", "operator": "equals", "value": True},
                    {"field": "pair.appearance_difference_high", "operator": "equals", "value": True},
                    {"field": "pair.gsd_ratio_large", "operator": "equals", "value": True},
                ],
                "action": "ROUTED", "primary_matcher": "superpoint_superglue", "fallback_matcher": "sift",
                "explanation": "High textural complexity, large appearance difference or a large recorded scale gap -> strong deep matcher with a classical fallback.",
            },
            {
                "id": "R-CLASS-001", "priority": 40,
                "modes": ["ADAPTIVE"], "match": "all",
                "when": [
                    {"field": "pair.texture_complexity_low", "operator": "equals", "value": True},
                    {"field": "pair.appearance_difference_low", "operator": "equals", "value": True},
                    {"field": "pair.gsd_ratio_large", "operator": "equals", "value": False},
                ],
                "action": "ROUTED", "primary_matcher": "sift", "fallback_matcher": "orb",
                "explanation": "Low textural complexity, low appearance difference and no large recorded scale gap -> classical baseline route.",
            },
            {
                "id": "R-DFT-001", "priority": 10,
                "modes": ["ADAPTIVE"], "match": "all",
                "when": [],
                "action": "ROUTED", "primary_matcher": "sift", "fallback_matcher": "orb",
                "explanation": "Deterministic default route when no more specific rule matches.",
            },
        ],
        "route_reasons": {
            "primary_unavailable": "PRIMARY_MATCHER_UNAVAILABLE",
            "empty_candidate_output": "EMPTY_CANDIDATE_OUTPUT",
            "failed_run": "FAILED_RUN",
            "no_available_matcher": "NO_AVAILABLE_MATCHER",
        },
    },
}


@lru_cache(maxsize=1)
def m6_routing_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M6 ADAPTIVE ROUTER settings.

    Mirrors ``m5_condition_config``: cached per process, falls back to the
    documented ``_M6R_DEFAULTS`` when the YAML is unavailable, and never
    raises on parse. The embedded ``configuration_id`` is the stable M6
    Adaptive Router Configuration ID (AR-M6-001).
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m6_routing") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged: dict[str, Any] = {
        "configuration_id": _M6R_DEFAULTS["configuration_id"],
        "configuration_version": _M6R_DEFAULTS["configuration_version"],
        "name": _M6R_DEFAULTS["name"],
        "source_reference": _M6R_DEFAULTS["source_reference"],
        "derived_rel": _M6R_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M6R_DEFAULTS["defaults"], section.get("defaults") or {}),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
    return merged


_M7T_DEFAULTS: dict[str, Any] = {
    "configuration_id": "TG-M7-001",
    "configuration_version": 1,
    "name": "Trust Gate — Geometric Verification of Candidate Correspondences",
    "source_reference": (
        "SIH26166 M7 spec - conservative, reproducible, auditable gate over M3/M4/M6 "
        "matcher run candidate correspondences; engineering defaults "
        "(scientifically_tuned: false); never a physical-accuracy or registration claim."
    ),
    "derived_rel": "metadata/m7_trust",
    "scientifically_tuned": False,
    "defaults": {
        "decision": {
            "zero_candidates": "ABSTAIN",
            "min_candidates": 8,
            "min_inliers": 8,
            "min_inlier_ratio": 0.30,
            "max_residual_rmse_px": 8.0,
            "max_residual_median_px": 5.0,
            "max_residual_p95_px": 12.0,
            "max_runtime_seconds": 60,
            "scientifically_tuned": False,
        },
        "geometry": {
            "models": ["affine", "homography"],
            "preferred_model": "affine",
            "attempt_hierarchy": True,
            "ransac": {
                "max_iterations": 2000,
                "inlier_threshold_px": 4.0,
                "confidence_parameter": 0.99,
                "seed": 20260923,
            },
        },
        "degeneracy": {
            "min_unique_points": 6,
            "max_condition_number": 1e6,
        },
        "spatial_sanity": {
            "min_extent_px": 5.0,
            "strip_ratio_warn": 0.02,
        },
        "duplicates": {
            "policy": "keep_first_record_counts",
        },
        "resource": {
            "max_candidates": 500000,
        },
        "reference_status": "REFERENCE_UNAVAILABLE",
        "forbidden_vocabulary": [
            "confidence",
            "final_confidence",
            "best",
            "winner",
            "superior",
        ],
    },
}


@lru_cache(maxsize=1)
def m7_trust_gate_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M7 TRUST GATE settings from configs/app.yaml.

    Mirrors ``m6_routing_config``: cached per process, falls back to the
    documented ``_M7T_DEFAULTS`` when the YAML is unavailable, and never
    raises on parse. The embedded ``configuration_id`` is the stable M7
    Trust Gate Configuration ID (TG-M7-001). Every threshold carries
    ``scientifically_tuned: false``.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m7_trust_gate") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged: dict[str, Any] = {
        "configuration_id": _M7T_DEFAULTS["configuration_id"],
        "configuration_version": _M7T_DEFAULTS["configuration_version"],
        "name": _M7T_DEFAULTS["name"],
        "source_reference": _M7T_DEFAULTS["source_reference"],
        "derived_rel": _M7T_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M7T_DEFAULTS["defaults"], section.get("defaults") or {}),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
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


_M8S_DEFAULTS: dict[str, Any] = {
    "configuration_id": "SR-M8-001",
    "configuration_version": 1,
    "name": "Spatial Reliability & Balanced Correspondence Selection",
    "source_reference": (
        "SIH26166 M8 spec — deterministic spatial bookkeeping over ACCEPTED M7 "
        "trusted correspondences; engineering defaults (scientifically_tuned: false); "
        "never an accuracy, probability or registration claim and never an override "
        "of the M7 verdict."
    ),
    "derived_rel": "metadata/m8_spatial",
    "scientifically_tuned": False,
    "defaults": {
        "grid": {"rows": 8, "cols": 8, "edge_policy": "REPORT_ONLY"},
        "selection": {
            "policy": "GRID_BALANCED",
            "max_selected": 4000,
            "min_trusted": 4,
            "min_selected": 1,
            "min_per_occupied_cell": 1,
            "min_occupied_cells": 4,
            "tie_break": "residual_then_original_index",
            "limit_applied_warning": True,
        },
        "coverage": {
            "low_coverage_ratio": 0.25,
            "concentration_ratio": 0.60,
        },
        "execution": {"max_runtime_seconds": 60},
        "reference_status": "REFERENCE_UNAVAILABLE",
        "forbidden_vocabulary": [
            "confidence",
            "final_confidence",
            "best",
            "winner",
            "superior",
        ],
    },
}


@lru_cache(maxsize=1)
def m8_spatial_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M8 SPATIAL SELECTION settings.

    Mirrors ``m7_trust_gate_config``: cached per process, falls back to the
    documented ``_M8S_DEFAULTS`` when the YAML is unavailable, and never
    raises on parse. The embedded ``configuration_id`` is the stable M8
    Spatial Selection Configuration ID (SR-M8-001) — distinct from the M5
    spatial reliability configuration (SR-M5-001) and the deep matcher
    configuration (DM-M8-001).
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m8_spatial") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged: dict[str, Any] = {
        "configuration_id": _M8S_DEFAULTS["configuration_id"],
        "configuration_version": _M8S_DEFAULTS["configuration_version"],
        "name": _M8S_DEFAULTS["name"],
        "source_reference": _M8S_DEFAULTS["source_reference"],
        "derived_rel": _M8S_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M8S_DEFAULTS["defaults"], section.get("defaults") or {}),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
    return merged


_M9R_DEFAULTS: dict[str, Any] = {
    "configuration_id": "RG-M9-001",
    "configuration_version": 1,
    "name": "Registration & Image Alignment — smallest-valid declared transform over M8-selected correspondences",
    "source_reference": (
        "SIH26166 M9 spec — engineering defaults; no scientifically calibrated lunar "
        "thresholds; never a physical accuracy or geolocation claim."
    ),
    "derived_rel": "metadata/m9_registration",
    "scientifically_tuned": False,
    "defaults": {
        "model": {
            "preference": "smallest_valid",
            "min_points_affine": 4,
            "min_points_homography": 5,
            "normalized_dlt": True,
        },
        "validation": {
            "max_rmse_px": 3.0,
            "max_p95_px": 5.0,
            "max_residual_max_px": 10.0,
            "max_transform_condition": 1e6,
            "min_abs_determinant": 1e-4,
            "max_abs_coefficient": 1e4,
            "min_homography_denominator": 1e-6,
            "max_scale_change": 20.0,
            "min_scale_factor": 1e-3,
        },
        "warp": {
            "interpolation": "linear",
            "border_mode": "constant",
            "fill_value": 0,
            "dtype": "uint16",
            "output_dimensions": "target_b_frame",
            "max_output_rows": 32768,
            "max_output_cols": 32768,
        },
        "execution": {"max_runtime_seconds": 120},
        "reference_status": "REFERENCE_UNAVAILABLE",
        "forbidden_vocabulary": [
            "confidence",
            "final_confidence",
            "best",
            "winner",
            "superior",
            "perfect",
            "accurate",
        ],
    },
}


@lru_cache(maxsize=1)
def m9_registration_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M9 Registration/Alignment settings.

    Mirrors ``m8_spatial_config``: cached per process, falls back to the
    documented ``_M9R_DEFAULTS`` when the YAML is unavailable, and never
    raises on parse. The embedded ``configuration_id`` is the stable M9
    Registration Configuration ID (RG-M9-001), distinct from the legacy
    M6 registration (RG-M6-001) and the Gemini ``m9`` AI settings (AI-M9-001).
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m9_registration") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged: dict[str, Any] = {
        "configuration_id": _M9R_DEFAULTS["configuration_id"],
        "configuration_version": _M9R_DEFAULTS["configuration_version"],
        "name": _M9R_DEFAULTS["name"],
        "source_reference": _M9R_DEFAULTS["source_reference"],
        "derived_rel": _M9R_DEFAULTS["derived_rel"],
        "defaults": _deep_merge(_M9R_DEFAULTS["defaults"], section.get("defaults") or {}),
    }
    merged.update({k: v for k, v in section.items() if k != "defaults"})
    merged["source"] = str(config_path)
    merged["scientifically_tuned"] = bool(merged.get("scientifically_tuned", False))
    return merged


_M4D_DEFAULTS: dict[str, Any] = {
    "configuration_id": "DM-M4-001",
    "configuration_version": 1,
    "name": "Strong Deep Matcher — SuperPoint + SuperGlue Candidate Correspondences",
    "source_reference": (
        "SIH26166 M4 spec; SuperPoint (Detone et al., NeurIPS 2018) + SuperGlue "
        "(Sarlin et al., CVPR 2020) reference graphs with official pretrained "
        "checkpoints; engineering defaults; no scientifically tuned thresholds."
    ),
    "derived_rel": "metadata/m4_deep_matching",
    "checkpoints": {
        "superpoint": {
            "filename": "superpoint_v1.pth",
            "source_url": "https://github.com/magicleap/SuperGluePretrainedNetwork/models/weights/superpoint_v1.pth",
            "sha256": "52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e",
        },
        "superglue": {
            "filename": "superglue_outdoor.pth",
            "source_url": "https://github.com/magicleap/SuperGluePretrainedNetwork/models/weights/superglue_outdoor.pth",
            "sha256": "2f5f5e9bb3febf07b69df633c4c3ff7a17f8af26a023aae2b9303d22339195bd",
        },
    },
    "defaults": {
        "execution": {
            "max_runtime_seconds": 180,
            "max_image_dimension": 1024,
            "max_keypoints": 2048,
            "nms_radius": 4,
            "device": "cpu",
            "torch_threads": 8,
        },
        "superglue": {
            "sinkhorn_iterations": 100,
            "match_threshold": 0.2,
            "gnn_layers_self_cross_pairs": 9,
        },
        "visualization": {
            "enabled": True,
            "max_lines": 120,
            "max_side_px": 960,
        },
    },
}


@lru_cache(maxsize=1)
def m4_deep_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M4-DEEP settings from configs/app.yaml.

    Mirrors ``m8_config``: cached per process, falls back to documented
    defaults, and never raises on parse. The embedded ``configuration_id``
    is the stable Deep Matcher Configuration ID (DM-M4-001). The
    ``checkpoints`` block records the manual provisioning source + pinned
    SHA-256 for the official SuperPoint/SuperGlue weights; the service
    verifies files against these pins and never auto-downloads.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m4_deep") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    defaults = section.get("defaults") or {}
    merged: dict[str, Any] = {
        "configuration_id": _M4D_DEFAULTS["configuration_id"],
        "configuration_version": _M4D_DEFAULTS["configuration_version"],
        "name": _M4D_DEFAULTS["name"],
        "derived_rel": _M4D_DEFAULTS["derived_rel"],
        "checkpoints": _deep_merge(_M4D_DEFAULTS["checkpoints"], section.get("checkpoints") or {}),
        "defaults": _deep_merge(_M4D_DEFAULTS["defaults"], defaults),
    }
    merged.update({k: v for k, v in section.items() if k not in ("defaults", "checkpoints")})
    merged["source"] = str(config_path)
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


# ============================================================================
# M10-M-odes — Metrics & Benchmark / Ablation / Failure Analysis
# ----------------------------------------------------------------------------
# Configuration id MET-M10-001 (distinct from the authentication milestone
# ``m10_config``/AU-M10-001). Engineering-only engineering defaults; every
# knob registers as ``scientifically_tuned: false``. The benchmark never
# declares a best/ superior/trusted/accuracy verdict and never fabricates
# a reference when real PRADAN data is unavailable.
_M10O_DEFAULTS: dict[str, Any] = {
    "m10_metrics_configuration_id": "MET-M10-001",
    "m10_metrics_configuration_version": 1,
    "metric_definition_version": "MET-M10D-001",
    "failure_taxonomy_version": "FT-M10-001",
    "name": "M10 Metrics, Benchmark, Ablation & Failure Analysis controller",
    "source_reference": "SIH26166 M10 spec — engineering defaults; no scientific calibration.",
    "derived_rel": "metadata/m10_metrics",
    "scientifically_tuned": False,
    "reference_status": {
        "value": "REFERENCE_UNAVAILABLE",
        "note": "No real OHRC/TMC-2 PRADAN products provisioned; benchmark is "
                "BLOCKED_PENDING_OPERATOR_DATA until they exist.",
    },
    "variants": {
        "version": 1,
        "ids": [
            {"id": "V1", "name": "FIXED_CLASSICAL_BASELINE",
             "routing": "FIXED_CLASSICAL", "trust_gate": "ENABLED",
             "spatial_selection": "ENABLED", "pipeline_variant": "FIXED_CLASSICAL"},
            {"id": "V2", "name": "FIXED_ALTERNATE_CLASSICAL",
             "routing": "FIXED_ALTERNATE_CLASSICAL", "trust_gate": "ENABLED",
             "spatial_selection": "ENABLED", "pipeline_variant": "FIXED_ALTERNATE_CLASSICAL"},
            {"id": "V3", "name": "FIXED_DEEP",
             "routing": "FIXED_DEEP", "trust_gate": "ENABLED",
             "spatial_selection": "ENABLED", "pipeline_variant": "FIXED_DEEP"},
            {"id": "V4", "name": "ROUTED_FULL_ADAPTIVE_RELIABILITY",
             "routing": "ROUTED", "trust_gate": "ENABLED",
             "spatial_selection": "ENABLED", "pipeline_variant": "FULL_ADAPTIVE_RELIABILITY"},
            {"id": "V5", "name": "TRUST_DISABLED_ABLATION",
             "routing": "ROUTED", "trust_gate": "DISABLED_FOR_ABLATION",
             "spatial_selection": "ENABLED", "pipeline_variant": "FULL_ADAPTIVE_RELIABILITY"},
            {"id": "V6", "name": "SPATIAL_DISABLED_ABLATION",
             "routing": "ROUTED", "trust_gate": "ENABLED",
             "spatial_selection": "DISABLED_FOR_ABLATION", "pipeline_variant": "FULL_ADAPTIVE_RELIABILITY"},
        ],
    },
    "funnel": {
        "stage_order": [
            "input_gate", "processing", "matching", "trust_gate", "spatial_selection",
            "registration",
        ],
        "stage_labels": {
            "input_gate": "M1 pair registration + data source gate",
            "processing": "M2 product processing (PREPARE)",
            "matching": "M3/M4 candidate correspondence generation",
            "trust_gate": "M7 trust gate (verified/trusted evidence)",
            "spatial_selection": "M8 spatial selection",
            "registration": "M9 registration / transform estimation",
        },
    },
    "aggregation": {
        "metrics": ["candidate_count", "verified_count", "inlier_count", "selected_count",
                    "registration_rmse_px", "registration_p95_px", "runtime_ms"],
        "operators": ["count", "sum", "mean", "median", "p90", "p95", "min", "max"],
        "report_vocabulary": {
            "norths": ["candidate_count", "registered_count", "verified_count"],
            "smaller_is_better_note": "Smaller residuals are reported as smaller; "
                                      "no lower-is-better verdict is applied.",
            "never_winner": True,
            "forbidden_vocabulary": [
                "winner", "best", "superior", "optimal", "accuracy", "success_rate",
                "perfect", "outperformed", "superp ''", "geolocation_accuracy", "CE90",
                "LE90", "confidence",
            ],
        },
    },
    "failure_taxonomy": {
        "version": "FT-M10-001",
        "root": "REGISTRATION_FAILURE",
        "branches": {
            "failed": ["TRANSFORM_FIT_ERROR", "VALUES_NOT_FINITE", "SPATIAL_NOT_AVAILABLE",
                       "TRUST_NOT_AVAILABLE", "MATCH_RUN_NOT_AVAILABLE"],
            "abstain": ["SPARSE_EVIDENCE", "MARGINAL_EVIDENCE", "BUDGET_EXCEEDED"],
            "failed_vs_abstain_policy": ("A failed run never abstains and an abstaining "
                                         "run never fails; a blocked run is never "
                                         "recorded as an outcome."),
        },
    },
    "runtime_limits": {
        "max_runtime_seconds": 120,
        "max_variants_per_run": 6,
    },
    "visualization": {"enabled": True, "max_series": 6, "max_bars": 20},
}


@lru_cache(maxsize=1)
def m10_metrics_config(path: Path | None = None) -> dict[str, Any]:
    """Engineering (non-scientific) M10 metrics/benchmark settings.

    Reads the ``m10_metrics:`` block of ``configs/app.yaml``, merges over
    ``_M10O_DEFAULTS``, and is cached per process. It is intentionally
    separate from ``m10_config()`` (the M10 authentication milestone,
    ``AU-M10-001``) so the two milestone sections never collide.
    """
    config_path = path or CONFIG_FILE_DEFAULT
    section: dict[str, Any] = {}
    if config_path.is_file():
        try:
            with open(config_path, encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            section = raw.get("m10_metrics") or {}
        except (OSError, yaml.YAMLError):
            section = {}

    merged = dict(_M10O_DEFAULTS)
    raw_variants = section.get("variants") or {}
    if isinstance(raw_variants, list):
        variant_ids = raw_variants
        variant_version = 1
    else:
        variant_ids = raw_variants.get("ids") or []
        variant_version = raw_variants.get("version", 1)
    merged["variants"] = {
        "version": variant_version,
        "ids": variant_ids or _M10O_DEFAULTS["variants"]["ids"],
    }
    merged.update({k: v for k, v in section.items() if k not in ("variants",)})
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
    # Production forces the Secure flag on via auth_cookie_secure_effective, so
    # the raw default (False) must not be treated as an unsafe configuration --
    # otherwise a correct production deploy crashes on startup. Guard the
    # *effective* value so a future regression that stops forcing Secure is
    # still caught loudly.
    if settings.app_env == "production" and not settings.auth_cookie_secure_effective:
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