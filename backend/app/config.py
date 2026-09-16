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
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Root of the repository, resolved from the location of this file.
# backend/app/config.py -> backend/app -> backend -> repo root
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_ROOT_DEFAULT = BASE_DIR / "data"
CONFIG_FILE_DEFAULT = BASE_DIR / "configs" / "app.yaml"


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
    milestone: str = "M2"
    app_env: str = "development"  # development | production
    app_debug: bool = True
    app_version: str = "0.2.0"

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    data_root: str = ""

    # --- Security (empty until real authentication milestone) ---
    auth_secret_key: str = ""
    auth_token_expire_minutes: int = 60
    auth_algorithm: str = "HS256"

    # --- AI / Gemini (optional in M0) ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    @property
    def data_root_path(self) -> Path:
        return Path(self.data_root).expanduser() if self.data_root else DATA_ROOT_DEFAULT

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]

    @property
    def auth_configured(self) -> bool:
        return bool(self.auth_secret_key.strip())

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
            "app_version": self.app_version,
            "cors_origins": self.cors_origin_list,
            "log_level": self.log_level,
            "data_root": str(self.data_root_path),
            "auth": {
                "configured": self.auth_configured,
                "algorithm": self.auth_algorithm,
            },
            "ai": {
                "service": "Gemini",
                "configured": self.gemini_configured,
                "model": self.gemini_model,
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

    Mirrors ``m1_config``: cached per process, falls back to documented
    defaults when the YAML is unavailable, and never raises on parse.
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
    },
}


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