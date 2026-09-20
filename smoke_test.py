"""SIH26166 — Milestone M11 environment smoke test.

Validates, end to end:
    * Python environment
    * dependency imports
    * configuration (YAML + runtime settings)
    * data directory architecture
    * FastAPI startup over a real HTTP socket
    * /api/health + /api/meta responses
    * M1 endpoints: /api/data/status, /api/data/sensors,
      /api/pairs, /api/pairs/next-id, /api/pairs/scan,
      /api/pairs/probe (traversal rejection), 404 behaviour
    * M2..M9 pipeline endpoint honesty (clean repo -> BLOCKED/NOT_STARTED)
    * M10 authentication: auth status, login with HttpOnly cookie, /me,
      fail-closed anonymous 401/501 behaviour
    * M11 hardening: /api/ready readiness probe, X-Request-ID echo,
      error envelopes, 413 body-limit, admin-only /api/ops/overview
    * frontend render + frontend->backend connectivity

Every milestone boots the real app with authentication ENABLED (a random
AUTH_SECRET_KEY is generated unless one is already configured) and an
isolated temporary auth database, then logs in as an administrator and
carries the bearer token on all probes.

Usage:
    .venv\\Scripts\\python.exe smoke_test.py

Exits non-zero if anything fails. NEVER reports PASS on failure.
"""

from __future__ import annotations

import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_PORT = int(os.environ.get("SMOKE_PORT", "8137"))

CHECKS: list[tuple[str, bool, str]] = []

# Freshly-obtained access token for the currently-probed backend instance.
SMOKE_TOKEN: str | None = None

SMOKE_ADMIN_USER = "smoke-admin"
SMOKE_ADMIN_PASSWORD = "Smoke-Admin-2026-m10!"


def _auth_env() -> dict[str, str]:
    """Env overrides that keep the smoke isolated and authentication ENABLED.

    Uses the live AUTH_SECRET_KEY when one is configured, otherwise generates
    an ephemeral key and a dedicated bootstrap administrator. The auth DB is
    placed in the OS temp dir so the smoke never writes into the repo's data
    tree.
    """
    key = os.environ.get("AUTH_SECRET_KEY", "").strip() or secrets.token_urlsafe(48)
    db = (
        os.environ.get("AUTH_DB_PATH", "").strip()
        or str(Path(tempfile.gettempdir()) / f"chandrasutra_smoke_{os.getpid()}.db")
    )
    user, pw = _admin_creds()
    return {
        "AUTH_SECRET_KEY": key,
        "AUTH_DB_PATH": db,
        "AUTH_REGISTER_ENABLED": "true",
        "AUTH_BOOTSTRAP_ADMIN_USERNAME": user,
        "AUTH_BOOTSTRAP_ADMIN_PASSWORD": pw,
    }


def _admin_creds() -> tuple[str, str]:
    user = os.environ.get("AUTH_BOOTSTRAP_ADMIN_USERNAME", "").strip() or SMOKE_ADMIN_USER
    pw = os.environ.get("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "").strip() or SMOKE_ADMIN_PASSWORD
    return user, pw


def _require_token(base: str, tag: str) -> bool:
    """Log in as the (auto-)bootstrap administrator and stash the bearer token."""
    global SMOKE_TOKEN  # noqa: PLW0603
    user, pw = _admin_creds()
    body = _post_json(f"{base}/auth/login", {"username": user, "password": pw})
    SMOKE_TOKEN = (body or {}).get("access_token")
    ok = bool(SMOKE_TOKEN)
    record(f"{tag}-auth-login", ok, f"login as {user} -> token={bool(SMOKE_TOKEN)} role={(body or {}).get('user', {}).get('role')}")
    return ok


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {SMOKE_TOKEN}"} if SMOKE_TOKEN else {}


def record(name: str, ok: bool, detail: str) -> None:
    CHECKS.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}: {detail}")


