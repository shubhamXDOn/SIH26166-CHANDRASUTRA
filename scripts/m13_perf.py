"""M13 performance measurement: honest local API timings.

Measures median/min/max request latency for the release-facing routes on the
local runtime only, using an authenticated TestClient against a seeded release
data root. Hosted latency is deliberately reported as NOT_MEASURED — no public
deployment exists in this environment, and no number may be invented for it.

Output: ``perf/m13_performance.json``. ``scripts/m13_release_prep.py`` copies
it into the data root so ``GET /api/m13/measurements`` can serve it.

Usage:
    python scripts/m13_perf.py [--data-root data] [--out perf/m13_performance.json] [--samples 5]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings, rfc3339_now
from backend.app.main import create_app
from fastapi.testclient import TestClient

AUTH_SECRET = "m13-perf-secret-0123456789abcdef0123456789abcdef"
ADMIN_USERNAME = "perf-admin"
ADMIN_PASSWORD = "Perf-1234-test!"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--out", default=str(ROOT / "perf" / "m13_performance.json"))
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()

    data_root = Path(args.data_root).expanduser()
    if not (data_root / "final_evidence").is_dir():
        print(f"ERROR: no seeded evidence at {data_root}. Run scripts/m13_release_prep.py first.",
              file=sys.stderr)
        return 1

    settings = Settings(
        data_root=str(data_root),
        auth_secret_key=AUTH_SECRET,
        auth_bootstrap_admin_username=ADMIN_USERNAME,
        auth_bootstrap_admin_password=ADMIN_PASSWORD,
        _env_file=None,
    )
    app = create_app(settings=settings)
    probe = TestClient(app)
    try:
        login = probe.post("/api/auth/login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    finally:
        probe.close()

    exp_id = next((p.name for p in sorted((data_root / "final_evidence").glob("EXP-*/"))
                   if (p / "manifest.json").is_file()), None)

    routes = [
        ("GET", "/api/health", None, False),
        ("GET", "/api/m13/status", None, True),
        ("GET", "/api/m13/evidence", None, True),
        ("GET", f"/api/m13/evidence/{exp_id}", None, True),
        ("GET", "/api/m13/reports", None, True),
        ("GET", "/api/m13/report/M12_FINAL_SCIENTIFIC_REPORT.md", None, True),
        ("GET", "/api/m13/record/reproducibility", None, True),
        ("GET", "/api/m13/provenance", None, True),
        ("POST", "/api/m13/demo/reset", {}, True),
    ]

    client = TestClient(app)
    try:
        headers = {"Authorization": f"Bearer {token}"}
        samples: dict[str, dict] = {}
        for method, path, payload, authed in routes:
            h = headers if authed else {}
            timed: list[float] = []
            for i in range(args.samples + 1):
                start = time.perf_counter()
                resp = client.request(method, path, json=payload, headers=h)
                elapsed = (time.perf_counter() - start) * 1000
                if resp.status_code != 200:
                    print(f"  WARN {method} {path} -> {resp.status_code}", file=sys.stderr)
                    continue
                if i > 0:  # first call is warm-up
                    timed.append(elapsed)
            if timed:
                samples[path] = {
                    "method": method,
                    "median_ms": round(statistics.median(timed), 1),
                    "min_ms": round(min(timed), 1),
                    "max_ms": round(max(timed), 1),
                    "samples": len(timed),
                }
    finally:
        client.close()

    payload = {
        "schema_version": "M13-PERF-001",
        "application": "CHANDRASUTRA (SIH26166)",
        "status": "MEASURED_LOCALLY" if samples else "NOT_MEASURED",
        "hosted": "NOT_MEASURED",
        "hosted_note": (
            "No public deployment was provisioned from this offline environment; "
            "hosted latency was not measured and is not estimated."
        ),
        "measured_at_utc": rfc3339_now(),
        "environment": "local development runtime",
        "warmup": "one un-timed call per route before sampling",
        "routes": samples,
    }
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {out} with {len(samples)} route(s):")
    for path, s in sorted(payload["routes"].items()):
        print(f"  {s['method']:<4} {path:<46} median={s['median_ms']}ms  min={s['min_ms']}  max={s['max_ms']}")
    print("hosted latency: NOT_MEASURED (honest).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())