"""M9 response validation (ResponseValidator).

Provider output is untrusted. Before it may become an answer it must:

* be a valid JSON object with a non-empty string ``answer`` (only required key);
* cite only evidence that actually exists in the packet that was sent;
* avoid the forbidden result terminology;
* leak no secrets and no absolute paths.

Any violation invalidates the response (INVALID_RESPONSE) — it is discarded,
never sanitized into a plausible answer. ``response_digest`` records exactly
what the provider returned so the AI audit trail stays truthful.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .config import AIConfig
from .models import AIAnswer
from .states import AIServiceState

_ALLOWED_MILESTONES: frozenset[str] = frozenset(
    {"M2", "M3", "M4", "M5", "M6", "M7", "M8", "REFERENCE", "PIPELINE"}
)

_GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_CREDENTIAL = re.compile(r"(?i)(access_token|api_key|apikey|authorization|auth)\s*[:=]\s*\S+")
_ABS_WINDOWS = re.compile(r"[A-Za-z]:[\\/][^\s\"{},]+")
_ABS_POSIX = re.compile(r"(?<![\w.])/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+){1,}")
# Backend endpoints (/api/<...> with plain word segments) are legitimate
# values for suggested_inspections, not absolute filesystem paths.
_ENDPOINT_ONLY = re.compile(r"/api/(?:[a-z0-9_\-]{1,}/)*[a-z0-9_\-]+", re.IGNORECASE)


@dataclass
class ValidationResult:
    ok: bool
    state: AIServiceState
    answer: AIAnswer | None = None
    error: str = ""
    error_code: str = ""
    response_digest: str | None = None


def raw_digest(text: str, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    h.update(text.encode("utf-8"))
    return f"{algorithm}:{h.hexdigest()}"


class ResponseValidator:
    def __init__(self, ai_config: AIConfig):
        self._cfg = ai_config

    # ------------------------------------------------------------------
    def validate(self, text: str, *, packet: dict[str, Any]) -> ValidationResult:
        response_digest = raw_digest(text, algorithm=self._cfg.digest_algorithm)

        if not text or not text.strip():
            return self._invalid("Provider returned an empty response.", "EMPTY_RESPONSE", response_digest)
        if self._leaks(text):
            return self._invalid("Provider response contained a secret or absolute path.", "LEAK_DETECTED", response_digest)

        parsed = self._parse_json(text)
        if parsed is None or not isinstance(parsed, dict):
            return self._invalid("Provider output was not a valid JSON object.", "MALFORMED_JSON", response_digest)

        answer_text = parsed.get("answer")
        if not isinstance(answer_text, str) or not answer_text.strip():
            return self._invalid("Provider response has no non-empty string 'answer'.", "MISSING_ANSWER", response_digest)

        if self._leaks(answer_text):
            return self._invalid("Provider answer contained a secret or absolute path.", "LEAK_DETECTED", response_digest)

        evidence = parsed.get("evidence")
        if evidence is None:
            evidence = []
        if not isinstance(evidence, list):
            return self._invalid("'evidence' must be a list.", "MALFORMED_EVIDENCE", response_digest)

        allowed_metrics = self._metric_universe(packet)
        normalized_evidence: list[dict[str, Any]] = []
        for ref in evidence:
            if not isinstance(ref, dict):
                return self._invalid("Each evidence reference must be an object.", "MALFORMED_EVIDENCE", response_digest)
            claim = ref.get("claim")
            milestone = ref.get("source_milestone")
            metric = ref.get("source_metric")
            if not isinstance(claim, str) or not claim.strip():
                return self._invalid("An evidence reference has no non-empty claim.", "MALFORMED_EVIDENCE", response_digest)
            if not isinstance(milestone, str) or milestone.strip() not in _ALLOWED_MILESTONES:
                return self._invalid(
                    f"Evidence reference cites unknown source_milestone: {milestone!r}.",
                    "UNKNOWN_EVIDENCE_MILESTONE", response_digest)
            if metric is not None and (not isinstance(metric, str) or metric.strip() not in allowed_metrics):
                return self._invalid(
                    f"Evidence reference cites metric not present in the evidence packet: {metric!r}.",
                    "UNKNOWN_EVIDENCE_METRIC", response_digest)
            entry = {"claim": claim.strip()}
            if metric:
                entry["source_metric"] = metric.strip()
            entry["source_milestone"] = milestone.strip()
            normalized_evidence.append(entry)

        limitations = self._coerce_str_list(parsed.get("limitations"))
        if limitations is None:
            return self._invalid("'limitations' must be a list of strings.", "MALFORMED_LIMITATIONS", response_digest)
        suggestions = self._coerce_str_list(parsed.get("suggested_inspections"))
        if suggestions is None:
            return self._invalid("'suggested_inspections' must be a list of strings.", "MALFORMED_SUGGESTIONS", response_digest)

        if self._contains_forbidden(answer_text) or self._contains_forbidden_in(evidence + limitations + suggestions):
            return self._invalid(
                "Provider response used forbidden result terminology; treated as it does not exist.",
                "FORBIDDEN_TERMINOLOGY", response_digest)
        if self._leaks_in(evidence + limitations + suggestions):
            return self._invalid(
                "Provider evidence/limitation text contained a secret or absolute path.",
                "LEAK_DETECTED", response_digest)

        return ValidationResult(
            ok=True,
            state=AIServiceState.COMPLETE,
            answer=AIAnswer(
                answer=answer_text.strip(),
                evidence=normalized_evidence,
                limitations=limitations,
                suggested_inspections=suggestions,
            ),
            response_digest=response_digest,
        )

    # ------------------------------------------------------------------
    def _invalid(self, error: str, code: str, response_digest: str) -> ValidationResult:
        return ValidationResult(
            ok=False,
            state=AIServiceState.INVALID_RESPONSE,
            error=error,
            error_code=code,
            response_digest=response_digest,
        )

    def _parse_json(self, text: str) -> Any:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"```[a-zA-Z]*", "", cleaned).strip("`").strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = cleaned[start:end + 1]
                try:
                    return json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    return None
            return None

    @staticmethod
    def _coerce_str_list(value: Any) -> list[str] | None:
        if value is None:
            return []
        if not isinstance(value, list):
            return None
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            out.append(item.strip())
        return out

    def _contains_forbidden(self, text: str) -> bool:
        lowered = text.lower()
        return any(term.lower() in lowered for term in self._cfg.forbidden_result_terms)

    def _contains_forbidden_in(self, values: list[Any]) -> bool:
        return any(self._contains_forbidden(s) for s in self._strings(values))

    @staticmethod
    def _strings(values: Any) -> list[str]:
        out: list[str] = []
        if isinstance(values, str):
            out.append(values)
        elif isinstance(values, dict):
            for v in values.values():
                out.extend(ResponseValidator._strings(v))
        elif isinstance(values, (list, tuple)):
            for v in values:
                out.extend(ResponseValidator._strings(v))
        return out

    def _leaks_in(self, values: list[Any]) -> bool:
        return any(self._leaks(s) for s in self._strings(values))

    def _leaks(self, text: str) -> bool:
        scan = _ENDPOINT_ONLY.sub("", text)
        return bool(
            _GOOGLE_KEY.search(scan)
            or _CREDENTIAL.search(scan)
            or _ABS_WINDOWS.search(scan)
            or _ABS_POSIX.search(scan)
        )

    @staticmethod
    def _metric_universe(packet: dict[str, Any]) -> set[str]:
        allowed: set[str] = {"PHYSICAL_TRUTH_AVAILABLE", "PHYSICAL_ACCURACY"}
        for key in ("m2", "m3", "m4", "m5", "m6", "m7", "m8"):
            entry = packet.get(key)
            if not isinstance(entry, dict):
                continue
            for metric in entry.get("metrics", []):
                if isinstance(metric, dict) and isinstance(metric.get("metric_id"), str):
                    allowed.add(metric["metric_id"])
        return allowed


__all__ = ["ResponseValidator", "ValidationResult", "raw_digest"]