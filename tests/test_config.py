"""Configuration foundation tests."""

from __future__ import annotations

import json

import pytest

from backend.app.config import (
    AppConfigError,
    Settings,
    load_pipeline_config,
)


def test_settings_load_with_defaults():
    s = Settings(_env_file=None)
    assert s.app_name == "SIH26166"
    assert s.app_env in ("development", "production")
    assert s.data_root_path.name == "data"


def test_settings_read_from_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("BACKEND_PORT", "9999")
    s = Settings(_env_file=None)
    assert s.app_env == "production"
    assert s.backend_port == 9999


def test_cors_origins_parsed_as_list():
    s = Settings(cors_origins="http://a:1, http://b:2", _env_file=None)
    assert s.cors_origin_list == ["http://a:1", "http://b:2"]


def test_pipeline_config_loads_yaml():
    cfg = load_pipeline_config()
    assert cfg.source.replace("\\", "/").endswith("configs/app.yaml")
    ids = [stage["id"] for stage in cfg.pipeline_stages]
    assert ids == ["data", "validate", "preprocess", "match", "trust", "register", "report"]


def test_pipeline_config_missing_file_fails_gracefully(tmp_path):
    with pytest.raises(AppConfigError):
        load_pipeline_config(tmp_path / "nope.yaml")


def test_secrets_not_exposed_in_public_dict():
    s = Settings(auth_secret_key="hunter2", gemini_api_key="AIzAsecret", _env_file=None)
    public = json.dumps(s.public_dict())
    assert "hunter2" not in public
    assert "AIzAsecret" not in public