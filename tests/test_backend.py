"""Application import + backend API behaviour tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

import backend.app.main as main_mod


def test_application_imports():
    assert main_mod.app is not None
    assert main_mod.app.title.startswith("CHANDRASUTRA")


def test_root_routes_registered():
    """Key routes are reachable and correctly namespaced under /api."""
    assert main_mod.app.url_path_for("health").endswith("/api/health")
    assert main_mod.app.url_path_for("meta").endswith("/api/meta")
    assert main_mod.app.url_path_for("login").endswith("/api/auth/login")
    assert main_mod.app.url_path_for("auth_status").endswith("/api/auth/status")
    assert main_mod.app.url_path_for("data_status").endswith("/api/data/status")
    assert main_mod.app.url_path_for("ai_status").endswith("/api/ai/status")


def test_health_endpoint(client_factory):
    with client_factory(data_root="") as client:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["application"] == "CHANDRASUTRA"
        assert body["project"] == "SIH26166"
        assert body["milestone"] == "M1"
        assert "version" in body
        assert "environment" in body
        assert "timestamp" in body
        assert "auth" in body and "configured" in body["auth"]
        assert "ai" in body and "configured" in body["ai"]


def test_unknown_route_returns_envelope(client_factory):
    with client_factory() as client:
        resp = client.get("/api/does-not-exist")
        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "NOT_FOUND"
        assert body["error"]["user_message"]


def test_meta_does_not_leak_secrets(client_factory):
    with client_factory(auth_secret_key="super-secret-value") as client:
        resp = client.get("/api/meta")
        assert resp.status_code == 200
        text = resp.text
        assert "super-secret-value" not in text
        assert "gemini_api_key" not in resp.json()["settings"]


def test_data_status_reports_no_pairs(client_factory):
    with client_factory() as client:
        resp = client.get("/api/data/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["pairs_registered"] == 0
        assert body["milestone"] == "M1"
        assert body["summary"]["total"] >= 4
        assert "directories" in body
        assert body["source"]["archive"] == "PRADAN"


def test_ai_status_not_configured_without_key(client_factory):
    with client_factory(gemini_api_key="") as client:
        resp = client.get("/api/ai/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "NOT_CONFIGURED"


def test_ai_explain_reports_not_configured(client_factory):
    with client_factory(gemini_api_key="") as client:
        resp = client.post("/api/ai/explain")
        assert resp.status_code == 501
        assert resp.json()["error"]["code"] == "NOT_CONFIGURED"


def test_auth_login_returns_not_configured(client_factory):
    with client_factory(auth_secret_key="") as client:
        resp = client.post("/api/auth/login", json={"username": "a", "password": "b"})
        assert resp.status_code == 501
        assert resp.json()["error"]["code"] == "NOT_CONFIGURED"


def test_auth_status_reports_configuration(client_factory):
    with client_factory(auth_secret_key="") as client:
        resp = client.get("/api/auth/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert body["policy"]["no_plaintext_passwords"] is True
        assert "analyst" in body["roles"]


def test_app_starts_without_env_file_from_clean_state():
    """The factory must be constructible with zero environment secrets."""
    from backend.app.main import create_app
    from backend.app.config import Settings

    app = create_app(settings=Settings(_env_file=None))
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200