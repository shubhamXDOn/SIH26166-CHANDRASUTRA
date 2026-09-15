"""Shared pytest fixtures.

Adds the repository root to sys.path so that both packaging styles
(``backend`` package import and root-level modules) resolve consistently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_settings import BaseSettings

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402


@pytest.fixture()
def settings_factory(tmp_path):
    """Return a factory producing isolated Settings (temp data root, env override)."""

    def make(**overrides):
        overrides.setdefault("data_root", str(tmp_path / "data"))
        return Settings(**overrides, _env_file=None)

    return make


@pytest.fixture()
def client_factory(tmp_path):
    """Return a factory building an app+client with isolated settings."""

    def make(**overrides):
        overrides.setdefault("data_root", str(tmp_path / "data"))
        settings = Settings(**overrides, _env_file=None)
        app = create_app(settings=settings)
        return TestClient(app)

    return make