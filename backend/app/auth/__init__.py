"""M10 — Full Authentication, Authorization & User Security.

The public surface is the :class:`AuthService` (identity, sessions, roles)
plus the ``api/auth.py`` router. Persistence: SQLite under
``<data_root>/auth/auth.db``. Tokens: short-lived JWT access tokens + opaque
rotated refresh tokens (SHA-256 hash only on disk).
"""

from __future__ import annotations

from .audit import SECURITY_AUDIT_EVENTS, SecurityAudit
from .config import AAuthConfig, LoginRateLimit, PasswordPolicy, load_auth_config
from .models import (
    AdminUserPatch,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RefreshSession,
    SafeUser,
    UserInDB,
)
from .service import AuthService, build_auth_service

__all__ = [
    "AAuthConfig",
    "AuthService",
    "build_auth_service",
    "SECURITY_AUDIT_EVENTS",
    "SecurityAudit",
    "LoginRateLimit",
    "PasswordPolicy",
    "load_auth_config",
    "UserInDB",
    "SafeUser",
    "RefreshSession",
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "ChangePasswordRequest",
    "AdminUserPatch",
]