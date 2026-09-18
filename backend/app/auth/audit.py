"""M10 security audit stream.

An append-only JSON-lines file under ``<data_root>/auth/audit/security_audit.jsonl``
kept separate from the M9 AI audit. It records identity and *what* happened,
never ``password``, ``password_hash``, access/refresh tokens, the Authorization
header, the Gemini API key, or full request bodies. A single security event may
carry the same ``request_id`` as a matching M9 AI audit record.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from ..config import Settings, rfc3339_now
from ..logging_conf import get_logger
from ..security import redact_text

logger = get_logger(__name__)

SECURITY_AUDIT_EVENTS = {
    "REGISTER",
    "LOGIN_SUCCESS",
    "LOGIN_FAILURE",
    "LOGOUT",
    "TOKEN_REFRESH",
    "TOKEN_REVOKED",
    "PASSWORD_CHANGE",
    "ROLE_CHANGE",
    "ACCOUNT_DISABLED",
    "ACCOUNT_ENABLED",
    "PROTECTED_ACCESS_DENIED",
    "ADMIN_ACTION",
    "BOOTSTRAP_ADMIN",
}

_FORBIDDEN_KEYS = (
    "password",
    "password_hash",
    "access_token",
    "refresh_token",
    "authorization",
    "x-goog-api-key",
    "gemini_api_key",
    "jwt_secret",
    "auth_secret_key",
)


def _scrub(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Drop any field that could carry credential material; redact strings."""
    if not metadata:
        return {}
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        low = str(key).lower()
        if any(token in low for token in _FORBIDDEN_KEYS):
            continue
        if isinstance(value, str):
            out[key] = redact_text(value)
        elif isinstance(value, dict):
            out[key] = _scrub(value)
        else:
            out[key] = value
    return out


class SecurityAudit:
    def __init__(self, settings: Settings, *, subdir: str = "auth/audit"):
        self._path = settings.data_root_path / Path(subdir) / "security_audit.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def record(
        self,
        *,
        event_type: str,
        success: bool,
        endpoint: str,
        request_id: str | None = None,
        user_id: str | None = None,
        username: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        event = event_type.upper()
        if event not in SECURITY_AUDIT_EVENTS:
            event = "ADMIN_ACTION"
        entry: dict[str, Any] = {
            "event_id": f"SE-{uuid.uuid4().hex[:16]}",
            "timestamp": rfc3339_now(),
            "user_id": user_id,
            "username": username,
            "event_type": event,
            "success": bool(success),
            "endpoint": endpoint,
            "request_id": request_id,
            "metadata": _scrub(metadata),
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        except OSError:
            logger.warning("Could not write security audit record.", extra={"operation": "security.audit", "status": "failed"})
        return entry["event_id"]

    def read_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        lines: list[dict[str, Any]] = []
        try:
            with open(self._path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        lines.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            return lines
        return lines[-limit:]


__all__ = ["SecurityAudit", "SECURITY_AUDIT_EVENTS"]