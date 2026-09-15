"""Authentication endpoints — FOUNDATION ONLY (M0).

The routes are defined now so the API surface is stable, but every handler
returns an explicit 501 NOT_CONFIGURED until the real authentication
milestone provides persistent user storage. There is no fake login: a client
can never obtain a session in M0.

Future handlers (to be filled in a later milestone, without breaking this
API shape):

    POST /api/auth/login    -> 200 {access_token, token_type, user}
    POST /api/auth/logout   -> 200 {message}
    GET  /api/auth/me       -> 200 {user}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings
from ..errors import NotConfiguredError
from ..logging_conf import get_logger
from ..security import Role
from .deps import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

_AUTH_NOT_CONFIGURED = "Authentication is not configured in M0 (AUTH_SECRET_KEY empty)."


def _require_auth_configured(settings: Settings) -> None:
    if not settings.auth_configured:
        raise NotConfiguredError(
            _AUTH_NOT_CONFIGURED,
            details={"milestone": "M0", "required": "AUTH_SECRET_KEY", "available": "later milestone"},
        )


@router.post("/login")
def login(_settings: Settings = Depends(get_settings)) -> dict:
    _require_auth_configured(_settings)
    raise NotConfiguredError(
        "Login requires persistent user storage, which is a later milestone.",
        details={"milestone": "M0"},
    )


@router.post("/logout")
def logout() -> dict:
    # Logout is meaningful only when sessions exist. Until then it is a
    # contract stub that reports the true state of the system.
    raise NotConfiguredError(
        _AUTH_NOT_CONFIGURED,
        details={"milestone": "M0"},
    )


@router.get("/me")
def me() -> dict:
    raise NotConfiguredError(
        _AUTH_NOT_CONFIGURED,
        details={"milestone": "M0"},
    )


@router.get("/status")
def auth_status(settings: Settings = Depends(get_settings)) -> dict:
    """Non-secret status of the authentication foundation."""
    return {
        "configured": settings.auth_configured,
        "milestone": "M0",
        "roles": [r.value for r in Role],
        "policy": {
            "no_plaintext_passwords": True,
            "secret_from_environment": True,
            "no_fake_login": True,
            "protected_routes_architected": True,
            "auth_service_boundary": "backend/app/security.py",
        },
    }