"""API error envelope + exception foundation.

All backend errors surface to the frontend through one consistent shape:

    {
      "error": {
        "code": "DATA_SOURCE_UNAVAILABLE",   # stable machine-readable code
        "message": "...",                     # concise technical message
        "user_message": "...",                # human-oriented explanation
        "severity": "error",                  # info | warning | error
        "retryable": false,
        "details": {...}                      # optional, never stack traces
      }
    }

Raw Python stack traces are never the primary UI experience; they go to logs.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging_conf import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for all application-level, user-reportable errors."""

    code = "APP_ERROR"
    http_status = 400
    user_message = "The request could not be completed."
    retryable = False

    def __init__(self, message: str, *, severity: str = "error", details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.severity = severity
        self.details = details or {}


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404
    user_message = "The requested resource could not be found."


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 422
    user_message = "The provided values are invalid."
    retryable = True


class NotConfiguredError(AppError):
    code = "NOT_CONFIGURED"
    http_status = 501
    user_message = "This capability is not configured yet. It will become available in a later milestone."
    retryable = False


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    http_status = 401
    user_message = "Authentication is required to continue."
    retryable = True


class ForbiddenError(AppError):
    code = "FORBIDDEN"
    http_status = 403
    user_message = "You do not have permission for this action."


class DataSourceUnavailableError(AppError):
    code = "DATA_SOURCE_UNAVAILABLE"
    http_status = 503
    user_message = "Unable to access the configured scientific data source."
    retryable = True


def error_envelope(exc: AppError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": exc.message,
            "user_message": exc.user_message,
            "severity": exc.severity,
            "retryable": exc.retryable,
            "details": exc.details or {},
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    """Register exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        logger.error(
            "AppError %s -> %s", exc.code, exc.message,
            extra={"operation": "error_handler", "status": "failed"},
        )
        return JSONResponse(status_code=exc.http_status, content=error_envelope(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        wrapped = AppError(
            str(exc.detail) if exc.detail else "HTTP error",
            severity="error",
        )
        wrapped.code = f"HTTP_{exc.status_code}"
        wrapped.http_status = exc.status_code
        wrapped.user_message = "The request could not be completed."

        if exc.status_code == 404:
            wrapped.code = "NOT_FOUND"
            wrapped.user_message = "The requested endpoint does not exist."
        elif exc.status_code == 405:
            wrapped.code = "METHOD_NOT_ALLOWED"
            wrapped.user_message = "This method is not allowed for the endpoint."
        elif exc.status_code in (401, 403):
            wrapped.code = "UNAUTHORIZED"
            wrapped.user_message = "Authentication or authorization is required."

        logger.warning("HTTP %s -> %s", exc.status_code, str(exc.detail)[:300])
        return JSONResponse(status_code=wrapped.http_status, content=error_envelope(wrapped))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception: %s", exc)
        wrapped = AppError("An internal error occurred.", severity="error")
        wrapped.code = "INTERNAL_ERROR"
        wrapped.http_status = 500
        wrapped.user_message = "An unexpected internal error occurred. Detailed logs were written server-side."
        return JSONResponse(status_code=500, content=error_envelope(wrapped))