"""AI assistant endpoints — FOUNDATION ONLY (M0).

The frontend always talks to *this* backend for AI. The Gemini key is a
backend-only secret and is never exposed to the browser.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..ai import AIServiceStatus
from ..config import Settings
from ..errors import NotConfiguredError
from ..state import get_state
from .deps import get_settings

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/status")
def ai_status() -> dict:
    assistant = get_state().assistant
    return assistant.status_dict()


@router.post("/explain")
def ai_explain(_settings: Settings = Depends(get_settings)) -> dict:
    """Contract stub: real explanations arrive with Gemini integration.

    In M0 this is never fabricated — it always reports the true state.
    """
    assistant = get_state().assistant
    if assistant.status is AIServiceStatus.NOT_CONFIGURED:
        raise NotConfiguredError(
            "No AI explanation can be generated because Gemini is not configured "
            "(GEMINI_API_KEY is empty).",
            details={"milestone": "M0", "status": "NOT_CONFIGURED"},
        )
    raise NotConfiguredError(
        "AI explanation endpoint exists but Gemini streaming is not implemented yet.",
        details={"milestone": "M0", "next": "Gemini integration milestone"},
    )