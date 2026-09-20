"""SIH26166 FastAPI application factory.

Startup contract:
    * application starts even when AUTH_SECRET_KEY / GEMINI_API_KEY are unset
    * configuration failures are reported loudly and precisely
    * no raw scientific data is loaded at startup; nothing blocks startup
    * M10 — when AUTH_SECRET_KEY is set, persistent users, sessions and
      role-based authorization are live; protected endpoints then require a
      valid bearer access token and enforce the viewer/analyst/admin matrix.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import BASE_DIR, Settings, load_pipeline_config, validate_runtime_config
from .data import ensure_derived_directories
from .errors import install_error_handlers
from .logging_conf import get_logger, setup_logging
from .middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from .state import create_state

logger = get_logger(__name__)


def create_app(settings: Settings | None = None, *, config_file: Path | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""

    load_pipeline_config(config_file)  # raises AppConfigError if broken -> fails fast

    if settings is None:
        settings = Settings()
    validate_runtime_config(settings)  # fails fast on unsafe production/demo config
    create_state(settings)
    setup_logging(level=settings.log_level, log_dir=BASE_DIR / "logs")
    ensure_derived_directories(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        ensure_derived_directories(settings)
        logger.info(
            "%s v%s started (env=%s, debug=%s)",
            settings.app_name,
            settings.app_version,
            settings.app_env,
            settings.app_debug,
            extra={"operation": "startup", "status": "ok"},
        )
        if not settings.auth_configured:
            logger.warning("AUTH_SECRET_KEY is empty — authentication endpoints remain NOT_CONFIGURED.")
        if not settings.gemini_configured:
            logger.warning("GEMINI_API_KEY is empty — AI insights report NOT_CONFIGURED.")
        yield
        logger.info("Application shutting down.", extra={"operation": "shutdown"})

    app = FastAPI(
        title=f"{settings.product_name} — {settings.tagline}",
        version=settings.app_version,
        description=(
            "CHANDRASUTRA (SIH26166) — adaptive-reliability platform for "
            "heterogeneous lunar imagery. M1: real data & metadata — the first "
            "documented OHRC–TMC-2 pair loads, validates and is fully traceable. "
             "M3 matching, M4 Trust Gate, M5 spatial selection, M6 verified "
             "registration, M7 quantitative metrics/reproducible experiment "
             "reports and M8 deep-matcher expansion are implemented. M9 adds a "
             "real, evidence-grounded Gemini copilot that explains recorded "
             "pipeline evidence and never originates scientific truth. M10 adds "
             "full authentication and authorization: persistent users, secure "
             "registration/login, short-lived access tokens with rotating refresh "
             "sessions, and server-side viewer/analyst/admin role enforcement with "
             "a security audit trail."
        ),
        docs_url="/api/docs" if settings.app_debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.http_max_body_bytes)
    app.add_middleware(RequestContextMiddleware, header=settings.request_id_header)

    install_error_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()