"""SIH26166 — M0 environment smoke test.

Validates, end to end:
    * Python environment
    * dependency imports
    * configuration (YAML + runtime settings)
    * data directory architecture
    * FastAPI startup over a real HTTP socket
    * /api/health response

Usage:
    .venv\\Scripts\\python.exe smoke_test.py

Exits non-zero if anything fails. NEVER reports PASS on failure.
"""

from __future__ import annotations

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
    print(f"SIH26166 M0 smoke test  |  repo root: {REPO_ROOT}")
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