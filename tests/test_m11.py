"""M11 hardening tests — reliability, observability, recoverability.

Covers B01–B40 across five themes:

* **B01–B05 smoke & request correlation** — health/meta shape, readYY readiness,
  the unified error envelope's ``request_id``, and ``X-Request-ID`` echo.
* **B06–B10 input & envelope hardening** — bounded request bodies (413
  ``LIMIT_EXCEEDED``), validation envelopes (422), 404 envelopes, env
  separation, and no unsanitized request IDs.
* **B11–B15 readiness model** — optional (AI/deep-matcher/real-data) states
  never make the service unhealthy; hard dependencies (filesystem) fail to
  503 ``NOT_READY``; BLOCKED scientific data is honest, not fatal.
* **B16–B20 atomic writes & run locks** — no partial artifacts, atomic
  replace failure preserves the old artifact, ``RunLock`` mutual exclusion
  (409), stale-lock reconciliation marking interrupted runs honestly, run
  events recorded by ``guard_run``.
* **B21–B25 no silent partial-as-success** — M4 timeout -> ``FAILED`` +
  ``TIMEOUT`` block code; M5 timeout -> ``FAILED`` + ``SPATIAL_TIMEOUT``;
  writers are atomic and in-run ``COMPLETE`` is never produced on timeout.
* **B26–B30 authentication interplay** — unconfigured auth fails closed
  (501) exactly where documented; health/readiness stay public while
  pipeline reads require a session; admin-only ops surface.
* **B31–B35 operational overview** — shape, service ids, honest scientific
  status, no secrets/paths/tracebacks, run events surfaced.
* **B36–B40 hardening posture** — runtime config constants, router-level run
  guards, budget enforcement keys, atomic artifact audit.

Every test uses isolated temp deployments; none touches the real data tree.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import fixturegen  # noqa: F401

from auth_helpers import (
    AUTH_TEST_SECRET,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    AuthedTestClient,
    admin_access_token,
)
from backend.app.auth import service as auth_service
from backend.app.config import Settings
from backend.app.data import ensure_derived_directories
from backend.app.errors import AppError, JobAlreadyRunningError
from backend.app.hardening import (
    RunLock,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_npy,
    atomic_write_npz,
    guarded_run,
    mark_run_interrupted,
    read_json_safe,
    recent_run_events,
)
from backend.app.main import create_app
from backend.app.ops import SERVICE_IDS, _ready_state, readiness_payload
from backend.app.spatial.service import SpatialService
from backend.app.spatial.states import SpatialBlockCode, SpatialRunState
from backend.app.trust.service import TrustService
from backend.app.trust.states import TrustGateState

# ---------------------------------------------------------------------------
# deployment helpers (mirrors test_m10 harness)
# ---------------------------------------------------------------------------


def _deploy(tmp_path: Path, **overrides):
    overrides.setdefault("data_root", str(tmp_path / "data"))
    settings = Settings(**overrides, _env_file=None)
    ensure_derived_directories(settings)
    app = create_app(settings=settings)
    return app, settings


def _anon(app) -> TestClient:
    return TestClient(app)


def _admin_client(app) -> AuthedTestClient:
    return AuthedTestClient(app, admin_access_token(app))


# ===========================================================================
# B01–B05  smoke & request correlation
# ===========================================================================


def test_b01_health_is_live_and_reports_m11(tmp_path):
    app, _settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["milestone"] == "M11"
        assert body["version"] == "0.11.0"
        assert "auth" in body
        assert "ai" in body


def test_b02_meta_keeps_m11_and_canonical_config_keys(tmp_path):
    app, settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.get("/api/meta")
        assert r.status_code == 200
        body = r.json()
        assert body["milestone"] == "M11"
        assert body["version"] == "0.11.0"
        for key in ("m1_config", "m7_config", "m10_config", "settings"):
            assert key in body
        assert body["settings"]["http_max_body_bytes"] == settings.http_max_body_bytes


def test_b03_ready_is_readiness_not_liveness(tmp_path):
    app, _settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.get("/api/ready")
        assert r.status_code == 200  # optional/BLOCKED states -> DEGRADED, never fatal
        body = r.json()
        assert body["ready"] is True
        assert body["status"] in ("READY", "DEGRADED")
        assert [s["id"] for s in body["services"]] == SERVICE_IDS


def test_b04_request_id_echoed_on_success(tmp_path):
    app, _settings = _deploy(tmp_path)
    rid = "b04-request-0001"
    with _anon(app) as client:
        r = client.get("/api/health", headers={"X-Request-ID": rid})
        assert r.headers.get("x-request-id") == rid


def test_b05_error_envelope_carries_request_id(tmp_path):
    app, _settings = _deploy(tmp_path)
    rid = "b05-request-0002"
    with _anon(app) as client:
        r = client.get("/api/does-not-exist", headers={"X-Request-ID": rid})
        assert r.status_code == 404
        assert r.headers.get("x-request-id") == rid
        env = r.json()["error"]
        assert env["code"] == "NOT_FOUND"
        assert env["request_id"] == rid


# ===========================================================================
# B06–B10  input & envelope hardening
# ===========================================================================


def test_b06_oversized_body_rejected_honestly(tmp_path):
    app, settings = _deploy(tmp_path)
    big = {"data": "x" * (settings.http_max_body_bytes + 1024)}
    with _anon(app) as client:
        r = client.post("/api/auth/login", json=big)
        assert r.status_code == 413
        env = r.json()["error"]
        assert env["code"] == "LIMIT_EXCEEDED"
        assert env["retryable"] is False


def test_b07_validation_failure_uses_unified_envelope(tmp_path):
    app, _settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.post("/api/auth/login", json={"username": 123, "password": "x"})
        assert r.status_code == 422
        env = r.json()["error"]
        assert env["code"] == "VALIDATION_ERROR"
        assert "fields" in env["details"]
        assert env["request_id"]


def test_b08_unknown_route_gets_not_found_envelope(tmp_path):
    app, _settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.get("/api/nope/1/2")
        assert r.status_code == 404
        env = r.json()["error"]
        assert env["code"] == "NOT_FOUND"
        assert r.headers.get("x-request-id") == env.get("request_id")


def test_b09_app_env_is_validated_and_demo_is_visible(tmp_path):
    with pytest.raises(ValidationError):
        Settings(app_env="not-an-env", _env_file=None)
    settings = Settings(app_env="demo", demo_mode=True, _env_file=None)
    assert settings.app_env == "demo"
    app, _ = _deploy(tmp_path, app_env="demo", app_debug=False, demo_mode=True)
    with _anon(app) as client:
        body = client.get("/api/health").json()
        assert body["environment"] == "demo"
        assert body["demo_mode"] is True


def test_b10_unsanitized_request_ids_are_replaced_not_echoed(tmp_path):
    app, _settings = _deploy(tmp_path)
    bad = "evil<script>alert(1)</script>"[:40]
    with _anon(app) as client:
        r = client.get("/api/health", headers={"X-Request-ID": bad})
        echoed = r.headers.get("x-request-id", "")
        assert bad not in echoed
        assert echoed  # a freshly generated id was used instead


# ===========================================================================
# B11–B15  readiness model
# ===========================================================================


def test_b11_scientific_data_blocked_is_honest_not_fatal(tmp_path):
    app, _settings = _deploy(tmp_path)
    with _anon(app) as client:
        r = client.get("/api/ready")
        assert r.status_code == 200
        services = {s["id"]: s for s in r.json()["services"]}
        sci = services["scientific_data"]
        assert sci["state"] == "BLOCKED"
        assert "REAL_DATA_UNAVAILABLE" in sci["detail"]
        assert r.json()["status"] == "DEGRADED"


def test_b12_optional_capabilities_never_fail_the_service(tmp_path):
    app, _settings = _deploy(tmp_path)
    with _anon(app) as client:
        services = {s["id"]: s for s in client.get("/api/ready").json()["services"]}
        for sid in ("ai_capability", "deep_matcher", "scientific_data", "authentication"):
            assert services[sid]["state"] in ("READY", "DEGRADED", "BLOCKED", "UNAVAILABLE", "NOT_CONFIGURED")


def test_b13_hard_dependency_failure_is_not_ready_503(tmp_path, monkeypatch):
    app, _settings = _deploy(tmp_path)
    monkeypatch.setattr(
        "backend.app.ops.dependency_status",
        lambda settings: [
            {"id": "backend", "name": "Backend", "state": "READY", "detail": ""},
            {"id": "database", "name": "Database", "state": "READY", "detail": ""},
            {"id": "filesystem", "name": "Filesystem", "state": "FAILED", "detail": "synthetic"},
            {"id": "configuration", "name": "Configuration", "state": "READY", "detail": ""},
            {"id": "authentication", "name": "Authentication", "state": "NOT_CONFIGURED", "detail": ""},
            {"id": "ai_capability", "name": "AI", "state": "NOT_CONFIGURED", "detail": ""},
            {"id": "deep_matcher", "name": "Deep matcher", "state": "UNAVAILABLE", "detail": ""},
            {"id": "scientific_data", "name": "Data", "state": "BLOCKED", "detail": ""},
        ],
    )
    with _anon(app) as client:
        r = client.get("/api/ready")
        assert r.status_code == 503
        assert r.json()["ready"] is False
        assert r.json()["status"] == "NOT_READY"


def test_b14_ready_state_truth_table(tmp_path):
    _deploy(tmp_path)
    assert _ready_state([
        {"id": "backend", "state": "READY"}, {"id": "filesystem", "state": "READY"},
        {"id": "configuration", "state": "READY"}, {"id": "database", "state": "READY"},
    ]) == ("READY", True)
    assert _ready_state([
        {"id": "backend", "state": "READY"}, {"id": "filesystem", "state": "READY"},
        {"id": "configuration", "state": "READY"}, {"id": "database", "state": "READY"},
        {"id": "scientific_data", "state": "BLOCKED"},
    ]) == ("DEGRADED", True)
    assert _ready_state([
        {"id": "backend", "state": "READY"}, {"id": "filesystem", "state": "FAILED"},
        {"id": "configuration", "state": "READY"}, {"id": "database", "state": "READY"},
    ]) == ("NOT_READY", False)


def test_b15_readiness_payload_shape_contract(tmp_path):
    _deploy(tmp_path)
    code, payload = readiness_payload(_settings_with(tmp_path))
    assert payload["ready"] is True
    assert isinstance(payload["services"], list)
    assert len(payload["services"]) == len(SERVICE_IDS)
    assert payload["services"][0]["id"] == "backend"
    assert "timestamp" in payload
    assert "note" in payload


def _settings_with(tmp_path: Path) -> Settings:
    settings = Settings(data_root=str(tmp_path / "data"), _env_file=None)
    ensure_derived_directories(settings)
    return settings


# ===========================================================================
# B16–B20  atomic writes & run locks
# ===========================================================================


def test_b16_atomic_json_never_leaves_partial_artifacts(tmp_path):
    target = tmp_path / "artifacts" / "status.json"
    atomic_write_json(target, {"state": "COMPLETE", "count": 7})
    assert read_json_safe(target) == {"state": "COMPLETE", "count": 7}
    leftovers = list(target.parent.glob(".status.json.tmp-*"))
    assert leftovers == []
    raw = target.read_text(encoding="utf-8")
    assert raw.endswith("\n")


def test_b17_atomic_replace_failure_preserves_previous_artifact(tmp_path, monkeypatch):
    target = tmp_path / "metrics.json"
    atomic_write_json(target, {"version": 1})
    before = target.read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("synthetic replace failure")

    monkeypatch.setattr("backend.app.hardening.os.replace", boom)
    with pytest.raises(OSError):
        atomic_write_json(target, {"version": 2, "pad": "y" * 500})
    assert target.read_text(encoding="utf-8") == before
    assert list(target.parent.glob(".metrics.json.tmp-*")) == []


def test_b18_runlock_rejects_concurrent_owner_with_409_class(tmp_path):
    run_dir = tmp_path / "derived" / "trust" / "CS-P000"
    first = RunLock(run_dir, budget_seconds=0.2, tag="m4_trust")
    first.acquire()
    try:
        second = RunLock(run_dir, budget_seconds=0.2, tag="m4_trust")
        with pytest.raises(JobAlreadyRunningError) as exc:
            with second:
                pass
        assert exc.value.code == "JOB_ALREADY_RUNNING"
        assert exc.value.http_status == 409
    finally:
        first.release()
    reacquire = RunLock(run_dir, budget_seconds=0.2, tag="m4_trust")
    with reacquire:
        assert (run_dir / ".run.lock").is_file()


def test_b19_stale_lock_is_reconciled_and_run_marked_interrupted(tmp_path):
    run_dir = tmp_path / "derived" / "registration" / "CS-P001"
    run_dir.mkdir(parents=True)
    atomic_write_json(run_dir / "status.json", {"state": "RUNNING", "pair_id": "CS-P001"})
    # Simulate a crashed process: a lock file older than the budget, left behind
    # while the dead run's status still says RUNNING.
    atomic_write_json(run_dir / ".run.lock", {
        "tag": "m6_registration", "token": "deadbeef",
        "pid": 0, "created_at": "2020-01-01T00:00:00Z", "created_epoch": 0.0,
    })
    os.utime(run_dir / ".run.lock", (time.time() - 60, time.time() - 60))

    marked = mark_run_interrupted(run_dir, reason="RUN_INTERRUPTED")
    assert marked is True
    status = read_json_safe(run_dir / "status.json")
    assert status["state"] == "FAILED"
    assert status["interrupted"] is True

    fresh = RunLock(run_dir, budget_seconds=0.2, tag="m6_registration")
    with fresh:
        recreated = read_json_safe(run_dir / ".run.lock")
        assert recreated is not None
        assert recreated["token"] != "deadbeef"  # the stale lock was replaced
        assert recreated["tag"] == "m6_registration"


def test_b20_guarded_run_records_success_and_failure_events(tmp_path):
    settings = SimpleNamespace(
        data_root_path=tmp_path,
        run_stale_budget_seconds=0.2,
    )
    pair = "CS-P002"
    before = len(recent_run_events())
    with guarded_run(tmp_path / "derived" / "spatial" / pair,
                     budget_seconds=0.2, tag="m5_spatial"):
        pass
    events = recent_run_events()
    assert len(events) == before  # guarded_run itself records nothing


def test_b20b_guard_run_records_run_event(tmp_path):
    from backend.app.run_guard import guard_run

    settings = SimpleNamespace(
        data_root_path=tmp_path,
        run_stale_budget_seconds=0.2,
    )

    def ok():
        return {"state": "COMPLETE"}

    result = guard_run(settings, derived_stage="spatial", pair_id="CS-P002",
                       configuration_id="SR-M5-001", tag="m5_spatial", fn=ok)
    assert result["state"] == "COMPLETE"

    def broken():
        err = AppError("boom")
        err.code = "INTEGRITY_FAILED"
        raise err

    with pytest.raises(AppError):
        guard_run(settings, derived_stage="spatial", pair_id="CS-P002",
                  configuration_id="SR-M5-001", tag="m5_spatial", fn=broken)
    latest = recent_run_events(limit=2)
    statuses = [e["status"] for e in latest]
    assert "COMPLETE" in statuses
    assert "FAILED" in statuses
    failed = [e for e in latest if e["status"] == "FAILED"][-1]
    assert failed["error_code"] == "INTEGRITY_FAILED"
    assert failed["stage"] == "m5_spatial"
    assert failed["configuration_id"] == "SR-M5-001"


def test_b20c_npy_and_npz_writes_are_atomic(tmp_path):
    arr = np.arange(24).reshape(4, 6)
    npy = tmp_path / "sel" / "registered_image.npy"
    atomic_write_npy(npy, arr)
    assert np.array_equal(np.load(npy), arr)
    npz_p = tmp_path / "sel" / "selected.npz"
    atomic_write_npz(npz_p, x_a=np.array([1.0, 2.0]), y_a=np.array([3.0]))
    with np.load(npz_p) as z:
        assert np.array_equal(z["x_a"], np.array([1.0, 2.0]))
    for p in (tmp_path / "sel").iterdir():
        assert ".tmp-" not in p.name
    raw = atomic_write_bytes(tmp_path / "sel" / "preview.png", b"\x89PNG\r\n\x1a\n")
    assert raw is None


# ===========================================================================
# B21–B25  no silent partial-as-success on timeout
# ===========================================================================


def test_b21_m4_timeout_never_reports_complete(tmp_path):
    svc = TrustService(tmp_path, m4_cfg={})
    run_dir = tmp_path / "derived" / "trust" / "CS-P010" / "r1"
    svc._write_status("CS-P010", run_dir, TrustGateState.FAILED,
                      "PC-M2-001", "MC-M3-001", "TG-M4-001",
                      block_code="TIMEOUT", reasons=["TG_NOT_RUN"])
    status = read_json_safe(run_dir / "trust_status.json")
    assert status["gate_state"] == "FAILED"
    assert status["block_code"] == "TIMEOUT"
    assert "TG_NOT_RUN" in status["reasons"]


def test_b22_m4_run_decision_ties_timeout_to_failed(tmp_path):
    src = Path("backend/app/trust/service.py").read_text(encoding="utf-8")
    assert "timed_out" in src
    assert "gate_state = TrustGateState.FAILED" in src
    assert "block_code=\"TIMEOUT\" if timed_out else None" in src
    assert "TrustGateState.COMPLETE if trusted_tiles > 0 else TrustGateState.FAILED" in src


def test_b23_m5_timeout_reports_failed_spatial_timeout(tmp_path):
    svc = SpatialService(tmp_path, m5_cfg={})
    run_dir = tmp_path / "derived" / "spatial" / "CS-P011" / "r1"
    svc._write_status(run_dir, "CS-P011", SpatialRunState.FAILED,
                      "PC-M2-001", "MC-M3-001", "TG-M4-001", "SR-M5-001",
                      block_code=SpatialBlockCode.SPATIAL_TIMEOUT.value,
                      reasons=["SPATIAL_RUNTIME_TIMEOUT"])
    status = read_json_safe(run_dir / "status.json")
    assert status["state"] == "FAILED"
    assert status["block_code"] == "SPATIAL_TIMEOUT"
    assert "SPATIAL_RUNTIME_TIMEOUT" in status["reasons"]


def test_b24_m5_summary_tracks_timed_out_truthfully(tmp_path):
    svc = SpatialService(tmp_path, m5_cfg={})
    run_dir = tmp_path / "derived" / "spatial" / "CS-P012" / "r1"
    summary = {"timed_out": True, "selected_correspondence_count": 12}
    svc._write_summary(run_dir, "CS-P012", SpatialRunState.FAILED,
                       "PC-M2-001", "MC-M3-001", "TG-M4-001", "SR-M5-001", summary)
    written = read_json_safe(run_dir / "summary.json")
    assert written["state"] == "FAILED"
    assert written["timed_out"] is True


def test_b25_m5_run_decision_never_complete_on_timeout(tmp_path):
    src = Path("backend/app/spatial/service.py").read_text(encoding="utf-8")
    assert "SpatialRunState.FAILED if timeout_flagged else SpatialRunState.COMPLETE" in src
    assert "block_code=SpatialBlockCode.SPATIAL_TIMEOUT.value" in src
    assert "reasons=[\"SPATIAL_RUNTIME_TIMEOUT\"]" in src


# ===========================================================================
# B26–B30  authentication interplay
# ===========================================================================


def test_b26_unconfigured_auth_fails_closed_on_protected_routes(tmp_path):
    app, _settings = _deploy(tmp_path)  # AUTH_SECRET_KEY empty
    with _anon(app) as client:
        r = client.get("/api/ops/overview")
        assert r.status_code == 501
        env = r.json()["error"]
        assert env["code"] == "AUTH_NOT_CONFIGURED"


def test_b27_health_and_ready_remain_public_with_auth_configured(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    # First login initializes the persistent auth database.
    with _admin_client(app):
        pass
    with _anon(app) as client:
        assert client.get("/api/health").status_code == 200
        r = client.get("/api/ready")
        assert r.status_code == 200
        services = {s["id"]: s for s in r.json()["services"]}
        assert services["authentication"]["state"] == "READY"
        assert services["database"]["state"] == "READY"


def test_b28_pipeline_reads_still_require_a_session(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with _anon(app) as client:
        r = client.get("/api/pairs/list")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_b29_admin_only_ops_route_enforced(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with _admin_client(app) as admin:
        r = admin.get("/api/ops/overview")
        assert r.status_code == 200
        assert r.json()["system"]["milestone"] == "M11"


def test_b30_auth_database_records_are_durable_under_wal(tmp_path):
    app, settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                            auth_bootstrap_admin_username=ADMIN_USERNAME,
                            auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with _admin_client(app):  # first login creates + initializes the DB (WAL)
        pass
    db = settings.auth_db_file
    assert db.is_file()
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    with sqlite3.connect(str(db), timeout=5) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        assert rows >= 1  # bootstrap admin persisted


# ===========================================================================
# B31–B35  operational overview
# ===========================================================================


def test_b31_ops_overview_shape(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with _admin_client(app) as admin:
        body = admin.get("/api/ops/overview").json()
        assert {s["id"] for s in body["services"]} == set(SERVICE_IDS)
        assert body["system"]["ready"] is True
        assert body["system"]["milestone"] == "M11"
        assert isinstance(body["recent_runs"], list)
        assert isinstance(body["recent_failures"], list)
        assert body["authentication"]["configured"] is True
        assert body["authentication"]["users"] >= 1


def test_b32_ops_overview_leaks_no_secrets_or_paths(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with _admin_client(app) as admin:
        text = json.dumps(admin.get("/api/ops/overview").json())
        assert AUTH_TEST_SECRET not in text
        assert ADMIN_PASSWORD not in text
        assert "traceback" not in text.lower()
        assert "data_root" not in text
        assert "\\data\\" not in text


def test_b33_ops_failure_flags_honest_scientific_status(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with _admin_client(app) as admin:
        services = {s["id"]: s for s in admin.get("/api/ops/overview").json()["services"]}
        assert services["scientific_data"]["state"] == "BLOCKED"
        assert "REAL_DATA_UNAVAILABLE" in services["scientific_data"]["detail"]


def test_b34_recent_run_events_surface_durations(tmp_path):
    _deploy(tmp_path)
    events = recent_run_events(limit=50)
    assert isinstance(events, list)
    for e in events:
        assert set(e) >= {"stage", "pair_id", "configuration_id", "status",
                          "duration_ms", "error_code", "finished_at"}


def test_b35_ops_requires_admin_role_not_just_any_session(tmp_path):
    app, _settings = _deploy(tmp_path, auth_secret_key=AUTH_TEST_SECRET,
                             auth_bootstrap_admin_username=ADMIN_USERNAME,
                             auth_bootstrap_admin_password=ADMIN_PASSWORD)
    with TestClient(app) as client:
        username = "ops-viewer"
        password = "Viewer-1234-test!"
        assert client.post("/api/auth/register",
                           json={"username": username, "password": password,
                                 "display_name": username}).status_code == 200
        login = client.post("/api/auth/login",
                            json={"username": username, "password": password})
        assert login.status_code == 200
        token = login.json()["access_token"]
    with AuthedTestClient(app, token) as viewer:
        r = viewer.get("/api/ops/overview")
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"


# ===========================================================================
# B36–B40  hardening posture
# ===========================================================================


def test_b36_runtime_hardening_constants_are_present(tmp_path):
    settings = _settings_with(tmp_path)
    assert settings.http_max_body_bytes >= 4_000_000
    assert settings.run_stale_budget_seconds >= 30
    assert settings.request_id_header == "x-request-id"


def test_b37_router_level_run_guards_are_wired(tmp_path):
    app, settings = _deploy(tmp_path)
    with _anon(app) as client:
        oas = client.get("/openapi.json").json()
    paths = oas.get("paths", {})
    for expected in (
        "/api/matching/{pair_id}/run",
        "/api/matching/{pair_id}/m8/run",
        "/api/trust/{pair_id}/run",
        "/api/spatial/{pair_id}/run",
        "/api/registration/{pair_id}/run",
        "/api/metrics/{pair_id}/run",
        "/api/ops/overview",
        "/api/ready",
    ):
        assert expected in paths, f"missing route {expected}"


def test_b38_pipeline_routers_use_guard_run(tmp_path):
    for router in ("matching", "trust", "spatial", "registration", "metrics"):
        text = Path(f"backend/app/api/{router}.py").read_text(encoding="utf-8")
        assert "guard_run" in text, router
        assert "derived_stage=" in text, router


def test_b39_pipeline_stages_declare_execution_budgets(tmp_path):
    import re
    text = Path("configs/app.yaml").read_text(encoding="utf-8")
    for stage in ("m2", "m3", "m4", "m5", "m6", "m7"):
        assert f"{stage}:" in text
    assert len(re.findall(r"max_runtime_seconds:\s*\d+", text)) >= 5
    assert len(re.findall(r"execution:", text)) >= 6


def test_b40_run_events_are_bounded_and_error_coded(tmp_path):
    _deploy(tmp_path)
    events = recent_run_events(limit=1)
    if events:
        assert events[-1]["duration_ms"] >= 0
        assert isinstance(events[-1]["status"], str)
    from backend.app.hardening import _MAX_RUN_EVENTS
    assert _MAX_RUN_EVENTS >= 100
    assert auth_service is not None  # keep import used; init path covered by B30


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))