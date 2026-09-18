"""AI subpackage — real Gemini assistant (M9)."""

from .config import AIConfig, load_ai_config
from .evidence import EvidenceBuild, EvidenceBuilder, Sanitizer, canonical_digest
from .models import AIAnswer, AIRequest, AIResponse
from .service import (
    AIServiceState,
    AIServiceStatus,
    GeminiAssistant,
    build_assistant,
)
from .states import AITask, is_terminal
from .validator import ResponseValidator, ValidationResult

__all__ = [
    "AIConfig",
    "AIAnswer",
    "AIRequest",
    "AIResponse",
    "AIServiceState",
    "AIServiceStatus",
    "AITask",
    "EvidenceBuild",
    "EvidenceBuilder",
    "GeminiAssistant",
    "ResponseValidator",
    "Sanitizer",
    "ValidationResult",
    "build_assistant",
    "canonical_digest",
    "is_terminal",
    "load_ai_config",
]