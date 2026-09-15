"""Health + application meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, rfc3339_now, to_jsonable
from ..data import data_directory_status
from .deps import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Structured health payload. Never leaks secrets."""
    return {
        "status": "ok",
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "timestamp": rfc3339_now(),
        "auth": {"configured": settings.auth_configured},
        "ai": {"service": "Gemini", "configured": settings.gemini_configured},
    }


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)) -> dict:
    """Non-secret application metadata, safe for the UI."""
    return {
        "application": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "debug": settings.app_debug,
        "data_root": str(settings.data_root_path),
        "settings": settings.public_dict(),
        "data_directories": [to_jsonable(d) for d in data_directory_status(settings)],
    }