"""Holds the lazily-initialized application singletons.

Kept separate from ``config`` to avoid import cycles:
    config -> (nothing)
    state  -> config, security, ai
    api    -> state, config
"""

from __future__ import annotations

from . import ai, security
from .config import Settings


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.guard = security.configure_auth_guard(settings)
        self.assistant = ai.build_assistant(settings)


app_state: AppState | None = None


def create_state(settings: Settings) -> AppState:
    global app_state
    app_state = AppState(settings)
    return app_state


def get_state() -> AppState:
    if app_state is None:
        raise RuntimeError("Application state not initialised; call create_state on startup.")
    return app_state