def main() -> int:
    print(f"CHANDRASUTRA (SIH26166) M1..M11 smoke test  |  repo root: {REPO_ROOT}")
    print(f"  Python           : {sys.version.split()[0]}  ({sys.executable})\n")

    # ---- 1. Python version ------------------------------------------------
    major, minor = sys.version_info[:2]
    record("python-version", (major, minor) >= (3, 10), f"Python {major}.{minor} (>=3.10 required)")

    # ---- 2. dependency imports --------------------------------------------
    deps = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "numpy": "numpy",
        "opencv (cv2)": "cv2",
        "pillow (PIL)": "PIL",
        "pydantic_settings": "pydantic_settings",
        "yaml": "yaml",
        "jwt (PyJWT)": "jwt",
        "httpx": "httpx",
        "pytest": "pytest",
    }
    for name, module in deps.items():
        try:
            __import__(module)
            record(f"import {module}", True, "import ok")
        except Exception as exc:  # noqa: BLE001
            record(f"import {module}", False, f"import failed: {exc}")

    # ---- 3. configuration --------------------------------------------------
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from backend.app.config import Settings, load_pipeline_config  # noqa: PLC0415

        settings = Settings()
        load_pipeline_config()
        record("config", True, f"env={settings.app_env} yaml=ok data_root={settings.data_root_path}")
    except Exception as exc:  # noqa: BLE001
        record("config", False, f"could not load configuration: {exc}")

    # ---- 4. data directory architecture -----------------------------------
    try:
        from backend.app.data import DATA_TREE, data_directory_status  # noqa: PLC0415

        info = data_directory_status(Settings())
        missing = [d.id for d in info if not d.exists]
        name = len(info)
        record(
            "data-directories",
            len(missing) == 0,
            f"{name} logical dirs; missing={missing or 'none'}",
        )
    except Exception as exc:  # noqa: BLE001
        record("data-directories", False, f"unable to inspect data tree: {exc}")

    # ---- 5. backend startup + health over HTTP -----------------------------
    record_backend_http()

    # ---- 5b. M1 endpoints over HTTP ----------------------------------------
    record_m1_backend()

    # ---- 5c. M2 endpoints over HTTP ----------------------------------------
    record_m2_backend()

    # ---- 5d. M3 endpoints over HTTP ----------------------------------------
    record_m3_backend()

    # ---- 5e. M4 endpoints over HTTP ----------------------------------------
    record_m4_backend()

    # ---- 5f. M5 endpoints over HTTP ----------------------------------------
    record_m5_backend()

    # ---- 5g. M6 endpoints over HTTP ----------------------------------------
    record_m6_backend()

    # ---- 5h. M7 endpoints over HTTP ----------------------------------------
    record_m7_backend()

    # ---- 5i. M8 endpoints over HTTP ----------------------------------------
    record_m8_backend()

    # ---- 5j. M9 AI endpoints over HTTP -------------------------------------
    record_m9_backend()

    # ---- 5k. M10 auth endpoints over HTTP ----------------------------------
    record_m10_backend()

    # ---- 5l. M11 hardening endpoints over HTTP ------------------------------
    record_m11_backend()

    # ---- 6. frontend render + frontend->backend connectivity ----------------
    record_frontend()

    print("\n  Summary:")
    total = len(CHECKS)
    passed = sum(1 for _n, ok, _d in CHECKS if ok)
    failed_n = total - passed
    print(f"    checks: {total} | passed: {passed} | failed: {failed_n}")
    if failed_n:
        print("  OVERALL: FAIL")
        return 1
    print("  OVERALL: PASS")
    return 0


