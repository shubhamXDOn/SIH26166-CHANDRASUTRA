"""M10 authentication endpoints — real accounts, sessions and roles.

Public routes:      GET  /api/auth/status, POST /api/auth/register, POST /api/auth/login
Authenticated:      GET  /api/auth/me, POST /api/auth/me/password, POST /api/auth/logout,
                    POST /api/auth/refresh
Administrator-only: GET  /api/auth/users, GET /api/auth/users/{id}, PATCH /api/auth/users/{id},
                    GET  /api/auth/security-summary

Conventions:
    * the access token is returned in the JSON body (frontend keeps it in
      memory only); the refresh token is additionally returned in an HttpOnly
      cookie for transport flexibility
    * secrets never appear in responses, errors, provenance or logs
    * the refresh token stored on disk is a SHA-256 hash, never the value
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from ..auth.dependencies import (
    AdminUser,
    AuthServiceDeps,
    CurrentUser,
    get_auth_service,
)
from ..auth.models import (
    AdminUserPatch,
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
)
from ..config import Settings
from ..logging_conf import get_logger
from .deps import get_settings

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _maybe_current_user(request: Request, service: AuthServiceDeps) -> object:
    """Resolve identity when a bearer token is present; never raises."""
    header = request.headers.get("authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    try:
        return service.get_current_user_from_authorization(header)
    except Exception:
        return None


def _set_refresh_cookie(response: Response, settings: Settings, refresh_token: str, *, expires_seconds: int) -> None:
    response.set_cookie(
        key=settings.auth_refresh_cookie_name,
        value=refresh_token,
        max_age=expires_seconds,
        httponly=True,
        secure=settings.auth_cookie_secure_effective,
        samesite=settings.auth_cookie_samesite,
        path="/api/auth/",
    )


@router.get("/status")
def auth_status(
    request: Request,
    service: AuthServiceDeps,
    settings: SettingsDep,
) -> dict:
    """Non-secret authentication configuration + current session identity (optional)."""
    current = _maybe_current_user(request, service)
    return service.status_dict(current_user=current)


@router.post("/register")
def register(
    payload: RegisterRequest,
    service: AuthServiceDeps,
    settings: SettingsDep,
) -> dict:
    user = service.register(
        username=payload.username, password=payload.password, display_name=payload.display_name
    )
    return {"user": user.as_dict(), "registration_enabled": service.config.registration_enabled}


@router.post("/login")
def login(
    payload: LoginRequest,
    response: Response,
    service: AuthServiceDeps,
    settings: SettingsDep,
) -> dict:
    result = service.login(username=payload.username, password=payload.password)
    _set_refresh_cookie(
        response,
        settings,
        result["refresh_token"],
        expires_seconds=int(result["refresh_token_expires_in"]),
    )
    result.pop("refresh_token", None)
    return result


@router.post("/refresh")
def refresh(
    response: Response,
    request: Request,
    service: AuthServiceDeps,
    settings: SettingsDep,
    payload: RefreshRequest | None = None,
) -> dict:
    refresh_token = (payload.refresh_token if payload else "") or request.cookies.get(
        settings.auth_refresh_cookie_name, ""
    )
    result = service.refresh(refresh_token)
    _set_refresh_cookie(
        response,
        settings,
        result["refresh_token"],
        expires_seconds=int(result["refresh_token_expires_in"]),
    )
    result.pop("refresh_token", None)
    return result


@router.post("/logout")
def logout(
    response: Response,
    request: Request,
    service: AuthServiceDeps,
    settings: SettingsDep,
    payload: RefreshRequest | None = None,
) -> dict:
    refresh_token = (payload.refresh_token if payload else "") or request.cookies.get(
        settings.auth_refresh_cookie_name, ""
    )
    current_user = _maybe_current_user(request, service)
    user_id = current_user.id if current_user is not None else None
    result = service.logout(refresh_token, user_id=user_id)
    response.delete_cookie(
        settings.auth_refresh_cookie_name,
        path="/api/auth/",
        secure=settings.auth_cookie_secure_effective,
    )
    return result


@router.get("/me")
def me(current: CurrentUser) -> dict:
    return {"user": current.as_dict()}


@router.post("/me/password")
def change_password(
    payload: ChangePasswordRequest,
    service: AuthServiceDeps,
    current: CurrentUser,
) -> dict:
    service.change_password(current, payload.current_password, payload.new_password)
    return {"changed": True, "sessions_revoked": True}


@router.get("/users")
def list_users(admin: AdminUser, service: AuthServiceDeps) -> dict:
    return {"users": service.list_users()}


@router.get("/users/{user_id}")
def get_user(user_id: str, admin: AdminUser, service: AuthServiceDeps) -> dict:
    return {"user": service.get_user(user_id)}


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    payload: AdminUserPatch,
    admin: AdminUser,
    service: AuthServiceDeps,
) -> dict:
    return {
        "user": service.patch_user(admin, user_id, new_role=payload.role, is_active=payload.is_active)
    }


@router.get("/security-summary")
def security_summary(admin: AdminUser, service: AuthServiceDeps) -> dict:
    return service.security_summary()


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, admin: AdminUser, service: AuthServiceDeps) -> dict:
    return service.revoke_session(admin, session_id)