"""M10 authentication configuration.

The M10 engineering policy lives in ``configs/app.yaml`` (``m10:``,
Configuration ID ``AU-M10-001``) and is exposed read-only through
``GET /api/auth/status``. Secrets (the JWT signing key) come from the
environment only and never appear here.

``load_auth_config`` merges the YAML defaults with runtime ``Settings``
overrides (TTLs, registration toggle) so operators can tune values without
editing source control.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..config import Settings, m10_config


class PasswordPolicy(BaseModel):
    min_length: int = 12
    require_letter: bool = True
    require_digit: bool = True
    disallow_username: bool = True


class LoginRateLimit(BaseModel):
    max_attempts: int = 5
    window_seconds: int = 300
    lockout_seconds: int = 900


class AAuthConfig(BaseModel):
    """Non-secret M10 authentication engineering policy."""

    configuration_id: str = "AU-M10-001"
    configuration_version: int = 1
    name: str = "Full Authentication, Authorization & User Security"
    source_reference: str = ""
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 604800
    session_idle_ttl_seconds: int = 86400
    password_policy: PasswordPolicy = Field(default_factory=PasswordPolicy)
    login_rate_limit: LoginRateLimit = Field(default_factory=LoginRateLimit)
    refresh_rotation: bool = True
    registration_enabled: bool = True
    roles: dict[str, str] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    source: str = ""

    def public_dict(self) -> dict[str, Any]:
        return {
            "configuration_id": self.configuration_id,
            "configuration_version": self.configuration_version,
            "name": self.name,
            "access_token_ttl_seconds": self.access_token_ttl_seconds,
            "refresh_token_ttl_seconds": self.refresh_token_ttl_seconds,
            "session_idle_ttl_seconds": self.session_idle_ttl_seconds,
            "password_policy": self.password_policy.model_dump(),
            "registration_enabled": self.registration_enabled,
            "refresh_rotation": self.refresh_rotation,
            "roles": dict(self.roles),
            "policy": dict(self.policy),
            "source_reference": self.source_reference,
            "source": self.source,
        }


def load_auth_config(settings: Settings, path: Any = None) -> AAuthConfig:
    """Load M10 auth policy (YAML defaults overlaid with runtime overrides)."""
    raw = dict(m10_config(path))
    raw["source"] = str(raw.get("source", ""))

    if settings.auth_access_ttl_seconds:
        raw["access_token_ttl_seconds"] = settings.auth_access_ttl_seconds
    if settings.auth_refresh_ttl_seconds:
        raw["refresh_token_ttl_seconds"] = settings.auth_refresh_ttl_seconds

    cfg = AAuthConfig(**raw)
    cfg.registration_enabled = settings.auth_register_enabled
    return cfg


__all__ = ["AAuthConfig", "load_auth_config", "PasswordPolicy", "LoginRateLimit"]