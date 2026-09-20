"""M11 performance measurement — CHANDRASUTRA (SIH26166).

Runs the real backend (in-process ASGI via TestClient, same code path as the
test suites and uvicorn) against a synthetic correlated pair and records honest
engineering measurements:

  * request latency percentiles for representative endpoints
  * error-envelope / correlation overhead (404, 422, X-Request-ID echo)
  * auth round-trips (bootstrap login excluded, /me measured)
  * the full guarded pipeline run (M2 prepare -> M3 match -> M4 trust ->
    M5 spatial -> M6 registration -> M7 metrics) end to end under RunLock
  * atomic write throughput (JSON / NPY / NPZ) vs plain writes
  * RunLock acquire/release overhead, including single-writer contention

Everything below is measured on this machine right now — no cached or
fabricated figures. Output is written to perf/results.md and printed.

Run:  .\\.venv\\Scripts\\python.exe scripts\\measure_performance.py
"""

from __future__ import annotations

import json
import logging
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("LOG_LEVEL", "ERROR")

import numpy as np  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.data import ensure_derived_directories  # noqa: E402
from backend.app.hardening import (  # noqa: E402
    RunLock,
    atomic_write_json,
    atomic_write_npy,
    atomic_write_npz,
)
from backend.app.main import create_app  # noqa: E402
from tests.fixturegen import write_correlated_fixtures  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "tests"))

from tests.auth_helpers import ADMIN_PASSWORD, ADMIN_USERNAME, authed_client_for_app  # noqa: E402
from tests.auth_helpers import configure_auth  # noqa: E402


