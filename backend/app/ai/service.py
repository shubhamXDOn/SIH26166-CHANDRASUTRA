"""AI assistant service boundary (M0).

* Real Gemini integration arrives in a later milestone.
* If GEMINI_API_KEY is missing the service reports NOT_CONFIGURED and the
  application keeps running — it never crashes startup.
* The AI key lives only in backend configuration (env/.env) and is NEVER
  exposed to browser code. The frontend calls our backend AI endpoints.
* The AI layer is explanatory/assistive. It must never be the source of
  scientific registration truth.
* Responses are never fabricated. When the service cannot produce a real
  answer it returns a structured "not available" state.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..config import Settings
from ..logging_conf import get_logger

logger = get_logger(__name__)


class AIServiceStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"
    ERROR = "ERROR"


class AIExplainRequest:
    """User-facing request to explain an analysis artifact (future)."""

    def __init__(self, *, context: dict[str, Any], prompt: str):
        self.context = context
        self.prompt = prompt


class AIExplainResponse:
    """Structured assistant response (future real content)."""

    def __init__(self, *, available: bool, status: AIServiceStatus, text: str = "", error: str = ""):
        self.available = available
        self.status = status
        self.text = text
        self.error = error

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status.value,
            "text": self.text,
            "error": self.error,
        }


class GeminiAssistant:
    """Boundary for the Gemini-based explanatory layer.

    M0 implements: configuration check, status, and a truthful
    NOT_CONFIGURED response. The ``explain`` method is the single seam that
    later milestones fill with a real, authenticated Gemini call.
    """

    service_name = "Gemini"

    def __init__(self, settings: Settings):
        self._settings = settings
        self._status = (
            AIServiceStatus.READY if settings.gemini_configured else AIServiceStatus.NOT_CONFIGURED
        )

    @property
    def status(self) -> AIServiceStatus:
        return self._status

    def status_dict(self) -> dict[str, Any]:
        return {
            "service": self.service_name,
            "status": self.status.value,
            "configured": self._settings.gemini_configured,
            "model": self._settings.gemini_model,
            "policy": {
                "explanatory_only": True,
                "core_science_source": "backend scientific pipeline (future milestones)",
                "no_fabricated_responses": True,
            },
        }

    def explain(self, request: AIExplainRequest) -> AIExplainResponse:
        """Seam for real Gemini calls (future milestone).

        Returns a truthful NOT_CONFIGURED response when the key is absent.
        """
        if not self._settings.gemini_configured:
            logger.info(
                "AI explain requested but service is NOT_CONFIGURED.",
                extra={"operation": "ai.explain", "status": "not_configured"},
            )
            return AIExplainResponse(
                available=False,
                status=AIServiceStatus.NOT_CONFIGURED,
                error=(
                    "Gemini is not configured on this instance (GEMINI_API_KEY is empty). "
                    "No AI explanation can be produced."
                ),
            )

        # Reachable only once real Gemini integration exists.
        raise NotImplementedError("Gemini call implementation arrives in a later milestone.")


def build_assistant(settings: Settings) -> GeminiAssistant:
    return GeminiAssistant(settings)