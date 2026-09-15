"""Shared FastAPI dependencies."""

from __future__ import annotations

from ..config import Settings
from ..state import AppState, get_state as _get_state


def dep_get_state() -> AppState:
    return _get_state()


def get_settings() -> Settings:
    return _get_state().settings