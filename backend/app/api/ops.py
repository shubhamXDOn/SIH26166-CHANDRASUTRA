"""M11 operational endpoints (admin-only operational view — not a science UI).

``GET /api/ops/overview`` gives a compact, honest system-status surface:
backend/database/filesystem/configuration/authentication/AI/deep-matcher/data
readiness, recent security failures, and recent run durations. It exposes no
secrets, no stack traces, no internal absolute paths and no scientific results.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth.dependencies import AdminUser
from ..ops import ops_overview
from ..state import get_state

router = APIRouter(
    prefix="/ops",
    tags=["operations"],
)


@router.get("/overview")
def overview(_admin: AdminUser) -> dict:
    """Compact operational overview (admin only)."""
    settings = get_state().settings
    return ops_overview(settings)


__all__ = ["router"]