"""M10 authentication data models.

``UserInDB`` is the persistence shape (never serialized to clients).
``SafeUser`` is the only user object the API ever returns. Request models
define the exact wire contract for each auth endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from ..security import Role


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_user_id() -> str:
    from ..config import to_jsonable

    del to_jsonable
    return f"U-{uuid.uuid4().hex[:12]}"


class UserInDB(BaseModel):
    """Stored user row. Never expose ``password_hash`` to clients."""

    id: str
    username: str
    display_name: str = ""
    password_hash: str = Field(exclude=True)
    role: Role
    is_active: bool = True
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    last_login_at: str | None = None

    def safe(self) -> "SafeUser":
        return SafeUser(
            id=self.id,
            username=self.username,
            display_name=self.display_name,
            role=self.role.value,
            is_active=self.is_active,
            created_at=self.created_at,
            updated_at=self.updated_at,
            last_login_at=self.last_login_at,
        )


class SafeUser(BaseModel):
    """Public user object — contains no credential material."""

    id: str
    username: str
    display_name: str = ""
    role: str
    is_active: bool = True
    created_at: str
    updated_at: str
    last_login_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump()


class RefreshSession(BaseModel):
    """One refresh-token session. Only the SHA-256 hash is stored."""

    id: str
    user_id: str
    token_hash: str = Field(exclude=True)
    created_at: str
    expires_at: str
    revoked_at: str | None = None
    last_used_at: str


# ---------------------------------------------------------------------------
# Wire request models
# ---------------------------------------------------------------------------

_USERNAME_RE = r"^[A-Za-z0-9][\w.\-]{2,63}$"


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=_USERNAME_RE)
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(default="", max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(default="", max_length=256)
    password: str = Field(default="", max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(default="", max_length=512)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(default="", max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class AdminUserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


__all__ = [
    "UserInDB",
    "SafeUser",
    "RefreshSession",
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "ChangePasswordRequest",
    "AdminUserPatch",
    "new_user_id",
]