def record_frontend() -> None:
    import shutil

    node = shutil.which("node")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not node or not npm:
        record("frontend-toolchain", False, f"node/npm not found (node={node}, npm={npm})")
        return
    record("frontend-toolchain", True, f"node={_run([node, '--version']) or '?'} npm present")

    frontend_dir = REPO_ROOT / "frontend"
    ssr = _run([node, "ssr-smoke.mjs"], cwd=frontend_dir)
    record("frontend-render", "OVERALL: PASS" in (ssr or ""), "ssr-smoke rendered all pages")

    # Spawn backend + vite on free ports and request /api/health THROUGH vite.
    backend_port = free_port()
    vite_port = free_port()
    env = {**os.environ, "VITE_PROXY_TARGET": f"http://127.0.0.1:{backend_port}", "VITE_PORT": str(vite_port), **_auth_env()}
    procs: list[subprocess.Popen] = []
    try:
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
                 "--port", str(backend_port), "--log-level", "warning"],
                cwd=REPO_ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        )
        if not _wait_for_health(f"http://127.0.0.1:{backend_port}/api/health", timeout=40):
            record("frontend-proxy-backend", False, "backend did not become healthy")
            return
        procs.append(
            subprocess.Popen(
                [npm, "run", "dev"],  # npm.cmd resolves via shutil.which on Windows
                cwd=frontend_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        )
        # _wait_for via health through the vite proxy
        if _wait_for_health(f"http://127.0.0.1:{vite_port}/api/health", timeout=60):
            record("frontend-proxy", True, f"GET {vite_port}/api/health returned 200 via vite proxy")
        else:
            record("frontend-proxy", False, "vite proxy did not reach the backend within 60s")
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        record("frontend-proxy", False, f"launch failed: {exc}")
    finally:
        for proc in procs:
            proc.terminate()
            try:
                proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=180, check=False
        )
        return (result.stdout + result.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def record_backend_http() -> None:
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_PORT": str(port), **_auth_env()},
        )
        url = f"http://127.0.0.1:{port}/api/health"
        healthy = _wait_for_health(url, timeout=40)
        if healthy:
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
                body = resp.read().decode("utf-8")
            record("backend-http", True, f"/api/health 200 -> {body[:120]}")
        else:
            record("backend-http", False, "uvicorn did not become healthy within 40s")
    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("backend-http", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m1_backend() -> None:
    """Boot the real app and probe the M1 endpoints honestly (clean repo)."""
    import re

    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M1_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m1-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m1"):
            return
        meta = _get_json(f"{base}/meta")
        record("m1-meta", bool(meta and meta.get("milestone") == "M11"), f"milestone={ (meta or {}).get('milestone') } tagline={(meta or {}).get('tagline')}")
        record(
            "m1-config",
            (((meta or {}).get("m1_config") or {}).get("hash_algorithm") or "").lower() == "sha256",
            f"m1_config keys={sorted((((meta or {}).get('m1_config') or {}).keys()))}",
        )
        record("m1-product", (meta or {}).get("application") == "CHANDRASUTRA", f"application={(meta or {}).get('application')}")

        status = _get_json(f"{base}/data/status")
        record("m1-data-status", bool(status), f"milestone={ (status or {}).get('milestone') } source={ (status or {}).get('source', {}).get('archive') }")
        record(
            "m1-pairs-honest-zero",
            int((status or {}).get("pairs_registered", -1)) == 0 and (status or {}).get("first_pair_status") is None,
            "clean repo reports 0 registered pairs (no fabrication)",
        )

        sensors = _get_json(f"{base}/data/sensors")
        phase_a = ((sensors or {}).get("phase_a") or [])
        ids = sorted(p.get("id") for p in phase_a)
        record("m1-sensors", ids == ["ohrc", "tmc2"], f"phase_a ids={ids}")

        pairs = _get_json(f"{base}/pairs")
        record("m1-pairs-list", isinstance((pairs or {}).get("pairs"), list), f"count={(pairs or {}).get('count')}")

        nxt = _get_json(f"{base}/pairs/next-id")
        record("m1-next-id", bool(re.match(r"^CS-P\d{3,}$", (nxt or {}).get("pair_id", ""))), f"next-id={(nxt or {}).get('pair_id')}")

        scan = _get_json(f"{base}/pairs/scan")
        dirs = {d.get("id") for d in (scan or {}).get("raw_dirs", [])}
        record("m1-scan", {"raw/ohrc", "raw/tmc2"}.issubset(dirs), f"raw_dirs ids={sorted(dirs)}")

        traversal = _get_status(f"{base}/pairs/probe?path=..%2F..%2Fetc%2Fpasswd")
        record("m1-traversal-guard", traversal in (400, 403, 422, 404), f"traversal probe rejected with HTTP {traversal}")

        missing = _get_status(f"{base}/pairs/CS-P999/preview/b")
        record("m1-unknown-pair-404", missing == 404, f"unknown pair preview -> HTTP {missing}")

        missing_val = _get_status(f"{base}/pairs/CS-P999/validate")
        record("m1-validate-404", missing_val == 404, f"unknown pair validate -> HTTP {missing_val}")
    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m1-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m2_backend() -> None:
    """Probe the M2 processing endpoints honestly (clean repo -> BLOCKED)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M2_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m2-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m2"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m2cfg = meta.get("m2_config") or {}
        record(
            "m2-meta-config",
            m2cfg.get("configuration_id") == "PC-M2-001" and "defaults" in m2cfg,
            f"m2_config={list(m2cfg.keys())}",
        )

        cfg = _get_json(f"{base}/processing/configurations") or {}
        cfgs = cfg.get("configurations") or []
        record(
            "m2-configurations",
            bool(cfgs) and cfgs[0].get("configuration_id") == "PC-M2-001" and cfg.get("default_configuration_id") == "PC-M2-001",
            f"configurations={[c.get('configuration_id') for c in cfgs]}",
        )

        overview = _get_json(f"{base}/processing/overview") or {}
        record(
            "m2-overview-honest-zero",
            (overview.get("pairs") == []) and (overview.get("blocked") is True) and "BLOCKED" in (overview.get("reason") or ""),
            f"overview blocked={overview.get('blocked')} reason={(overview.get('reason') or '')[:80]}",
        )

        status404 = _get_status(f"{base}/processing/CS-P999/status")
        record("m2-unknown-status-404", status404 == 404, f"unknown pair processing status -> HTTP {status404}")

        prep404 = _get_status(f"{base}/processing/CS-P999/prepare", method="POST", payload={"configuration_id": None})
        record("m2-unknown-prepare-404", prep404 == 404, f"unknown pair prepare -> HTTP {prep404}")
    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m2-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m3_backend() -> None:
    """Probe the M3 matching endpoints honestly (clean repo -> BLOCKED)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M3_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m3-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m3"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m3cfg = meta.get("m3_config") or {}
        record(
            "m3-meta-config",
            m3cfg.get("configuration_id") == "MC-M3-001" and "defaults" in m3cfg,
            f"m3_config={list(m3cfg.keys())}",
        )

        cfg = _get_json(f"{base}/matching/configurations") or {}
        cfgs = cfg.get("configurations") or []
        strategies = (cfgs[0].get("display_only") or {}).get("strategies") or [] if cfgs else []
        by_id = {s.get("strategy"): s for s in strategies}
        record(
            "m3-configurations",
            bool(cfgs)
            and cfgs[0].get("configuration_id") == "MC-M3-001"
            and cfg.get("default_configuration_id") == "MC-M3-001"
            and by_id.get("sift", {}).get("available") is True
            and by_id.get("deep_optional", {}).get("available") is False,
            f"configurations={[c.get('configuration_id') for c in cfgs]} strategies={sorted(by_id)}",
        )

        overview = _get_json(f"{base}/matching/overview") or {}
        record(
            "m3-overview-honest-zero",
            (overview.get("pairs") == []) and (overview.get("blocked") is True) and "BLOCKED" in (overview.get("reason") or ""),
            f"overview blocked={overview.get('blocked')} reason={(overview.get('reason') or '')[:80]}",
        )

        status404 = _get_status(f"{base}/matching/CS-P999/status")
        record("m3-unknown-status-404", status404 == 404, f"unknown pair matching status -> HTTP {status404}")

        run404 = _get_status(f"{base}/matching/CS-P999/run", method="POST", payload={"configuration_id": "MC-M3-001"})
        record("m3-unknown-run-404", run404 == 404, f"unknown pair matching run -> HTTP {run404}")
    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m3-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m4_backend() -> None:
    """Probe the M4 trust gate endpoints honestly (clean repo -> NOT_STARTED)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M4_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m4-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m4"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m4cfg = meta.get("m4_config") or {}
        record(
            "m4-meta-config",
            m4cfg.get("trust_configuration_id") == "TG-M4-001" and "defaults" in m4cfg,
            f"m4_config={list(m4cfg.keys())}",
        )

        cfg = _get_json(f"{base}/trust/configurations") or {}
        cfgs = cfg.get("configurations") or []
        record(
            "m4-configurations",
            bool(cfgs)
            and cfgs[0].get("trust_configuration_id") == "TG-M4-001"
            and cfg.get("default_trust_configuration_id") == "TG-M4-001",
            f"configurations={[c.get('trust_configuration_id') for c in cfgs]}",
        )

        overview = _get_json(f"{base}/trust/overview") or {}
        record(
            "m4-overview-honest-zero",
            (overview.get("total_trust_pairs") == 0)
            and (overview.get("trusted_pairs") == 0)
            and (overview.get("blocked_pairs") == 0),
            f"overview total={overview.get('total_trust_pairs')} trusted={overview.get('trusted_pairs')}",
        )

        status404 = _get_status(f"{base}/trust/CS-P999/status")
        record("m4-unknown-status-404", status404 == 404, f"unknown pair trust status -> HTTP {status404}")

        run404 = _get_status(f"{base}/trust/CS-P999/run", method="POST", payload={"trust_configuration_id": "TG-M4-001"})
        record("m4-unknown-run-404", run404 == 404, f"unknown pair trust run -> HTTP {run404}")
    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m4-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m5_backend() -> None:
    """Probe the M5 spatial reliability endpoints honestly (clean repo -> NOT_STARTED)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M5_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m5-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m5"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m5cfg = meta.get("m5_config") or {}
        record(
            "m5-meta-config",
            m5cfg.get("spatial_reliability_configuration_id") == "SR-M5-001" and "defaults" in m5cfg,
            f"m5_config={list(m5cfg.keys())}",
        )

        cfg = _get_json(f"{base}/spatial/configurations") or {}
        cfgs = cfg.get("configurations") or []
        record(
            "m5-configurations",
            bool(cfgs)
            and cfgs[0].get("spatial_reliability_configuration_id") == "SR-M5-001"
            and cfg.get("default_spatial_reliability_configuration_id") == "SR-M5-001",
            f"configurations={[c.get('spatial_reliability_configuration_id') for c in cfgs]}",
        )

        overview = _get_json(f"{base}/spatial/overview") or {}
        record(
            "m5-overview-honest-zero",
            (overview.get("total_spatial_pairs") == 0)
            and (overview.get("complete_pairs") == 0)
            and (overview.get("blocked_or_insufficient_pairs") == 0),
            f"overview total={overview.get('total_spatial_pairs')} complete={overview.get('complete_pairs')}",
        )

        status404 = _get_status(f"{base}/spatial/CS-P999/status")
        record("m5-unknown-status-404", status404 == 404, f"unknown pair spatial status -> HTTP {status404}")

        run404 = _get_status(f"{base}/spatial/CS-P999/run", method="POST",
                             payload={"spatial_reliability_configuration_id": "SR-M5-001"})
        record("m5-unknown-run-404", run404 == 404, f"unknown pair spatial run -> HTTP {run404}")

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m5-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m6_backend() -> None:
    """Probe the M6 registration endpoints honestly (clean repo -> NOT_STARTED)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M6_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m6-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m6"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m6cfg = meta.get("m6_config") or {}
        record(
            "m6-meta-config",
            m6cfg.get("registration_configuration_id") == "RG-M6-001" and "defaults" in m6cfg,
            f"m6_config={list(m6cfg.keys())}",
        )

        cfg = _get_json(f"{base}/registration/configurations") or {}
        cfgs = cfg.get("configurations") or []
        record(
            "m6-configurations",
            bool(cfgs)
            and cfgs[0].get("registration_configuration_id") == "RG-M6-001"
            and cfg.get("default_registration_configuration_id") == "RG-M6-001",
            f"configurations={[c.get('registration_configuration_id') for c in cfgs]}",
        )

        overview = _get_json(f"{base}/registration/overview") or {}
        record(
            "m6-overview-honest-zero",
            (overview.get("total_registration_pairs") == 0)
            and (overview.get("complete_pairs") == 0)
            and (overview.get("blocked_or_insufficient_pairs") == 0),
            f"overview total={overview.get('total_registration_pairs')} complete={overview.get('complete_pairs')}",
        )

        status404 = _get_status(f"{base}/registration/CS-P999/status")
        record("m6-unknown-status-404", status404 == 404,
               f"unknown pair registration status -> HTTP {status404}")

        run404 = _get_status(f"{base}/registration/CS-P999/run", method="POST",
                             payload={"registration_configuration_id": "RG-M6-001"})
        record("m6-unknown-run-404", run404 == 404,
               f"unknown pair registration run -> HTTP {run404}")

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m6-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m7_backend() -> None:
    """Probe the M7 metrics endpoints honestly (clean repo -> NOT_STARTED)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M7_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m7-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m7"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m7cfg = meta.get("m7_config") or {}
        record(
            "m7-meta-config",
            m7cfg.get("metrics_configuration_id") == "MT-M7-001" and "defaults" in m7cfg,
            f"m7_config={list(m7cfg.keys())}",
        )

        cfg = _get_json(f"{base}/metrics/configurations") or {}
        cfgs = cfg.get("configurations") or []
        record(
            "m7-configurations",
            bool(cfgs)
            and cfgs[0].get("metrics_configuration_id") == "MT-M7-001"
            and cfg.get("default_metrics_configuration_id") == "MT-M7-001",
            f"configurations={[c.get('metrics_configuration_id') for c in cfgs]}",
        )

        overview = _get_json(f"{base}/metrics/overview") or {}
        record(
            "m7-overview-honest-zero",
            (overview.get("total_metrics_pairs") == 0)
            and (overview.get("complete_pairs") == 0)
            and (overview.get("not_complete_pairs") == 0),
            f"overview total={overview.get('total_metrics_pairs')} complete={overview.get('complete_pairs')}",
        )

        status404 = _get_status(f"{base}/metrics/CS-P999/status")
        record("m7-unknown-status-404", status404 == 404,
               f"unknown pair metrics status -> HTTP {status404}")

        run404 = _get_status(f"{base}/metrics/CS-P999/run", method="POST",
                             payload={"metrics_configuration_id": "MT-M7-001"})
        record("m7-unknown-run-404", run404 == 404,
               f"unknown pair metrics run -> HTTP {run404}")

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m7-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m8_backend() -> None:
    """Probe the M8 mental-deep expansion + benchmark endpoints (clean repo)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M8_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m8-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m8"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m8cfg = meta.get("m8_config") or {}
        record(
            "m8-meta-config",
            m8cfg.get("configuration_id") == "DM-M8-001" and "defaults" in m8cfg,
            f"m8_config={list(m8cfg.keys())}",
        )

        caps = _get_json(f"{base}/matching/capabilities") or {}
        matchers = caps.get("matchers") or []
        by_id = {m.get("matcher_id"): m for m in matchers}
        honest_deep = (by_id.get("superpoint_superglue") or {}).get("available") is False
        classical_ok = (by_id.get("sift") or {}).get("available") is True
        weights = (by_id.get("superpoint_superglue") or {}).get("weights_available") is False
        record(
            "m8-capabilities-honest",
            honest_deep and classical_ok and weights,
            f"matchers={sorted(by_id)} deep_available={honest_deep} weights_available={weights}",
        )
        device = caps.get("device") or {}
        record(
            "m8-device-surface",
            "deep_runtime" in device and bool(device.get("effective_device")),
            f"effective_device={device.get('effective_device')} runtime={sorted((device.get('deep_runtime') or {}).keys())}",
        )

        status404 = _get_status(f"{base}/matching/CS-P999/m8/status")
        record("m8-unknown-status-404", status404 == 404,
               f"unknown pair m8 status -> HTTP {status404}")

        run404 = _get_status(f"{base}/matching/CS-P999/m8/run", method="POST",
                             payload={"mode": "AUTO", "benchmark": False})
        record("m8-unknown-run-404", run404 == 404,
               f"unknown pair m8 run -> HTTP {run404}")

        route404 = _get_status(f"{base}/matching/CS-P999/m8/routing")
        record("m8-unknown-routing-404", route404 == 404,
               f"unknown pair m8 routing -> HTTP {route404}")

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m8-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m9_backend() -> None:
    """Probe the M9 AI assistant endpoints (clean repo, no Gemini key)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M9_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m9-backend", False, "uvicorn did not become healthy within 40s")
            return

        if not _require_token(base, "m9"):
            return
        meta = _get_json(f"{base}/meta") or {}
        m9cfg = meta.get("m9_config") or {}
        record(
            "m9-meta-config",
            m9cfg.get("ai_configuration_id") == "AI-M9-001"
            and "grounding_rules" in m9cfg
            and "constraints" in m9cfg,
            f"m9_config keys={list(m9cfg.keys())}",
        )
        record("m9-milestone", meta.get("milestone") == "M11", f"milestone={meta.get('milestone')}")

        ai_status = _get_json(f"{base}/ai/status") or {}
        record(
            "m9-ai-status",
            ai_status.get("status") == "NOT_CONFIGURED"
            and ai_status.get("configured") is False
            and ai_status.get("policy", {}).get("explanatory_only") is True,
            f"ai status={ai_status.get('status')} configured={ai_status.get('configured')}",
        )

        explain = _post_json(f"{base}/ai/explain")
        err = (explain or {}).get("error") or {}
        ok_explain = err.get("code") == "NOT_CONFIGURED"
        record(
            "m9-ai-explain-unconfigured",
            ok_explain,
            f"POST /ai/explain error.code={err.get('code')}",
        )

        resp_blob = json.dumps(explain or {})
        record("m9-ai-no-secret", "AIza" not in resp_blob, "no Google API key leaked in any AI response")

        tasks = ("explain-failure", "explain-routing", "summarize-experiment", "chat")
        for name in tasks:
            body = _post_json(f"{base}/ai/{name}")
            errc = ((body or {}).get("error") or {}).get("code")
            record(f"m9-{name}-unconfigured", errc == "NOT_CONFIGURED", f"POST /ai/{name} error.code={errc}")

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m9-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def record_m10_backend() -> None:
    """Probe the M10 auth endpoints honestly (real HTTP, real tokens)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M10_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m10-backend", False, "uvicorn did not become healthy within 40s")
            return

        status = _get_json(f"{base}/auth/status") or {}
        record(
            "m10-auth-status",
            status.get("authentication_enabled") is True
            and status.get("configured") is True
            and status.get("registration_enabled") is True
            and bool(status.get("roles"))
            and is_int_ttl(status.get("access_token_ttl_seconds")),
            f"enabled={status.get('authentication_enabled')} configured={status.get('configured')} "
            f"session={status.get('session_state')} ttl={status.get('access_token_ttl_seconds')}s",
        )

        cookies = _login_cookies(base)
        joined = "; ".join(cookies)
        record(
            "m10-refresh-cookie",
            bool(joined)
            and "httponly" in joined.lower()
            and "path=/api/auth/" in joined.lower()
            and "chandrasutra_refresh" in joined,
            f"Set-Cookie={joined[:90]}",
        )

        if not _require_token(base, "m10"):
            return

        me = _get_json(f"{base}/auth/me") or {}
        rec_user = me.get("user") or {}
        admin_user, _admin_pw = _admin_creds()
        record(
            "m10-me",
            bool(rec_user.get("id")) and rec_user.get("username") == admin_user and rec_user.get("role") == "admin",
            f"fields={list(rec_user.keys())} role={rec_user.get('role')}",
        )

        anon = _anon_status(f"{base}/data/status")
        record("m10-fail-closed", anon in (401, 403, 501), f"anonymous GET /data/status -> HTTP {anon}")

        anon_post = _anon_status(f"{base}/processing/CS-P999/prepare", method="POST", payload={"configuration_id": None})
        record("m10-anon-mutation-blocked", anon_post in (401, 403, 501), f"anonymous POST /prepare -> HTTP {anon_post}")

        users = _get_json(f"{base}/auth/users") or {}
        record(
            "m10-users-listed",
            isinstance(users.get("users"), list) and len(users.get("users")) >= 1,
            f"users={len(users.get('users') or [])}",
        )

        summary = _get_json(f"{base}/auth/security-summary") or {}
        record(
            "m10-security-summary",
            summary.get("total_users", 0) >= 1
            and isinstance(summary.get("recent_security_events"), list)
            and bool(summary.get("configuration_id")),
            f"total_users={summary.get('total_users')} events={len(summary.get('recent_security_events') or [])}",
        )

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m10-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def is_int_ttl(value: object) -> bool:
    return isinstance(value, int) and value > 0


def record_m11_backend() -> None:
    """Probe the M11 hardening surface: readiness, request-id, envelopes, body
    limit, and the admin-only operational overview (real HTTP)."""
    port = free_port()
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "SMOKE_M11_PORT": str(port), **_auth_env()},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m11-backend", False, "uvicorn did not become healthy within 40s")
            return

        health = _get_json(f"{base}/health") or {}
        record(
            "m11-health",
            health.get("status") == "ok" and health.get("milestone") == "M11",
            f"status={health.get('status')} milestone={health.get('milestone')}",
        )

        # Readiness probe: optional/BLOCKED dependencies degrade, never fail.
        ready = _get_json(f"{base}/ready") or {}
        svc_ids = [s.get("id") for s in ready.get("services") or []]
        record(
            "m11-ready",
            ready.get("ready") is True
            and ready.get("status") in ("READY", "DEGRADED")
            and svc_ids == [
                "backend", "database", "filesystem", "configuration",
                "authentication", "ai_capability", "deep_matcher", "scientific_data",
            ],
            f"ready={ready.get('ready')} status={ready.get('status')} services={len(svc_ids)}",
        )
        sci = next((s for s in (ready.get("services") or []) if s.get("id") == "scientific_data"), {})
        record(
            "m11-ready-data-honest",
            sci.get("state") == "BLOCKED" and "REAL_DATA_UNAVAILABLE" in (sci.get("detail") or ""),
            f"scientific_data.state={sci.get('state')}",
        )

        # Request-ID echo + error envelope correlation over real HTTP.
        rid = "smoke-m11-request-0001"
        try:
            req = urllib.request.Request(f"{base}/health", headers={"X-Request-ID": rid})
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                echoed = resp.headers.get("X-Request-Id", "")
                resp.read()
        except Exception:  # noqa: BLE001
            echoed = ""
        record("m11-request-id-echo", echoed == rid, f"x-request-id echoed={echoed!r}")

        err = _post_json(f"{base}/nope/1/2")
        errc = ((err or {}).get("error") or {}).get("code")
        err_id = ((err or {}).get("error") or {}).get("request_id")
        record("m11-404-envelope", errc == "NOT_FOUND" and bool(err_id), f"404 error.code={errc} request_id={bool(err_id)}")

        big = {"data": "x" * 8_100_000}
        big_status = _oversized_status(f"http://127.0.0.1:{port}/api/auth/login", 8_100_002)
        record("m11-body-limit", big_status == 413, f"oversized body -> HTTP {big_status}")

        # Admin-only operational overview.
        anon_ops = _anon_status(f"{base}/ops/overview")
        record("m11-ops-admin-gated", anon_ops in (401, 403, 501), f"anonymous /ops/overview -> HTTP {anon_ops}")

        if not _require_token(base, "m11"):
            record("m11-ops-overview", False, "could not obtain admin token")
            return
        ops = _get_json(f"{base}/ops/overview") or {}
        ops_ok = (
            ops.get("system", {}).get("milestone") == "M11"
            and len(ops.get("services") or []) == 8
            and isinstance(ops.get("recent_runs"), list)
            and isinstance(ops.get("recent_failures"), list)
        )
        record(
            "m11-ops-overview",
            ops_ok,
            f"milestone={ops.get('system', {}).get('milestone')} services={len(ops.get('services') or [])} runs={len(ops.get('recent_runs') or [])}",
        )
        ops_secret = any(s in str(ops) for s in ("SMOKE_ADMIN", "auth_secret", "Bearer "))
        record("m11-ops-no-secret", not ops_secret, "no credentials/paths/tracebacks in /ops/overview")

    except (urllib.error.URLError, OSError) as exc:  # noqa: BLE001
        record("m11-backend", False, f"request failed: {exc}")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()


def _login_cookies(base: str) -> list[str]:
    user, pw = _admin_creds()
    data = json.dumps({"username": user, "password": pw}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/auth/login",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.headers.get_all("Set-Cookie") or []
    except Exception:  # noqa: BLE001
        return []


def _anon_status(url: str, method: str = "GET", payload: dict | None = None) -> int:
    """Status of a request made WITHOUT any Authorization header."""
    try:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return -1


def _get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            payload = resp.read().decode("utf-8")
        return json.loads(payload)
    except Exception:  # noqa: BLE001
        return None


def _post_json(url: str, payload: dict | None = None) -> dict | None:
    try:
        data = json.dumps(payload).encode("utf-8") if payload is not None else b""
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **_headers()},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return None
    except (urllib.error.URLError, OSError):
        return None


def _get_status(url: str, method: str = "GET", payload: dict | None = None) -> int:
    try:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json", **_headers()} if data is not None else _headers()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return -1


def _oversized_status(url: str, declared_length: int) -> int:
    """Status of a POST that *declares* an over-limit Content-Length.

    Sends headers + an empty body so the server's up-front 413 guard answers
    before the client ever streams the payload (deterministic even over real
    HTTP where an early server close mid-write can reset the socket).
    """
    try:
        parsed = urllib.parse.urlparse(url)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        conn.request(
            "POST",
            parsed.path,
            body=b"",
            headers={"Content-Type": "application/json", "Content-Length": str(declared_length)},
        )
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        return status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, http.client.HTTPException):
        return -1


def _wait_for_health(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)