"""M10 token utilities.

Access tokens are short-lived JWT HS256 with a ``typ`` claim, a ``jti``, and
issuer/audience. Refresh tokens are opaque random strings; only their
SHA-256 hash is ever stored server-side, so a leaked database never reveals
usable refresh tokens. Token content deliberately excludes passwords, keys
and scientific evidence.
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid
from typing import Any

import jwt

from ..config import Settings
from ..errors import TokenExpiredError, TokenInvalidError
from ..security import Role

_TOKEN_TYPE_ACCESS = "access"
_TOKEN_TYPE_REFRESH = "refresh"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def access_token_ttl(settings: Settings, auth_config: Any) -> int:
    from .config import load_auth_config

    cfg = auth_config if auth_config is not None else load_auth_config(settings)
    if settings.auth_access_ttl_seconds:
        return settings.auth_access_ttl_seconds
    return int(cfg.access_token_ttl_seconds)


def refresh_token_ttl(settings: Settings, auth_config: Any) -> int:
    from .config import load_auth_config

    cfg = auth_config if auth_config is not None else load_auth_config(settings)
    if settings.auth_refresh_ttl_seconds:
        return settings.auth_refresh_ttl_seconds
    return int(cfg.refresh_token_ttl_seconds)


def create_access_token(
    *,
    settings: Settings,
    subject: str,
    role: Role,
    ttl_seconds: int | None = None,
    auth_config: Any = None,
    extra: dict[str, Any] | None = None,
) -> str:
    if not settings.auth_configured:
        raise TokenInvalidError("Authentication is not configured (AUTH_SECRET_KEY is empty).")
    now = _utcnow()
    ttl = ttl_seconds or access_token_ttl(settings, auth_config)
    claims: dict[str, Any] = {
        "sub": subject,
        "role": role.value,
        "iat": now,
        "exp": now + datetime.timedelta(seconds=ttl),
        "iss": settings.auth_issuer_value,
        "aud": settings.auth_audience_value,
        "jti": uuid.uuid4().hex,
        "typ": _TOKEN_TYPE_ACCESS,
    }
    if extra:
        claims.update(extra)
    return jwt.encode(claims, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def decode_access_token(
    settings: Settings, token: str, *, require_type: str = _TOKEN_TYPE_ACCESS
) -> dict[str, Any]:
    """Verify signature, expiry, issuer, audience and token type."""
    if not settings.auth_configured:
        raise TokenInvalidError("Authentication is not configured (AUTH_SECRET_KEY is empty).")
    if not token or not token.startswith("eyJ"):
        raise TokenInvalidError("Malformed access token.")
    try:
        claims = jwt.decode(
            token,
            settings.auth_secret_key,
            algorithms=[settings.auth_algorithm],
            issuer=settings.auth_issuer_value,
            audience=settings.auth_audience_value,
            options={"require": ["sub", "role", "iat", "exp", "iss", "aud", "jti", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("The session has expired; please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("Invalid or malformed access token.") from exc
    if claims.get("typ") != require_type:
        raise TokenInvalidError("Unrecognized token type.")
    return claims


def generate_refresh_token() -> tuple[str, str]:
    """Return (opaque token, sha256 hash). Only the hash is persisted."""
    raw = secrets.token_urlsafe(48)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, digest


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def refresh_jti() -> str:
    return f"R-{uuid.uuid4().hex}"


__all__ = [
    "create_access_token",
    "decode_access_token",
    "generate_refresh_token",
    "hash_refresh_token",
    "refresh_jti",
    "access_token_ttl",
    "refresh_token_ttl",
]