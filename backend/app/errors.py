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


def _logger():
    # Imported lazily to avoid a module-level cycle:
    # security -> errors -> logging_conf -> security.
    from .logging_conf import get_logger

    return get_logger(__name__)


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


class AIRateLimitedError(AppError):
    code = "AI_RATE_LIMITED"
    http_status = 429
    user_message = "The AI provider is rate-limiting requests. Please retry shortly."
    retryable = True


class AIProviderError(AppError):
    code = "AI_PROVIDER_ERROR"
    http_status = 502
    user_message = "The AI provider could not complete the request. No result was fabricated."
    retryable = True


class AITimeoutError(AppError):
    code = "AI_TIMEOUT"
    http_status = 504
    user_message = "The AI provider did not respond in time. The deterministic pipeline is unaffected."
    retryable = True


class AIInvalidResponseError(AppError):
    code = "AI_INVALID_RESPONSE"
    http_status = 502
    user_message = "The AI provider returned a response that failed validation; it was discarded, not shown."
    retryable = False


class AIBlockedError(AppError):
    code = "AI_BLOCKED"
    http_status = 409
    user_message = "This AI request was refused because the requested action would violate the evidence-grounding policy."
    retryable = False


# ---------------------------------------------------------------------------
# M10 authentication & authorization errors (unified envelope, stable codes)
# ---------------------------------------------------------------------------

class AuthenticationError(AppError):
    """Base class for authentication/authorization failures."""

    code = "AUTH_ERROR"
    http_status = 401
    user_message = "Authentication failed."


class AuthNotConfiguredError(AuthenticationError):
    code = "AUTH_NOT_CONFIGURED"
    http_status = 501
    user_message = "Authentication is not configured (AUTH_SECRET_KEY is empty)."
    retryable = False


class AuthRequiredError(AuthenticationError):
    code = "AUTH_REQUIRED"
    http_status = 401
    user_message = "Authentication is required to continue."


class InvalidCredentialsError(AuthenticationError):
    code = "INVALID_CREDENTIALS"
    http_status = 401
    user_message = "Invalid username or password."
    retryable = True


class TokenInvalidError(AuthenticationError):
    code = "TOKEN_INVALID"
    http_status = 401
    user_message = "The access token is invalid or malformed."


class TokenExpiredError(AuthenticationError):
    code = "TOKEN_EXPIRED"
    http_status = 401
    user_message = "The session has expired; please sign in again."
    retryable = True


class SessionRevokedError(AuthenticationError):
    code = "SESSION_REVOKED"
    http_status = 401
    user_message = "The session has been revoked; please sign in again."


class ForbiddenRoleError(AuthenticationError):
    code = "FORBIDDEN"
    http_status = 403
    user_message = "You do not have permission for this action."


class RoleRequiredError(AuthenticationError):
    code = "ROLE_REQUIRED"
    http_status = 403
    user_message = "Your account does not have the required role for this action."


class AccountDisabledError(AuthenticationError):
    code = "ACCOUNT_DISABLED"
    http_status = 403
    user_message = "This account is disabled. Contact an administrator."


class AuthRateLimitedError(AuthenticationError):
    code = "RATE_LIMITED"
    http_status = 429
    user_message = "Too many attempts. Please wait before trying again."
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
        _logger().error(
            "AppError %s -> %s", exc.code, exc.message,
            extra={"operation": "error_handler", "status": "failed"},
        )
        return JSONResponse(status_code=exc.http_status, content=error_envelope(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        logger = _logger()
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
        _logger().exception("Unhandled exception: %s", exc)
        wrapped = AppError("An internal error occurred.", severity="error")
        wrapped.code = "INTERNAL_ERROR"
        wrapped.http_status = 500
        wrapped.user_message = "An unexpected internal error occurred. Detailed logs were written server-side."
        return JSONResponse(status_code=500, content=error_envelope(wrapped))