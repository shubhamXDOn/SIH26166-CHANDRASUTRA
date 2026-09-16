"""Health + application meta endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import Settings, m1_config, m2_config, m3_config, m4_config, m5_config, rfc3339_now, to_jsonable
from ..data import data_directory_status
from .deps import get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
def health(settings: Settings = Depends(get_settings)) -> dict:
    """Structured health payload. Never leaks secrets."""
    return {
        "status": "ok",
        "application": settings.product_name,
        "project": settings.app_name,
        "tagline": settings.tagline,
        "milestone": settings.milestone,
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
        "application": settings.product_name,
        "project_identifier": settings.app_name,
        "tagline": settings.tagline,
        "milestone": settings.milestone,
        "version": settings.app_version,
        "environment": settings.app_env,
        "debug": settings.app_debug,
        "data_root": str(settings.data_root_path),
        "m1_config": m1_config(),
        "m2_config": m2_config(),
        "m3_config": m3_config(),
        "m4_config": m4_config(),
        "m5_config": m5_config(),
        "settings": settings.public_dict(),
        "data_directories": [to_jsonable(d) for d in data_directory_status(settings)],
    }