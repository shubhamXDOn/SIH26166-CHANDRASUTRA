"""M11 operational status: readiness + admin overview.

Separates liveness (process alive) from readiness (safe to serve requests).
Readiness inspects only safe operational dependencies and reports honest
states (READY / DEGRADED / NOT_CONFIGURED / BLOCKED / FAILED). Optional
capabilities (Gemini, deep matchers) and unavailable real PRADAN data never
make the whole application unhealthy.

Never exposes secrets, credentials, stack traces or internal absolute paths.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from .config import (
    Settings,
    m1_config,
    m2_config,
    m3_config,
    m4_config,
    m5_config,
    m6_config,
    m7_config,
    m8_config,
    m9_config,
    m10_config,
    rfc3339_now,
)
from .hardening import recent_run_events
from .logging_conf import get_logger
from .pairs import PairRegistry

logger = get_logger(__name__)

SERVICE_IDS = [
    "backend",
    "database",
    "filesystem",
    "configuration",
    "authentication",
    "ai_capability",
    "deep_matcher",
    "scientific_data",
]

# Hard dependencies: when one of these is FAILED the service is NOT_READY.
_HARD_SERVICES = {"backend", "filesystem", "configuration", "database"}


def _config_status(settings: Settings) -> dict[str, Any]:
    del settings
    present = {
        "m1": bool(m1_config()), "m2": bool(m2_config()), "m3": bool(m3_config()),
        "m4": bool(m4_config()), "m5": bool(m5_config()), "m6": bool(m6_config()),
        "m7": bool(m7_config()), "m8": bool(m8_config()), "m9": bool(m9_config()),
        "m10": bool(m10_config()),
    }
    if all(present.values()):
        return {"state": "READY", "detail": "All M1–M10 pipeline configurations loaded."}
    missing = [k for k, v in present.items() if not v]
    return {
        "state": "FAILED",
        "detail": "Missing configuration sections: " + ", ".join(missing) + ".",
    }


def _filesystem_status(settings: Settings) -> dict[str, Any]:
    root = settings.data_root_path
    if not root.is_dir():
        return {"state": "FAILED", "detail": "Data root directory does not exist."}
    probe = root / f".fs-probe-{uuid.uuid4().hex[:10]}"
    try:
        probe.write_text("probe")
        probe.unlink()
    except OSError as exc:
        return {"state": "FAILED", "detail": f"Data root is not writable: {exc.__class__.__name__}."}
    return {"state": "READY", "detail": "Data root is present and writable."}


def _database_status(settings: Settings) -> dict[str, Any]:
    if not settings.auth_configured:
        return {"state": "NOT_CONFIGURED", "detail": "Authentication is not configured; no auth database in use."}
    path = settings.auth_db_file
    if not path.is_file():
        return {"state": "FAILED", "detail": "Auth database file does not exist though auth is configured."}
    try:
        import sqlite3

        conn = sqlite3.connect(str(path), timeout=2)
        try:
            conn.execute("SELECT COUNT(*) FROM users").fetchone()
            conn.execute("SELECT COUNT(*) FROM refresh_sessions").fetchone()
            return {"state": "READY", "detail": "Auth database reachable."}
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        return {"state": "FAILED", "detail": f"Auth database unreachable: {exc.__class__.__name__}."}


def _authentication_status(settings: Settings) -> dict[str, Any]:
    if not settings.auth_configured:
        return {"state": "NOT_CONFIGURED", "detail": "AUTH_SECRET_KEY empty — protected routes fail closed with 501."}
    db = _database_status(settings)
    if db["state"] != "READY":
        return {"state": "FAILED", "detail": "Authentication configured but its database is unavailable."}
    return {"state": "READY", "detail": "Authentication configured and operational."}


def _ai_status(settings: Settings) -> dict[str, Any]:
    from .state import get_state

    if not settings.gemini_configured:
        return {"state": "NOT_CONFIGURED", "detail": "GEMINI_API_KEY empty — AI copilot reports NOT_CONFIGURED."}
    try:
        status = get_state().assistant.status_dict()
    except Exception as exc:  # noqa: BLE001
        return {"state": "FAILED", "detail": f"AI service state unavailable: {exc.__class__.__name__}."}
    available = bool(status.get("available"))
    return {
        "state": "READY" if available else "DEGRADED",
        "detail": "Gemini configured." if available else "Gemini configured but not currently available.",
    }


def _deep_matcher_status(settings: Settings) -> dict[str, Any]:
    from .matching.m8 import capabilities as m8cap

    try:
        entries = m8cap.capabilities_public()
    except Exception as exc:  # noqa: BLE001
        return {"state": "FAILED", "detail": f"Deep matcher capability probe failed: {exc.__class__.__name__}."}
    classical = [e for e in entries if e.get("class") == "classical" and e.get("available")]
    deep = [e for e in entries if e.get("class") == "deep" and e.get("available")]
    if deep:
        return {"state": "READY", "detail": f"{len(deep)} deep matcher(s) available."}
    if classical:
        return {"state": "DEGRADED", "detail": f"Only classical matchers available ({len(classical)}); deep matchers unavailable."}
    return {"state": "UNAVAILABLE", "detail": "No matcher available (weights/device/dependencies)."}


def _scientific_data_status(settings: Settings) -> dict[str, Any]:
    try:
        pairs = PairRegistry(settings).list()
    except Exception as exc:  # noqa: BLE001
        return {"state": "FAILED", "detail": f"Pair registry unreadable: {exc.__class__.__name__}."}
    fixture = 0
    real = 0
    for p in pairs:
        ids = f"{getattr(p, 'image_a_product_id', '')} {getattr(p, 'image_b_product_id', '')}"
        if "fixture" in ids.lower():
            fixture += 1
        else:
            real += 1
    if real:
        return {"state": "READY", "detail": f"{real} real pair(s) registered."}
    if fixture:
        return {"state": "BLOCKED", "detail": f"REAL_DATA_UNAVAILABLE — only {fixture} synthetic TEST FIXTURE pair(s) registered; real PRADAN data is not available."}
    return {"state": "BLOCKED", "detail": "REAL_DATA_UNAVAILABLE — no pair registered yet."}


def dependency_status(settings: Settings) -> list[dict[str, Any]]:
    checks: dict[str, Any] = {
        "backend": {"state": "READY", "detail": "Process is alive."},
        "database": _database_status(settings),
        "filesystem": _filesystem_status(settings),
        "configuration": _config_status(settings),
        "authentication": _authentication_status(settings),
        "ai_capability": _ai_status(settings),
        "deep_matcher": _deep_matcher_status(settings),
        "scientific_data": _scientific_data_status(settings),
    }
    return [{"id": did, "name": _SERVICE_EN[did], **(checks[did])} for did in SERVICE_IDS]


_SERVICE_EN = {
    "backend": "Backend application",
    "database": "Database",
    "filesystem": "Filesystem",
    "configuration": "Configuration",
    "authentication": "Authentication",
    "ai_capability": "AI capability",
    "deep_matcher": "Deep matcher",
    "scientific_data": "Scientific data",
}


def _ready_state(services: list[dict[str, Any]]) -> tuple[str, bool]:
    """Overall readiness. Core failures -> NOT_READY (503); otherwise READY or DEGRADED."""
    hard_failed = [s["id"] for s in services if s["id"] in _HARD_SERVICES and s["state"] == "FAILED"]
    blocked_optional = [s["id"] for s in services if s["id"] not in _HARD_SERVICES and s["state"] in ("FAILED", "BLOCKED", "UNAVAILABLE")]
    if hard_failed:
        return "NOT_READY", False
    if blocked_optional:
        return "DEGRADED", True
    return "READY", True


def readiness_payload(settings: Settings) -> tuple[int, dict[str, Any]]:
    services = dependency_status(settings)
    state, ok = _ready_state(services)
    return (200 if ok else 503, {
        "ready": ok,
        "status": state,
        "timestamp": rfc3339_now(),
        "services": services,
        "note": (
            "Readiness reflects operational dependencies. Optional capabilities "
            "(AI, deep matcher) and real-data availability (BLOCKED while PRADAN "
            "access is pending) do not make the service unhealthy."
        ),
    })


def ops_overview(settings: Settings) -> dict[str, Any]:
    """Compact admin-only operational view (no scientific result claims)."""
    from .auth.audit import SecurityAudit
    from .auth.config import load_auth_config
    from .hardening import current_request_id
    from .state import get_state

    services = dependency_status(settings)
    state, _ok = _ready_state(services)

    auth = {"configured": settings.auth_configured}
    if settings.auth_configured:
        try:
            service = get_state().auth
            users = service.list_users()
            sessions = sum(len(u.get("sessions", [])) for u in users) if users else 0
            auth.update({
                "users": len(users),
                "active_sessions": sessions,
                "configuration_id": load_auth_config(settings).configuration_id,
            })
        except Exception as exc:  # noqa: BLE001
            auth.update({"error": f"{exc.__class__.__name__}"})

    failures: list[dict[str, Any]] = []
    try:
        audit = SecurityAudit(settings).read_recent(limit=200)
        failures = [
            {
                "timestamp": e.get("timestamp", ""),
                "event_type": e.get("event_type", ""),
                "endpoint": e.get("endpoint", ""),
                "request_id": e.get("request_id", ""),
            }
            for e in audit
            if not e.get("success", True) or e.get("event_type") in ("LOGIN_FAILURE", "PROTECTED_ACCESS_DENIED", "TOKEN_REVOKED")
        ][-20:]
    except Exception as exc:  # noqa: BLE001
        failures = [{"event_type": "AUDIT_READ_FAILED", "endpoint": "", "request_id": "",
                     "timestamp": rfc3339_now(), "detail": f"{exc.__class__.__name__}"}]

    return {
        "system": {
            "ready": state in ("READY", "DEGRADED"),
            "status": state,
            "environment": settings.app_env,
            "debug": settings.app_debug,
            "demo_mode": settings.demo_mode,
            "milestone": settings.milestone,
            "version": settings.app_version,
            "timestamp": rfc3339_now(),
            "request_id": current_request_id(),
        },
        "services": services,
        "authentication": auth,
        "recent_failures": failures,
        "recent_runs": recent_run_events(limit=20),
    }


__all__ = ["dependency_status", "readiness_payload", "ops_overview", "SERVICE_IDS"]