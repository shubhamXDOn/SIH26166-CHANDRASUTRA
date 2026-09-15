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
    app_env: str = "development"  # development | production
    app_debug: bool = True
    app_version: str = "0.1.0"

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
    return PipelineConfig(source=str(config_path), **raw)


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