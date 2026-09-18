"""M9 Gemini HTTP client (real provider call).

This client talks to the official Google Generative Language REST API
(``generativelanguage.googleapis.com/v1beta``). The API key is sent only in
the ``x-goog-api-key`` header — it is never logged, never placed on the
AIConfig object, and never included in any response.

Retry policy is deliberately conservative (1 retry on transient provider
failures with a short backoff) so a failing provider can never burn unbounded
quota. Timeout and output-token bounds come from configuration.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from ..config import Settings
from .config import AIConfig
from .states import AIServiceState

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


@dataclass
class GeminiResult:
    ok: bool
    state: AIServiceState
    text: str = ""
    latency_ms: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    error_code: str = ""
    raw_status_code: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "state": self.state.value,
            "latency_ms": round(self.latency_ms, 1),
            "usage": dict(self.usage),
            "error_code": self.error_code,
        }


class GeminiClient:
    def __init__(self, settings: Settings, ai_config: AIConfig):
        self._settings = settings
        self._cfg = ai_config
        self._key = settings.gemini_api_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def model(self) -> str:
        return self._settings.gemini_model

    def _max_attempts(self) -> int:
        return 1 + max(0, int(self._cfg.extras.get("max_retries", 1)))

    def generate(self, *, system: str, contents: str,
                 max_output_tokens: int | None = None) -> GeminiResult:
        if not self.configured:
            return GeminiResult(
                ok=False,
                state=AIServiceState.NOT_CONFIGURED,
                error="Gemini is not configured (GEMINI_API_KEY is empty).",
                error_code="NOT_CONFIGURED",
            )

        url = (
            f"{_GEMINI_BASE}/models/{quote(self.model)}:generateContent"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": contents}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_output_tokens or self._cfg.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        headers = {
            "x-goog-api-key": self._key,
            "content-type": "application/json",
            "accept": "application/json",
        }

        started = time.perf_counter()
        max_attempts = self._max_attempts()
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            try:
                resp = httpx.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._cfg.timeout_seconds,
                )
            except httpx.TimeoutException:
                latency_ms = (time.perf_counter() - started) * 1000.0
                return GeminiResult(
                    ok=False,
                    state=AIServiceState.TIMEOUT,
                    latency_ms=latency_ms,
                    error="Gemini request timed out.",
                    error_code="TIMEOUT",
                )
            except httpx.RequestError as exc:
                latency_ms = (time.perf_counter() - started) * 1000.0
                if attempt < max_attempts:
                    time.sleep(0.5)
                    continue
                return GeminiResult(
                    ok=False,
                    state=AIServiceState.PROVIDER_ERROR,
                    latency_ms=latency_ms,
                    error=f"Gemini provider unreachable: {type(exc).__name__}",
                    error_code="PROVIDER_UNREACHABLE",
                )

            latency_ms = (time.perf_counter() - started) * 1000.0
            status = resp.status_code

            if status == 429:
                if attempt < max_attempts:
                    time.sleep(1.0)
                    continue
                return GeminiResult(
                    ok=False,
                    state=AIServiceState.RATE_LIMITED,
                    latency_ms=latency_ms,
                    error="Gemini rate-limited the request.",
                    error_code="RATE_LIMITED",
                    raw_status_code=status,
                )
            if status >= 500:
                if attempt < max_attempts:
                    time.sleep(1.0)
                    continue
                return GeminiResult(
                    ok=False,
                    state=AIServiceState.PROVIDER_ERROR,
                    latency_ms=latency_ms,
                    error=f"Gemini provider error (HTTP {status}).",
                    error_code="PROVIDER_ERROR",
                    raw_status_code=status,
                )
            if status >= 400:
                return GeminiResult(
                    ok=False,
                    state=AIServiceState.PROVIDER_ERROR,
                    latency_ms=latency_ms,
                    error=f"Gemini rejected the request (HTTP {status}).",
                    error_code="PROVIDER_REQUEST_ERROR",
                    raw_status_code=status,
                )

            parsed = self._parse_ok(resp, latency_ms)
            if attempt < max_attempts and not parsed.ok and parsed.state is AIServiceState.PROVIDER_ERROR:
                time.sleep(0.5)
                continue
            return parsed

        return GeminiResult(
            ok=False,
            state=AIServiceState.PROVIDER_ERROR,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            error="Gemini call exhausted retry budget.",
            error_code="PROVIDER_ERROR",
        )

    # ------------------------------------------------------------------
    def _parse_ok(self, resp: httpx.Response, latency_ms: float) -> GeminiResult:
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            return GeminiResult(
                ok=False,
                state=AIServiceState.PROVIDER_ERROR,
                latency_ms=latency_ms,
                error="Gemini returned a non-JSON body.",
                error_code="PROVIDER_BAD_BODY",
                raw_status_code=resp.status_code,
            )

        usage_metadata = data.get("usageMetadata") if isinstance(data, dict) else None
        usage: dict[str, Any] = {
            "input_tokens": "NOT_AVAILABLE",
            "output_tokens": "NOT_AVAILABLE",
            "model": self.model,
        }
        if isinstance(usage_metadata, dict):
            if "promptTokenCount" in usage_metadata:
                usage["input_tokens"] = int(usage_metadata["promptTokenCount"])
            if "candidatesTokenCount" in usage_metadata:
                usage["output_tokens"] = int(usage_metadata["candidatesTokenCount"])

        prompt_feedback = data.get("promptFeedback") if isinstance(data, dict) else None
        if isinstance(prompt_feedback, dict) and prompt_feedback.get("blockReason"):
            return GeminiResult(
                ok=False,
                state=AIServiceState.BLOCKED,
                latency_ms=latency_ms,
                usage=usage,
                error=f"Gemini blocked the request: {prompt_feedback.get('blockReason')}",
                error_code="BLOCKED",
                raw_status_code=resp.status_code,
            )

        text = self._extract_text(data)
        if not text:
            return GeminiResult(
                ok=False,
                state=AIServiceState.PROVIDER_ERROR,
                latency_ms=latency_ms,
                usage=usage,
                error="Gemini returned no usable text candidates.",
                error_code="EMPTY_CANDIDATES",
                raw_status_code=resp.status_code,
            )
        return GeminiResult(
            ok=True,
            state=AIServiceState.COMPLETE,
            text=text,
            latency_ms=latency_ms,
            usage=usage,
            raw_status_code=resp.status_code,
        )

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(candidates, list) or not candidates:
            return ""
        content = candidates[0].get("content") if isinstance(candidates[0], dict) else None
        if not isinstance(content, dict):
            return ""
        parts = content.get("parts") or []
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "".join(chunks)


__all__ = ["GeminiClient", "GeminiResult"]