"""M10 test helpers — authenticated TestClient for the M1–M9 suites.

Since M10 the scientific pipeline endpoints require authentication. The
M1–M9 suites keep exercising the real pipeline by running through
``AuthedTestClient``, which attaches a bootstrap-admin bearer access token
to every request automatically (callers may override with their own
``Authorization`` header). Only the M10 suite exercises unauthenticated and
unauthorized behaviour explicitly.

The test secret below is a deliberate, documented value used ONLY by the
test suite; it never influences environment settings.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

AUTH_TEST_SECRET = "m10-test-secret-0123456789abcdef0123456789abcdef"
ADMIN_USERNAME = "test-admin"
ADMIN_PASSWORD = "Admin-1234-test!"


def configure_auth(settings) -> None:
    """Force a known test secret + bootstrap admin onto an in-test Settings."""
    if not settings.auth_secret_key:
        settings.auth_secret_key = AUTH_TEST_SECRET
    settings.auth_bootstrap_admin_username = ADMIN_USERNAME
    settings.auth_bootstrap_admin_password = ADMIN_PASSWORD


class AuthedTestClient(TestClient):
    """TestClient that injects a bearer token when not already provided."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self._token = token

    @property
    def token(self) -> str:
        return self._token

    def request(self, method, url, **kwargs):
        headers = dict(kwargs.get("headers") or {})
        if self._token:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)

    def bare(self):
        """Return a client that does NOT inject a token (for 401/403 probes)."""
        return TestClient(self.app)


def admin_access_token(app) -> str:
    """Log in as the bootstrap admin on an already-built app.

    Requires ``auth_secret_key`` + bootstrap admin to be configured (see
    ``configure_auth``). Returns the access token for ``AuthedTestClient``.
    """
    probe = TestClient(app)
    try:
        resp = probe.post(
            "/api/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]
    finally:
        probe.close()


def authed_client_for_app(app) -> AuthedTestClient:
    """Wrap an app (auth pre-configured) in an authed TestClient."""
    return AuthedTestClient(app, admin_access_token(app))


__all__ = [
    "AUTH_TEST_SECRET",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "AuthedTestClient",
    "configure_auth",
    "admin_access_token",
    "authed_client_for_app",
]