"""FastAPI dependencies bridging the M10 auth service into endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from ..security import Role
from ..state import get_state
from .models import SafeUser
from .service import AuthService


def get_auth_service() -> AuthService:
    return get_state().auth


AuthServiceDeps = Annotated[AuthService, Depends(get_auth_service)]


def current_user_dep(request: Request, service: AuthServiceDeps) -> SafeUser:
    """Resolve and validate the bearer token; enforce active-account policy."""
    return service.get_current_user_from_authorization(request.headers.get("authorization"))


CurrentUser = Annotated[SafeUser, Depends(current_user_dep)]


def require_admin_dep(user: CurrentUser, service: AuthServiceDeps) -> SafeUser:
    return service.require_role(user, Role.ADMIN)


AdminUser = Annotated[SafeUser, Depends(require_admin_dep)]


def require_analyst_dep(user: CurrentUser, service: AuthServiceDeps) -> SafeUser:
    return service.require_role(user, Role.ADMIN, Role.ANALYST)


AnalystUser = Annotated[SafeUser, Depends(require_analyst_dep)]

__all__ = [
    "AuthServiceDeps",
    "CurrentUser",
    "AdminUser",
    "AnalystUser",
    "get_auth_service",
]