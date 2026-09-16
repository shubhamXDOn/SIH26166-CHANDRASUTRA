"""SIH26166 — Milestone M1 environment smoke test.

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
    * frontend render + frontend->backend connectivity

Usage:
    .venv\\Scripts\\python.exe smoke_test.py

Exits non-zero if anything fails. NEVER reports PASS on failure.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_PORT = int(os.environ.get("SMOKE_PORT", "8137"))

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    CHECKS.append((name, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {name}: {detail}")


def main() -> int:
    print(f"CHANDRASUTRA (SIH26166) M1/M2/M3 smoke test  |  repo root: {REPO_ROOT}")
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
    env = {**os.environ, "VITE_PROXY_TARGET": f"http://127.0.0.1:{backend_port}", "VITE_PORT": str(vite_port)}
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
            env={**os.environ, "SMOKE_PORT": str(port)},
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
            env={**os.environ, "SMOKE_M1_PORT": str(port)},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m1-backend", False, "uvicorn did not become healthy within 40s")
            return

        meta = _get_json(f"{base}/meta")
        record("m1-meta", bool(meta and meta.get("milestone") == "M3"), f"milestone={ (meta or {}).get('milestone') } tagline={(meta or {}).get('tagline')}")
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
            env={**os.environ, "SMOKE_M2_PORT": str(port)},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m2-backend", False, "uvicorn did not become healthy within 40s")
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
            env={**os.environ, "SMOKE_M3_PORT": str(port)},
        )
        base = f"http://127.0.0.1:{port}/api"
        if not _wait_for_health(f"{base}/health", timeout=40):
            record("m3-backend", False, "uvicorn did not become healthy within 40s")
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


def _get_json(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            payload = resp.read().decode("utf-8")
        return json.loads(payload)
    except Exception:  # noqa: BLE001
        return None


def _get_status(url: str, method: str = "GET", payload: dict | None = None) -> int:
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