def pct(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    n = len(ordered)
    def q(p: float) -> float:
        if n == 0:
            return 0.0
        idx = int(p * (n - 1))
        return ordered[idx]
    return {
        "mean": statistics.mean(samples) if samples else 0.0,
        "p50": q(0.50),
        "p95": q(0.95),
        "p99": q(0.99),
    }


def run_latency(name, client, path, method="GET", payload=None, n=150):
    samples: list[float] = []
    call = getattr(client, method.lower())
    for _ in range(n):
        t0 = time.perf_counter()
        resp = call(path, json=payload) if payload is not None else call(path)
        dt = (time.perf_counter() - t0) * 1000.0
        assert resp.status_code < 500, (path, resp.status_code, resp.text[:200])
        samples.append(dt)
    return name, pct(samples)


def main() -> int:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("backend.app.middleware").setLevel(logging.WARNING)

    tmp = Path(tempfile.mkdtemp(prefix="cs_perf_"))
    write_correlated_fixtures(tmp)

    settings = Settings(data_root=str(tmp), _env_file=None)
    configure_auth(settings)
    ensure_derived_directories(settings)

    app = create_app(settings=settings)
    print(f"environment: {platform.platform()} | {platform.python_version()} "
          f"| cpus={os.cpu_count()} | {platform.machine()}")
    print(f"workspace:   {tmp}")
    print("fixtures:    synthetic correlated OHRC/TMC-2 pair (TEST FIXTURE, not real data)\n")

    rows: list[tuple[str, str]] = []
    summary: list[str] = []
    results: list[str] = []

    def R(metric, value):
        rows.append((metric, value))
        summary.append(f"{metric}: {value}")

    with authed_client_for_app(app) as c:
        # ------------------------------------------------------------ register pair
        t0 = time.perf_counter()
        reg = c.post("/api/pairs/register", json={
            "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
            "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
            "overlap_status": "UNKNOWN",
        })
        assert reg.status_code == 200, reg.text
        pair_id = reg.json()["pair_id"]
        val = c.post(f"/api/pairs/{pair_id}/validate").json()
        assert val["status"] == "VALID", val
        R("pair register+validate", f"{(time.perf_counter() - t0) * 1000:.0f} ms")

        # ------------------------------------------------------------ latency probes
        for name, path, method, n, payload in (
            ("GET /api/health", "/api/health", "GET", 200, None),
            ("GET /api/ready", "/api/ready", "GET", 200, None),
            ("GET /api/meta", "/api/meta", "GET", 200, None),
            ("GET /api/data/status", "/api/data/status", "GET", 200, None),
            ("GET /api/pairs", "/api/pairs", "GET", 200, None),
            ("GET /api/pairs/next-id", "/api/pairs/next-id", "GET", 200, None),
            ("GET /api/ops/overview", "/api/ops/overview", "GET", 60, None),
            ("404 envelope (GET /api/nope)", "/api/nope/1/2", "GET", 200, None),
            ("422 envelope (auth/login bad type)", "/api/auth/login", "POST", 100, {"username": 123, "password": "x"}),
            ("GET /api/auth/me (token)", "/api/auth/me", "GET", 200, None),
        ):
            name, stats = run_latency(name, c, path, method, payload, n)
            R(name, f"{{\"mean_ms\": {stats['mean']:.2f}, \"p50\": {stats['p50']:.2f}, "
                    f"\"p95\": {stats['p95']:.2f}, \"p99\": {stats['p99']:.2f}}}")

        # X-Request-ID correlation echo.
        t0 = time.perf_counter()
        resp = c.get("/api/health", headers={"X-Request-ID": "perf-req-0001"})
        echoed = resp.headers.get("x-request-id", "")
        dt = (time.perf_counter() - t0) * 1000.0
        R("request-id echo", f"echoed={echoed == 'perf-req-0001'} ({dt:.2f} ms)")

        # ------------------------------------------------------------ full pipeline run
        geom = {
            "source": "TEST_FIXTURE",
            "reference": "Synthetic correlated scene for benchmark (software validation only).",
            "products": {
                "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 0.5},
                "tmc2": {"row_offset_m": -2.0, "col_offset_m": -2.0, "gsd_m": 0.5},
            },
        }
        stages: dict[str, tuple[str, float]] = {}

        def mark(stage: str) -> "callable":
            t0 = time.perf_counter()

            def done(state: str) -> None:
                stages[stage] = (state, (time.perf_counter() - t0) * 1000.0)

            return done

        d = mark("M2 prepare")
        prep = c.post(f"/api/processing/{pair_id}/prepare", json={"geometry": geom}).json()
        d(prep["state"])

        d = mark("M3 match")
        m3 = c.post(f"/api/matching/{pair_id}/run", json={"configuration_id": None}).json()
        d(m3["state"])

        d = mark("M4 trust gate")
        m4 = c.post(f"/api/trust/{pair_id}/run", json={"trust_configuration_id": "TG-M4-001"}).json()
        d(m4["gate_state"])

        d = mark("M5 spatial")
        m5 = c.post(f"/api/spatial/{pair_id}/run",
                    json={"spatial_reliability_configuration_id": "SR-M5-001"}).json()
        d(m5["state"])

        m5_summary = c.get(f"/api/spatial/{pair_id}/summary").json().get("summary") or {}
        sel_outcome = m5_summary.get("selection_outcome") or (m5_summary.get("selection") or {}).get("outcome")
        sel_count = (m5_summary.get("selection") or {}).get("selected_correspondence_count")
        pipeline_note = f"selection={sel_outcome} selected={sel_count}"

        d = mark("M6 registration")
        m6 = c.post(f"/api/registration/{pair_id}/run",
                    json={"registration_configuration_id": "RG-M6-001"}).json()
        d(m6["state"])

        d = mark("M7 metrics")
        m7 = c.post(f"/api/metrics/{pair_id}/run", json={}).json()
        d(m7["state"])

        wall = sum(t for _s, t in stages.values())
        R("guarded pipeline M2->M7 (real engines)", f"{wall:.0f} ms wall; {pipeline_note}; M6={m6['state']} M7={m7['state']}")
        for stage, (_st, dt) in stages.items():
            R(f"  stage {stage} (guarded run)", f"{_st} in {dt:.0f} ms")

        # Re-running an already-complete stage must be handled by the run guard
        # (never spawned), so a second metrics POST is cheap and still guarded.
        t0 = time.perf_counter()
        again = c.post(f"/api/metrics/{pair_id}/run", json={}).json()
        again_dt = (time.perf_counter() - t0) * 1000.0
        R("guarded re-run same stage (no duplicate work)", f"{again_dt:.0f} ms ({again['state']})")

    # The synthetic engine chain can defeat the M5 selection threshold without
    # the code being wrong (honest INSUFFICIENT outcome). To still measure the
    # M6/M7 engines, time them against a suite-validated M2->M5 tree built with
    # the same real services on a fresh workspace. Both cases are reported
    # above/below.
    from tests import test_m7 as m7h  # noqa: PLC0415

    tree_settings = Settings(data_root=str(Path(tempfile.mkdtemp(prefix="cs_perf_tree_"))), _env_file=None)
    tree = m7h._ready_for_m7(tree_settings, pair_id)
    rg_svc = m7h._get_m6_svc(tree)
    t0 = time.perf_counter()
    rg_status = rg_svc.run(pair_id)
    rg_dt = (time.perf_counter() - t0) * 1000.0
    R("M6 registration engine (suite tree)", f"{rg_dt:.0f} ms -> {rg_status['state']}")

    mt_svc = m7h._get_m7_svc(tree)
    t0 = time.perf_counter()
    mt_status = mt_svc.run(pair_id)
    mt_dt = (time.perf_counter() - t0) * 1000.0
    R("M7 metrics engine (suite tree)", f"{mt_dt:.0f} ms -> {mt_status['state']}")

    # ------------------------------------------------------------ run guard
    lock_dir = tmp / "perf_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    for _ in range(300):
        with RunLock(lock_dir, budget_seconds=99999, tag="perf-serial"):
            pass
    R("RunLock acquire+release (uncontended)", f"{(time.perf_counter() - t0) * 1000 / 300:.3f} ms/op")

    workers = 6
    barrier = threading.Barrier(workers)
    results: list[tuple[str, float]] = []

    def contend(idx: int, tag: str) -> None:
        try:
            barrier.wait()
            t0 = time.perf_counter()
            with RunLock(lock_dir, budget_seconds=99999, tag=tag):
                results.append((f"worker{idx}", (time.perf_counter() - t0) * 1000.0))
                time.sleep(0.01)
        except Exception as exc:  # noqa: BLE001
            results.append((f"worker{idx}-rejected", getattr(exc, "code", type(exc).__name__)))

    t0 = time.perf_counter()
    threads = [threading.Thread(target=contend, args=(i, "perf-contend")) for i in range(workers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    dt = (time.perf_counter() - t0) * 1000.0
    holders = [r for r in results if not r[0].endswith("-rejected")]
    rejected = [r for r in results if r[0].endswith("-rejected")]
    R("RunLock single-writer guard (6 concurrent workers)",
      f"holders={len(holders)} (JOB_ALREADY_RUNNING rejected={len(rejected)}); total {dt:.0f} ms")

    # ------------------------------------------------------------ atomic write throughput
    adir = tmp / "perf_atomic"
    adir.mkdir(parents=True, exist_ok=True)
    payload = {"configuration_id": "SR-M5-001", "values": [1, 2, 3]}
    arr = np.arange(700 * 520, dtype=np.uint16).reshape(700, 520)

    def plain_write(path: Path, writer) -> float:
        path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.perf_counter()
        writer(path)
        with open(path, "rb") as f:
            f.read()
        return (time.perf_counter() - t0) * 1000.0

    def atomic_json(path: Path) -> None:
        atomic_write_json(path, payload)

    def plain_json(path: Path) -> None:
        path.write_text(json.dumps(payload), encoding="utf-8")

    def atomic_npy(path: Path) -> None:
        atomic_write_npy(path, arr)

    def plain_npy(path: Path) -> None:
        np.save(path, arr)

    def atomic_npz(path: Path) -> None:
        atomic_write_npz(path, selected=arr, mask=arr > 32000)

    def plain_npz(path: Path) -> None:
        np.savez_compressed(path, selected=arr, mask=arr > 32000)

    for label, atomic, plain in (
        ("atomic_write_json vs direct", atomic_json, plain_json),
        ("atomic_write_npy vs np.save", atomic_npy, plain_npy),
        ("atomic_write_npz vs savez_compressed", atomic_npz, plain_npz),
    ):
        n = 20
        a_s = []
        p_s = []
        for i in range(n):
            suffix = "json" if "json" in label else ("npz" if "npz" in label else "npy")
            a_s.append(plain_write(adir / f"a_{i}.{suffix}", atomic))
            p_s.append(plain_write(adir / f"p_{i}.{suffix}", plain))
        R(f"{label} (n={n})",
          f"atomic_mean_ms={statistics.mean(a_s):.2f} | plain_mean_ms={statistics.mean(p_s):.2f} "
          f"| ratio={statistics.mean(a_s) / max(statistics.mean(p_s), 1e-9):.2f}x")

    # ------------------------------------------------------------ output
    md = [
        "# M11 Measured Performance — CHANDRASUTRA (SIH26166)",
        "",
        f"- Machine: {platform.platform()}",
        f"- Python: {platform.python_version()} | CPUs: {os.cpu_count()}",
        "- Method: real backend app over TestClient (same ASGI path as uvicorn), synthetic correlated OHRC/TMC-2 fixtures.",
        "- Every figure is measured live by `scripts/measure_performance.py`; nothing is cached or fabricated.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for metric, value in rows:
        md.append(f"| {metric} | {value} |")

    out = Path(REPO_ROOT / "perf" / "results.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())