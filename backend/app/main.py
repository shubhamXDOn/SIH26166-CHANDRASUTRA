"""SIH26166 FastAPI application factory.

Startup contract (M0):
    * application starts even when AUTH_SECRET_KEY / GEMINI_API_KEY are unset
    * configuration failures are reported loudly and precisely
    * no raw scientific data is loaded at startup; nothing blocks startup
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import api_router
from .config import BASE_DIR, Settings, load_pipeline_config
from .data import ensure_derived_directories
from .errors import install_error_handlers
from .logging_conf import get_logger, setup_logging
from .state import create_state

logger = get_logger(__name__)


def create_app(settings: Settings | None = None, *, config_file: Path | None = None) -> FastAPI:
    """Build and configure the FastAPI application."""

    load_pipeline_config(config_file)  # raises AppConfigError if broken -> fails fast

    if settings is None:
        settings = Settings()
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
        title=f"{settings.app_name} — Trustworthy lunar image correspondence & registration",
        version=settings.app_version,
        description=(
            "Adaptive-reliability platform for heterogeneous lunar imagery. "
            "M0 foundation build — scientific pipeline milestones begin at M1."
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

    install_error_handlers(app)
    app.include_router(api_router)

    return app


app = create_app()