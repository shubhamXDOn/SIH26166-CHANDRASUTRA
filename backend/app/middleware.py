"""M11 ASGI middleware: request correlation, bounded bodies, access logging.

* ``RequestContextMiddleware`` — bind a stable request ID (accept a sanitized
  inbound ``X-Request-ID`` or generate one), echo it back, and emit one
  structured access log line per request (method, path, status, duration_ms,
  request_id). Never logs secrets; the Authorization header is redacted.
* ``BodySizeLimitMiddleware`` — reject over-limit request bodies with an
  honest ``413 LIMIT_EXCEEDED`` envelope before any pipeline code runs.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Awaitable

from fastapi.responses import JSONResponse

from .config import Settings
from .errors import PayloadTooLargeError, error_envelope
from .hardening import new_request_id, sanitize_request_id, set_request_id
from .logging_conf import get_logger

logger = get_logger(__name__)


class RequestContextMiddleware:
    """Correlate requests, echo request IDs, and write structured access logs."""

    def __init__(self, app, header: str = "x-request-id"):
        self.app = app
        self._header = header.lower()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = sanitize_request_id(dict(scope.get("headers") or {}).get(
            self._header.encode(), b"").decode("utf-8", "ignore")
        )
        if not request_id:
            request_id = new_request_id()
        set_request_id(request_id)

        status_holder = {"status": 0}
        started = time.perf_counter()
        storage = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = message.get("headers", [])
                message["headers"] = list(headers) + [
                    (self._header.encode(), request_id.encode())
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if scope.get("method") and not scope.get("_m11_flushed", False):
                scope["_m11_flushed"] = True
                route = ""
                route_obj = scope.get("route")
                if route_obj is not None:
                    route = getattr(route_obj, "path", "") or ""
                logger.info(
                    "http %s %s status=%s duration_ms=%.1f req=%s",
                    (scope.get("method") or "").upper(),
                    route or scope.get("path", ""),
                    status_holder["status"] or "?",
                    (time.perf_counter() - started) * 1000.0,
                    request_id,
                )
            _reset_request_id(request_id)

        _ = storage


def _reset_request_id(request_id: str) -> None:
    from .hardening import current_request_id

    if current_request_id() == request_id:
        set_request_id("")  # context dies with the request task anyway


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ``max_bytes``.

    Enforces the declared Content-Length up-front and guards chunked bodies by
    wrapping ``receive``. Over-limit requests receive ``413 LIMIT_EXCEEDED``
    with the unified error envelope — never a raw traceback.
    """

    def __init__(self, app, max_bytes: int | None = None):
        self.app = app
        self._max_bytes = max_bytes if max_bytes and max_bytes > 0 else 8_000_000

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers") or []}
        content_length = headers.get("content-length")
        try:
            declared = int(content_length) if content_length else 0
        except (TypeError, ValueError):
            declared = 0
        if declared > self._max_bytes:
            response = JSONResponse(
                status_code=PayloadTooLargeError.http_status,
                content=error_envelope(PayloadTooLargeError(
                    f"Request body of {declared} bytes exceeds the maximum of {self._max_bytes}.",
                )),
            )
            await response(scope, receive, send)
            return

        received = 0
        over = False

        async def receive_wrapper():
            nonlocal received, over
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._max_bytes:
                    over = True
                    raise PayloadTooLargeError(
                        f"Request body exceeds the maximum of {self._max_bytes} bytes.",
                    )
            return message

        try:
            await self.app(scope, receive_wrapper, send)
        except PayloadTooLargeError as exc:
            response = JSONResponse(
                status_code=exc.http_status,
                content=error_envelope(exc),
            )
            try:
                await response(scope, receive, send)
            except Exception:  # noqa: BLE001 — the client may already be gone
                pass


__all__ = ["RequestContextMiddleware", "BodySizeLimitMiddleware"]