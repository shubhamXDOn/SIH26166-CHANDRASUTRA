"""Authentication & authorization FOUNDATION (M0).

M0 deliberately ships the *secure architecture*, not the full system:

    * user schema (pydantic) with roles
    * secure password hashing boundary (stdlib PBKDF2-HMAC-SHA256)
    * access-token signing boundary (JWT HS256 via PyJWT, key from env)
    * protected-route dependency that is safe when auth is NOT configured
    * role/authorization boundary

Real user storage, login flows and account provisioning are a later
milestone. Until then, auth endpoints return an explicit 501 NOT_CONFIGURED
and protected routes are locked behind the ``require_configured_auth`` guard.
Nothing here fakes a login; nothing stores plaintext passwords; no secret is
hardcoded (AUTH_SECRET_KEY comes from the environment or .env).
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from enum import Enum
from typing import Any

import jwt
from fastapi import Header
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .config import Settings
from .errors import UnauthorizedError


class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"

    @classmethod
    def description(cls) -> str:
        return (
            "admin: manage users, roles, security audit and config; "
            "analyst: execute processing/analysis workflows and view data; "
            "viewer: inspect results and use explanatory AI."
        )

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self.value]


_ROLE_RANK = {
    Role.VIEWER.value: 0,
    Role.ANALYST.value: 1,
    Role.ADMIN.value: 2,
}


def roles_at_least(role: Role) -> set[Role]:
    """All roles with rank >= ``role`` (used for authorization)."""
    return {r for r in Role if r.rank >= role.rank}


# ---------------------------------------------------------------------------
# User schema
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    """Payload for creating a user (used by a later milestone)."""

    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w.\-]+$")
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(default="", max_length=128)
    role: Role = Role.VIEWER


class UserInDB(BaseModel):
    """A stored user. Never expose the password hash to clients."""

    username: str
    display_name: str
    role: Role
    password_hash: str = Field(exclude=True)

    def public_view(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role.value,
        }


# ---------------------------------------------------------------------------
# Password hashing (stdlib only, safe defaults)
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 210_000


def hash_password(password: str, *, salt: str | None = None) -> str:
    """Return ``pbkdf2_sha256$<iterations>$<salt>$<hex-digest>``."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Access tokens (JWT HS256) — secret comes from environment/.env only
# ---------------------------------------------------------------------------

TokenClaims = dict[str, Any]


def create_access_token(settings: Settings, subject: str, role: Role, extra: dict[str, Any] | None = None) -> str:
    if not settings.auth_configured:
        raise UnauthorizedError("Authentication is not configured (AUTH_SECRET_KEY is empty).")
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    claims: TokenClaims = {
        "sub": subject,
        "role": role.value,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=settings.auth_token_expire_minutes),
        "iss": settings.app_name,
    }
    if extra:
        claims.update(extra)
    return jwt.encode(claims, settings.auth_secret_key, algorithm=settings.auth_algorithm)


def decode_access_token(settings: Settings, token: str) -> TokenClaims:
    if not settings.auth_configured:
        raise UnauthorizedError("Authentication is not configured (AUTH_SECRET_KEY is empty).")
    try:
        return jwt.decode(
            token,
            settings.auth_secret_key,
            algorithms=[settings.auth_algorithm],
            issuer=settings.app_name,
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Session has expired; please sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or malformed access token.") from exc


# ---------------------------------------------------------------------------
# FastAPI dependency guard
# ---------------------------------------------------------------------------

class AuthGuard:
    """Reusable dependency. Behavour while auth is NOT configured (M0):

    * any attempt to use authentication raises 501 NOT_CONFIGURED
    * any protected endpoint is therefore impossible to reach until the
      real authentication milestone — nothing is silently faked.
    """

    def __init__(self, settings: Settings):
        self._settings = settings

    def require_configured(self) -> None:
        if not self._settings.auth_configured:
            raise UnauthorizedError("Authentication is not configured (AUTH_SECRET_KEY is empty).")

    def get_current_user(
        self,
        authorization: str | None = Header(default=None),
        settings: BaseSettings | None = None,
    ) -> dict[str, str]:
        del settings
        self.require_configured()
        if not authorization or not authorization.lower().startswith("bearer "):
            raise UnauthorizedError("Missing bearer token.")
        token = authorization.split(" ", 1)[1].strip()
        claims = decode_access_token(self._settings, token)
        return {
            "username": str(claims.get("sub", "")),
            "role": str(claims.get("role", "")),
        }

    def require_role(self, allowed: set[Role]) -> dict[str, str]:
        user = self.get_current_user()
        if user["role"] not in {r.value for r in allowed}:
            raise UnauthorizedError("Insufficient privileges for this operation.")
        return user


# Standalone dependency for routers without a bound settings instance
_auth_guard: AuthGuard | None = None


def configure_auth_guard(settings: Settings) -> AuthGuard:
    global _auth_guard
    _auth_guard = AuthGuard(settings)
    return _auth_guard


def get_auth_guard() -> AuthGuard:
    if _auth_guard is None:
        raise RuntimeError("Auth guard not configured; call configure_auth_guard at startup.")
    return _auth_guard


def require_db_session() -> None:
    """Placeholder boundary for the database/session milestone."""
    raise UnauthorizedError("Persistent user storage is not configured (future milestone).")


# ---------------------------------------------------------------------------
# Redaction inside security.py for lazy import safety.
# ---------------------------------------------------------------------------

_REDACT_TOKEN_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9\-_\.=]+")
_REDACT_HEADER_RE = re.compile(r"(?i)((?:authorization|x-goog-api-key|api[-_]key|refresh[-_]token|jwt[-_]secret|password[-_]hash)\s*[:=]\s*)([^\s,;]+)")
_REDACT_JWT_RE = re.compile(r"(?i)\beyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.([A-Za-z0-9\-_]+)")


def redact_text(text: str) -> str:
    """Scrub common secret patterns from a piece of text (logs, messages)."""
    if not text:
        return text
    text = _REDACT_HEADER_RE.sub(lambda m: f"{m.group(1)}***", text)
    text = _REDACT_TOKEN_RE.sub(r"\1***", text)
    text = _REDACT_JWT_RE.sub(r"eyJ***.***.***", text)
    return text


__all__ = [
    "Role",
    "UserCreate",
    "UserInDB",
    "hash_password",
    "verify_password",
    "create_access_token",
    "decode_access_token",
    "AuthGuard",
    "configure_auth_guard",
    "get_auth_guard",
    "require_db_session",
    "redact_text",
]