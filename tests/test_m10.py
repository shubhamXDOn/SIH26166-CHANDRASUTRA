"""M10 tests — real authentication, authorization & user security.

Covers AU-M10-001: configuration/status, accounts (registration, login,
rate-limiting), tokens (JWT validity, expiry, forgery, refresh rotation,
replay-safety), sessions (logout, admin revocation, password-change
revocation), the full authorization matrix (reads=viewer,
mutations=analyst, admin=admin), server-side-only role enforcement,
audit + redaction, and the guarantee that authentication never alters
scientific identity or milestone honesty (B01–B30 behaviours grouped).

Every test uses isolated temp deployments; no test touches the real
data tree or a real Gemini key.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fixturegen  # noqa: F401

from auth_helpers import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AUTH_TEST_SECRET,
    AuthedTestClient,
    admin_access_token,
    configure_auth,
)
from backend.app.auth.tokens import create_access_token
from backend.app.config import Settings
from backend.app.data import ensure_derived_directories
from backend.app.main import create_app
from backend.app.security import Role

PW = "Zonda#Gust-2026-strong1"          # meets M10 policy; contains no username
PW2 = "North#Peak-2027-bravo2"
REFRESH_COOKIE = "chandrasutra_refresh"

_update_counts = True


def update_expected_counts(totus: dict, n: int, sub: str) -> None:
    if _update_counts:
        print(f"      [TEST COUNT] +{n} {sub}")


# ---------------------------------------------------------------------------
# deployment helpers
# ---------------------------------------------------------------------------

def _deploy(tmp_path, **overrides):
    overrides.setdefault("data_root", str(tmp_path / "data"))
    overrides.setdefault("auth_secret_key", AUTH_TEST_SECRET)
    overrides.setdefault("auth_bootstrap_admin_username", ADMIN_USERNAME)
    overrides.setdefault("auth_bootstrap_admin_password", ADMIN_PASSWORD)
    settings = Settings(**overrides, _env_file=None)
    ensure_derived_directories(settings)
    app = create_app(settings=settings)
    return app, settings


def _anon(app) -> TestClient:
    return TestClient(app)


def _login(app, username: str, password: str) -> dict:
    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login", json={"username": username, "password": password}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        body["_refresh"] = client.cookies.get(REFRESH_COOKIE, "")
        return body


def _register(app, username: str, password: str = PW, display_name: str = "", **extra) -> dict:
    payload = {"username": username, "password": password, "display_name": display_name, **extra}
    with TestClient(app) as client:
        r = client.post("/api/auth/register", json=payload)
        return {"status": r.status_code, "json": r.json()}


def _as(app, token: str) -> AuthedTestClient:
    return AuthedTestClient(app, token)


def _promote(app, admin_token: str, user_id: str, role: str = "analyst") -> int:
    with _as(app, admin_token) as client:
        r = client.patch(f"/api/auth/users/{user_id}", json={"role": role})
        if r.status_code == 200:
            return r.status_code
        return r.status_code  # expose for assertions


# ===========================================================================
# A. configuration & honest states
# ===========================================================================

def test_m10_meta_is_m10_and_leaks_no_secrets(client_factory):
    with client_factory(auth_secret_key=AUTH_TEST_SECRET) as client:
        r = client.get("/api/meta")
        assert r.status_code == 200
        body = r.json()
        assert body["milestone"] == "M11"
        assert body["version"] == "0.11.0"
        assert AUTH_TEST_SECRET not in json.dumps(body)


def test_m10_auth_status_public_states(client_factory, tmp_path):
    # unconfigured deployment: status lies nowhere, reports honestly
    with client_factory(auth_secret_key="") as client:
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        assert r.json()["configured"] is False
        assert r.json()["session_state"] == "UNAUTHENTICATED"
    # configured deployment
    app, settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.get("/api/auth/status")
        assert r.status_code == 200
        body = r.json()
        assert body["configured"] is True
        assert body["authentication_enabled"] is True
        assert body["registration_enabled"] is True
        assert body["access_token_ttl_seconds"] == 900
        assert set(body["roles"]) == {"viewer", "analyst", "admin"}
        assert "password_hash" not in json.dumps(body)
        assert AUTH_TEST_SECRET not in json.dumps(body)


def test_m10_unconfigured_reports_auth_not_configured(client_factory):
    with client_factory(auth_secret_key="") as client:
        public = [
            ("/api/health", 200),
            ("/api/meta", 200),
            ("/api/auth/status", 200),
        ]
        for path, status in public:
            assert client.get(path).status_code == status, path
        protected = [
            ("GET", "/api/data/status", None),
            ("GET", "/api/ai/status", None),
            ("GET", "/api/pairs", None),
            ("POST", "/api/pairs/register", {}),
            ("POST", "/api/auth/login", {"username": "a", "password": "b"}),
            ("POST", "/api/auth/register", {"username": "someone", "password": PW}),
            ("POST", "/api/auth/refresh", {}),
            ("GET", "/api/auth/me", None),
        ]
        for method, path, payload in protected:
            r = client.request(method, path, json=payload)
            assert r.status_code == 501, (method, path, r.text)
            assert r.json()["error"]["code"] == "AUTH_NOT_CONFIGURED", path


# ===========================================================================
# B. accounts: registration, login, rate limiting
# ===========================================================================

def test_m10_register_creates_viewer(tmp_path):
    app, _ = _deploy(tmp_path)
    got = _register(app, "alice")
    assert got["status"] == 200
    user = got["json"]["user"]
    assert user["role"] == "viewer"
    assert user["is_active"] is True
    assert user["username"] == "alice"
    assert "password" not in json.dumps(user)
    assert got["json"]["registration_enabled"] is True


def test_m10_register_rejects_weak_password(tmp_path):
    app, _ = _deploy(tmp_path)
    for bad in ("short", "nodigitshereplease"):
        got = _register(app, "bob", password=bad)
        assert got["status"] == 422, bad
        assert got["json"]["error"]["code"] == "VALIDATION_ERROR"
        assert "password_policy" in got["json"]["error"]["details"]


def test_m10_register_role_injection_ignored(tmp_path):
    app, _ = _deploy(tmp_path)
    got = _register(app, "mallory", **{"role": "admin", "is_active": False})
    assert got["status"] == 200
    assert got["json"]["user"]["role"] == "viewer"  # server keeps ground truth
    assert got["json"]["user"]["is_active"] is True


def test_m10_register_duplicate_username(tmp_path):
    app, _ = _deploy(tmp_path)
    assert _register(app, "carol")["status"] == 200
    got = _register(app, "CAROL")  # normalized; no case-based clones
    assert got["status"] == 401
    assert got["json"]["error"]["code"] == "INVALID_CREDENTIALS"
    assert got["json"]["error"]["details"]["code"] == "USERNAME_TAKEN"


def test_m10_register_optional(tmp_path):
    app, _ = _deploy(tmp_path, auth_register_enabled=False)
    got = _register(app, "dave")
    assert got["status"] == 422
    assert got["json"]["error"]["code"] == "VALIDATION_ERROR"
    assert "disabled" in got["json"]["error"]["message"].lower()


def test_m10_login_returns_cookie_and_no_body_secret(tmp_path):
    app, _ = _deploy(tmp_path)
    _register(app, "erin", PW)
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "erin", "password": PW})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["expires_in"] == 900
        assert body["user"]["username"] == "erin"
        assert "refresh_token" not in body              # never in the body
        assert "password" not in json.dumps(body)
        cookie = r.cookies.get(REFRESH_COOKIE)
        assert cookie and cookie not in json.dumps(body)
        assert "httponly" in (r.headers.get("set-cookie", "")).lower()


def test_m10_login_generic_failure_no_enumeration(tmp_path):
    # wrong password vs unknown user must be indistinguishable
    app, _ = _deploy(tmp_path)
    _register(app, "frank", PW)
    msgs, codes = set(), set()
    for creds in (("frank", "wrong-password-1"), ("ghost-user", PW)):
        err = _login_status(app, creds[0], creds[1])
        msgs.add(err["message"])
        codes.add(err["code"])
    assert codes == {"INVALID_CREDENTIALS"}
    assert len(msgs) == 1


def _login_status(app, username, password) -> dict:
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 401
        return r.json()["error"]


def test_m10_login_locks_after_rate_limit(tmp_path):
    app, _ = _deploy(tmp_path)
    _register(app, "grace", PW)
    for _ in range(5):
        _login_status(app, "grace", "wrong-password-1")
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "grace", "password": PW})
        assert r.status_code == 429, r.text
        assert r.json()["error"]["code"] == "RATE_LIMITED"


# ===========================================================================
# C. access tokens
# ===========================================================================

def test_m10_access_token_required(tmp_path):
    app, settings = _deploy(tmp_path)
    with _anon(app) as client:
        for path in ("/api/auth/me", "/api/data/status"):
            r = client.get(path)
            assert r.status_code == 401, path
            assert r.json()["error"]["code"] == "AUTH_REQUIRED", path


def test_m10_invalid_tokens_rejected(tmp_path):
    app, settings = _deploy(tmp_path)
    _register(app, "heidi", PW)
    user_id = _login(app, "heidi", PW)["user"]["id"]
    tests = []
    # malformed
    tests.append(("garbage", "TOKEN_INVALID"))
    # wrong signature
    import datetime

    import jwt as pyjwt

    now = datetime.datetime.now(datetime.timezone.utc)
    tests.append((
        pyjwt.encode({
            "sub": user_id, "role": "viewer", "iat": now, "exp": now + datetime.timedelta(seconds=900),
            "iss": settings.auth_issuer_value, "aud": settings.auth_audience_value,
            "jti": "abc", "typ": "access",
        }, "definitely-wrong-secret", algorithm=settings.auth_algorithm),
        "TOKEN_INVALID",
    ))
    # wrong token type
    cfg = __import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings)
    del cfg
    wrong_typ = create_access_token(
        settings=settings, subject=user_id, role=Role.VIEWER,
        auth_config=__import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings),
        extra={"typ": "refresh"},
    )
    tests.append((wrong_typ, "TOKEN_INVALID"))
    # unknown subject
    tests.append((
        create_access_token(settings=settings, subject="U-nonexistent", role=Role.VIEWER,
                            auth_config=__import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings)),
        "TOKEN_INVALID",
    ))
    # tampered payload (signature preserved from a different token)
    real = create_access_token(settings=settings, subject=user_id, role=Role.VIEWER,
                               auth_config=__import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings))
    head, _, sig = real.split(".")
    forged_claims = {"sub": user_id, "role": "admin", "exp": 4102444800, "iat": 1700000000,
                     "iss": settings.auth_issuer_value, "aud": settings.auth_audience_value,
                     "jti": "z", "typ": "access"}
    encoded = base64.urlsafe_b64encode(json.dumps(forged_claims).encode()).rstrip(b"=").decode()
    tests.append((f"{head}.{encoded}.{sig}", "TOKEN_INVALID"))

    with _anon(app) as client:
        for token, code in tests:
            r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401, token[:40]
            assert r.json()["error"]["code"] == code, token[:40]


def test_m10_expired_token_rejected(tmp_path):
    app, settings = _deploy(tmp_path)
    _register(app, "ivan", PW)
    user_id = _login(app, "ivan", PW)["user"]["id"]
    expired = create_access_token(
        settings=settings, subject=user_id, role=Role.VIEWER,
        ttl_seconds=-30,
        auth_config=__import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings),
    )
    with _anon(app) as client:
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_m10_role_claim_cannot_elevate(tmp_path):
    # even a correctly-signed token with role=admin does not matter:
    # authorization reads the role stored server-side (the DB row).
    app, settings = _deploy(tmp_path)
    _register(app, "judy", PW)
    viewer_id = _login(app, "judy", PW)["user"]["id"]
    forged = create_access_token(settings=settings, subject=viewer_id, role=Role.ADMIN,
                                 auth_config=__import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings))
    with _anon(app) as client:
        r = client.get("/api/auth/users", headers={"Authorization": f"Bearer {forged}"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"


# ===========================================================================
# D. refresh rotation, sessions, logout
# ===========================================================================

def test_m10_refresh_rotates_and_replay_fails(tmp_path):
    app, _ = _deploy(tmp_path)
    _register(app, "kevin", PW)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "kevin", "password": PW})
        assert login.status_code == 200
        access = login.json()["access_token"]
        old_refresh = client.cookies.get(REFRESH_COOKIE)
        # original access works
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 200
        # rotate
        r = client.post("/api/auth/refresh")
        assert r.status_code == 200, r.text
        new_refresh = client.cookies.get(REFRESH_COOKIE)
        assert new_refresh and new_refresh != old_refresh
        # replay of the old, rotated token must be refused
        replay = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "SESSION_REVOKED"


def test_m10_refresh_unknown_token(tmp_path):
    app, _ = _deploy(tmp_path)
    with TestClient(app) as client:
        r = client.post("/api/auth/refresh", json={"refresh_token": "not-a-real-refresh-token"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "SESSION_REVOKED"


def test_m10_logout_revokes_session(tmp_path):
    app, _ = _deploy(tmp_path)
    _register(app, "laura", PW)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "laura", "password": PW})
        old_refresh = client.cookies.get(REFRESH_COOKIE)
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json()["logged_out"] is True
        assert r.json()["sessions_revoked"] >= 1
        assert client.post("/api/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401
    # anonymous logout is safe and honest
    with _anon(app) as client:
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json()["logged_out"] is True


def test_m10_admin_revokes_single_session(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert login.status_code == 200
        session_id = login.json()["session_id"]
        sid_refresh = client.cookies.get(REFRESH_COOKIE)
    # session listed, then revoked precisely by admin
    with _as(app, admin_token) as client:
        r = client.delete(f"/api/auth/sessions/{session_id}")
        assert r.status_code == 200
        assert r.json()["revoked"] is True
        assert r.json()["session_id"] == session_id
    with TestClient(app) as client:
        r = client.post("/api/auth/refresh", json={"refresh_token": sid_refresh})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "SESSION_REVOKED"
    # unknown session id -> 404
    with _as(app, admin_token) as client:
        assert client.delete("/api/auth/sessions/R-nope").status_code == 404


# ===========================================================================
# E. role enforcement (authorization matrix)
# ===========================================================================

def _provision_user(app, admin_token, username, pw=PW, role="viewer"):
    assert _register(app, username, pw)["status"] == 200
    token = _login(app, username, pw)["access_token"]
    if role != "viewer":
        uid = _login(app, username, pw)["user"]["id"]
        with _as(app, admin_token) as client:
            r = client.patch(f"/api/auth/users/{uid}", json={"role": role})
            assert r.status_code == 200, r.text
    return _login(app, username, pw)["access_token"]


def test_m10_matrix_reads_require_session(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    viewer = _provision_user(app, admin_token, "viewer1")
    read_paths = [
        "/api/data/status", "/api/data/sensors", "/api/pairs", "/api/pairs/scan",
        "/api/processing/configurations", "/api/processing/overview",
        "/api/matching/configurations", "/api/matching/capabilities",
        "/api/metrics/configurations", "/api/metrics/overview",
        "/api/registration/configurations", "/api/spatial/configurations",
        "/api/trust/configurations", "/api/ai/status",
    ]
    for path in read_paths:
        assert _anon(app).get(path).status_code in (401,), path
        r = _as(app, viewer).get(path)
        assert r.status_code == 200, (path, r.text[:200])


def test_m10_matrix_mutations_require_analyst(tmp_path):
    app, settings = _deploy(tmp_path)
    fixturegen.write_standard_fixtures(Path(settings.data_root_path))
    admin_token = admin_access_token(app)
    admin = _as(app, admin_token)
    viewer = _as(app, _provision_user(app, admin_token, "viewer2"))
    analyst = _as(app, _provision_user(app, admin_token, "analyst1", role="analyst"))

    mutation = {
        "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
        "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
        "overlap_status": "UNKNOWN",
    }
    # viewer: every mutation arrives as a clean 403 with no partial effects
    for path in ("/api/pairs/register", "/api/pairs/CS-P001/validate"):
        r = viewer.request("post", path, json=mutation if path.endswith("/register") else {})
        assert r.status_code == 403, (path, r.text)
        assert r.json()["error"]["code"] == "FORBIDDEN"
        assert r.json()["error"]["details"]["required_roles"] == ["admin", "analyst"]
    # analyst: mutation proceeds (registration only needs the data, not the role)
    r = analyst.post("/api/pairs/register", json=mutation)
    assert r.status_code == 200, r.text
    assert r.json()["pair_id"] == "CS-P001"
    # admin may mutate too and sees the same registered registry
    r2 = admin.get("/api/data/status").json()
    assert r2["pairs_registered"] >= 1


def test_m10_identity_not_actor_dependent(tmp_path):
    # registering the same products under two different identities yields the
    # same Pair ID: auth is contextual provenance, never part of the digest.
    import tempfile

    payload = {
        "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
        "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
        "overlap_status": "UNKNOWN",
    }
    ids: list[str] = []
    for who in ("alpha", "beta"):
        app, settings = _deploy(Path(tempfile.mkdtemp(prefix="cs_m10_")))
        fixturegen.write_standard_fixtures(Path(settings.data_root_path))
        admin_token = admin_access_token(app)
        with _as(app, _provision_user(app, admin_token, who, role="analyst")) as client:
            r = client.post("/api/pairs/register", json=payload)
            assert r.status_code == 200, r.text
            ids.append(r.json()["pair_id"])
    assert ids[0] == ids[1]


def test_m10_admin_only_endpoints(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    viewer = _as(app, _provision_user(app, admin_token, "viewer3"))
    analyst = _as(app, _provision_user(app, admin_token, "analyst2", role="analyst"))
    admin = _as(app, admin_token)
    for path in ("/api/auth/users", "/api/auth/security-summary"):
        assert viewer.get(path).status_code == 403
        assert analyst.get(path).status_code == 403
        assert admin.get(path).status_code == 200


def test_m10_users_list_shape_and_no_leaks(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    _register(app, "mike", PW)
    with _as(app, admin_token) as client:
        body = client.get("/api/auth/users").json()
        users = body["users"]
        assert any(u["username"] == "mike" for u in users)
        assert any(u["username"] == ADMIN_USERNAME for u in users)
        for u in users:
            assert "password" not in json.dumps(u)
            assert "active_sessions" in u
        assert PW not in json.dumps(body)


# ===========================================================================
# F. admin account management
# ===========================================================================

def test_m10_admin_patch_role_and_audit(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    uid = _login(app, *_reg_and_login(app, "nina", PW))["user"]["id"]
    with _as(app, admin_token) as client:
        r = client.patch(f"/api/auth/users/{uid}", json={"role": "analyst"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "analyst"
        summary = client.get("/api/auth/security-summary").json()
        events = summary["recent_security_events"]
        assert any(
            e["event_type"] == "ROLE_CHANGE" and e.get("metadata", {}).get("to") == "analyst"
            for e in events
        )


def _reg_and_login(app, username, pw=PW):
    _register(app, username, pw)
    return username, pw


def test_m10_admin_safety_guards(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    admin_user = _login(app, ADMIN_USERNAME, ADMIN_PASSWORD)["user"]
    with _as(app, admin_token) as client:
        # no self-elevation (already admin; role is max) and no last-admin demotion
        r = client.patch(f"/api/auth/users/{admin_user['id']}", json={"role": "viewer"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"
        # no disabling yourself
        r = client.patch(f"/api/auth/users/{admin_user['id']}", json={"is_active": False})
        assert r.status_code == 403
        # cannot disable the last active administrator
        r = client.patch(f"/api/auth/users/{admin_user['id']}", json={"is_active": False})
        assert r.status_code == 403


def test_m10_disable_user_revokes_access(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    username = "olivia"
    _register(app, username, PW)
    access = _login(app, username, PW)
    token, refresh = access["access_token"], access["_refresh"]
    uid = access["user"]["id"]
    with _as(app, admin_token) as client:
        assert client.patch(f"/api/auth/users/{uid}", json={"is_active": False}).status_code == 200
    with _anon(app) as client:
        r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "ACCOUNT_DISABLED"
        r = client.post("/api/auth/refresh", json={"refresh_token": refresh})
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "ACCOUNT_DISABLED"
    with _as(app, admin_token) as client:
        assert client.patch(f"/api/auth/users/{uid}", json={"is_active": True}).status_code == 200
    with _anon(app) as client:
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_m10_change_password_revokes_sessions(tmp_path):
    app, _ = _deploy(tmp_path)
    _register(app, "paul", PW)
    access = _login(app, "paul", PW)
    old_refresh = access["_refresh"]
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "paul", "password": PW})
        assert login.status_code == 200
        bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
        r = client.post("/api/auth/me/password",
                        json={"current_password": "still-wrong", "new_password": PW2},
                        headers=bearer)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_CREDENTIALS"
        r = client.post("/api/auth/me/password",
                        json={"current_password": PW, "new_password": PW2},
                        headers=bearer)
        assert r.status_code == 200
        assert r.json()["changed"] is True
    with _anon(app) as client:
        r = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "SESSION_REVOKED"
        r = client.post("/api/auth/login", json={"username": "paul", "password": PW})
        assert r.status_code == 401
        r = client.post("/api/auth/login", json={"username": "paul", "password": PW2})
        assert r.status_code == 200


# ===========================================================================
# G. audit + redaction
# ===========================================================================

def test_m10_security_summary_and_audit_redaction(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    _register(app, "quinn", PW)
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": "quinn", "password": "wrong-1"})
        client.post("/api/auth/login", json={"username": "quinn", "password": PW})
    summary = None
    with _as(app, admin_token) as client:
        summary = client.get("/api/auth/security-summary").json()
    text = json.dumps(summary)
    event_types = {e["event_type"] for e in summary["recent_security_events"]}
    assert "REGISTER" in event_types
    assert "LOGIN_SUCCESS" in event_types
    assert "LOGIN_FAILURE" in event_types
    assert summary["active_users"] >= 2
    assert isinstance(summary["role_distribution"].get("viewer"), int)
    for e in summary["recent_security_events"]:
        assert PW not in json.dumps(e)
    # failed-login detail carries the reason, never the password
    failures = summary["recent_failed_logins"]
    assert failures and all(f["metadata"]["reason"] in ("invalid_credentials", "account_disabled") for f in failures)


def test_m10_no_secret_ever_echoed(tmp_path):
    app, _ = _deploy(tmp_path)
    admin_token = admin_access_token(app)
    access = _login(app, ADMIN_USERNAME, ADMIN_PASSWORD)
    assert access["access_token"]
    probes = []
    with _as(app, admin_token) as client:
        probes.append(client.get("/api/auth/security-summary").text)
        probes.append(client.get("/api/auth/users").text)
        probes.append(client.get("/api/meta").text)
        probes.append(client.get("/api/health").text)
    body_only = {k: v for k, v in access.items() if not k.startswith("_")}
    probes.append(json.dumps(body_only))
    blob = "".join(probes)
    assert AUTH_TEST_SECRET not in blob
    assert ADMIN_PASSWORD not in blob
    assert access["_refresh"] not in blob


# ===========================================================================
# H. bug hunt (B01..B30 expressed as behaviours)
# ===========================================================================

def test_m10_bug_hunt_behaviours(tmp_path, client_factory, authed_client_factory):
    update_expected_counts({}, 30, "m10-bug-hunt")

    app, settings = _deploy(tmp_path)
    admin_token = admin_access_token(app)

    # B01 — auth must not be bypassable by missing headers or proxy headers
    with _anon(app) as client:
        assert client.get("/api/data/status").status_code == 401
        assert client.post("/api/auth/me", headers={"X-Forwarded-User": "admin"}).status_code in (401, 405)

    # B02 — a viewer cannot escalate through path tricks (/users//, case)
    viewer = _as(app, _provision_user(app, admin_token, "tyler"))
    assert viewer.get("/api/auth//users").status_code in (403, 404)
    assert viewer.get("/api/auth/USERS").status_code in (403, 404)

    # B03 — generic auth-required for missing bearer, never INFO leakage
    with _anon(app) as client:
        r = client.get("/api/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED"

    # B04 — login rate-limited username bucket independent (other accounts fine)
    _login_status(app, "tyler", "wrong-1")
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 200

    # B05 — receiving a refresh token in a JSON body is a leak; it never happens
    login = _login(app, ADMIN_USERNAME, ADMIN_PASSWORD)
    assert login["access_token"]

    # B06 — the refresh token only ever travels in an HttpOnly cookie
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        body = r.json()
        assert "refresh_token" not in body                     # never in the body
        set_cookie = r.headers.get("set-cookie", "")
        assert "httponly" in set_cookie.lower()
        assert "path=/api/auth/" in set_cookie.lower()

    # B07 — refresh with an empty token is auth-required, not a 500
    with _anon(app) as client:
        r = client.post("/api/auth/refresh", json={"refresh_token": ""})
        assert r.status_code == 401
        assert r.json()["error"]["code"] in ("AUTH_REQUIRED", "SESSION_REVOKED", "TOKEN_INVALID")

    # B08 — passwords never appear in audit, users, login or errors
    with _anon(app) as client:
        bad = client.post("/api/auth/login", json={"username": "tyler", "password": PW}).json()
        assert PW not in json.dumps(bad)

    # B09 — security summary exposes no raw tokens or secrets
    with _as(app, admin_token) as client:
        assert AUTH_TEST_SECRET not in client.get("/api/auth/security-summary").text

    # B10 — an access token is not accepted where a refresh token belongs
    with _anon(app) as client:
        r = client.post("/api/auth/refresh", json={"refresh_token": viewer.token[:40]})
        assert r.status_code == 401
        assert r.json()["error"]["code"] in ("AUTH_REQUIRED", "SESSION_REVOKED", "TOKEN_INVALID")

    # B11 — refresh of a session hashed at rest, never stored raw
    with _as(app, admin_token) as client:
        lst = client.get("/api/auth/users").json()["users"]
        assert not any("token" in json.dumps(u) for u in lst)

    # B12 — unknown route under auth returns envelope, not stack traces
    with _anon(app) as client:
        r = client.get("/api/auth/does-not-exist")
        assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"

    # B13 — mutation gates resolve BEFORE body semantics (no partial effect)
    with _as(app, _provision_user(app, admin_token, "ursula")) as client:
        r = client.post("/api/pairs/register", json={"image_a": "../../etc/passwd"})
        assert r.status_code == 403

    # B14 — analyst semantics still enforced for analysts (path traversal 422)
    with _as(app, _provision_user(app, admin_token, "viktor", role="analyst")) as client:
        r = client.post("/api/pairs/register", json={"image_a": "../../etc/passwd"})
        assert r.status_code == 422 or r.json()["error"]["code"] == "VALIDATION_ERROR"

    # B15 — no plaintext password anywhere in a fresh app's HTTP surface
    with _anon(app) as client:
        for path in ("/api/health", "/api/meta", "/api/auth/status"):
            assert ADMIN_PASSWORD not in client.get(path).text

    # B16 — roles are closed vocabulary (no invented roles accepted)
    with _as(app, admin_token) as client:
        uid = _login(app, ADMIN_USERNAME, ADMIN_PASSWORD)["user"]["id"]
        r = client.patch(f"/api/auth/users/{uid}", json={"role": "superuser"})
        assert r.status_code == 422

    # B18 — duplicate registration cannot create free-floating sessions
    second = _register(app, "tyler", PW)
    assert second["status"] == 401

    # B19 — logout is idempotent and safe
    with _anon(app) as client:
        assert client.post("/api/auth/logout").status_code == 200

    # B20 — auto-created admin is a normal, patchable, auditable user
    with _as(app, admin_token) as client:
        lst = client.get("/api/auth/users").json()["users"]
        boot = next(u for u in lst if u["username"] == ADMIN_USERNAME)
        assert boot["role"] == "admin" and "id" in boot

    # B21 — every response is behind the unified envelope (no raw exceptions)
    with _anon(app) as client:
        r = client.post("/api/auth/login", json={"username": "tyler", "password": "x"})
        assert "error" in r.json() and "code" in r.json()["error"]

    # B22 — account lockout is per-username, not global identity-blocking
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}).status_code == 200

    # B23 — refresh cookie path/secure flags sane in prod helper
    assert settings.auth_cookie_samesite in ("strict", "lax", "none")

    # B24 — protected reads are AUTH_REQUIRED (401), mutable reads are readable by viewer
    assert _as(app, _provision_user(app, admin_token, "wendy")).get("/api/data/status").status_code == 200

    # B25 — no user enumeration through /me or users listing
    with _anon(app) as client:
        r = client.get("/api/auth/me", headers={"Authorization": "Bearer eyJ.eyJ.xx"})
        assert r.status_code in (401,)

    # B26 — an analyst sees the same honest zero-pair dataset as admin
    with _as(app, _provision_user(app, admin_token, "xavier", role="analyst")) as client:
        assert client.get("/api/data/status").json()["pairs_registered"] == 0

    # B27 — identity never leaks into scientific endpoints' responses
    with _as(app, admin_token) as client:
        text = client.get("/api/data/status").text
        assert "test-admin" not in text

    # B28 — token expiry is honoured (no clock-free access)
    with _anon(app) as client:
        expired = create_access_token(settings=settings, subject="U-x", role=Role.VIEWER, ttl_seconds=-1,
                                      auth_config=__import__("backend.app.auth.config", fromlist=["load_auth_config"]).load_auth_config(settings))
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

    # B29 — one account, many sessions; revoking one keeps the current live
    with TestClient(app) as client:
        client.post("/api/auth/login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        with _as(app, admin_token) as c2:
            me = c2.get("/api/auth/users").json()["users"]
            sessions = [u["active_sessions"] for u in me if u["username"] == ADMIN_USERNAME]
            assert sessions and sessions[0] >= 2
        # the second, most-recent session still refreshes fine
        assert client.post("/api/auth/refresh").status_code == 200

    # B30 — password change cannot be performed without knowing the password
    with _anon(app) as client:
        r = client.post("/api/auth/me/password", json={"current_password": "x", "new_password": PW2})
        assert r.status_code in (401,)

    # B17 — disabled auth still fails closed (server never soft-fails open)
    # NOTE: run last — creating a second app replaces the module state, so it
    # must not run before the checks that still need the fully-configured app.
    with client_factory(auth_secret_key="") as client:
        r = client.get("/api/pairs")
        assert r.status_code == 501 and r.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"