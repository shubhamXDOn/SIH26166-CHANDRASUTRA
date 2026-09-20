# M11 Measured Performance — CHANDRASUTRA (SIH26166)

- Machine: Windows-11-10.0.26200-SP0
- Python: 3.14.1 | CPUs: 12
- Method: real backend app over TestClient (same ASGI path as uvicorn), synthetic correlated OHRC/TMC-2 fixtures.
- Every figure is measured live by `scripts/measure_performance.py`; nothing is cached or fabricated.

| Metric | Value |
| --- | --- |
| pair register+validate | 233 ms |
| GET /api/health | {"mean_ms": 3.83, "p50": 4.00, "p95": 5.08, "p99": 5.33} |
| GET /api/ready | {"mean_ms": 17.79, "p50": 15.71, "p95": 20.36, "p99": 21.91} |
| GET /api/meta | {"mean_ms": 6.45, "p50": 6.67, "p95": 8.19, "p99": 8.83} |
| GET /api/data/status | {"mean_ms": 16.89, "p50": 17.24, "p95": 21.80, "p99": 24.69} |
| GET /api/pairs | {"mean_ms": 12.19, "p50": 12.13, "p95": 15.13, "p99": 16.02} |
| GET /api/pairs/next-id | {"mean_ms": 11.16, "p50": 11.47, "p95": 15.14, "p99": 16.12} |
| GET /api/ops/overview | {"mean_ms": 105.00, "p50": 106.59, "p95": 142.90, "p99": 161.74} |
| 404 envelope (GET /api/nope) | {"mean_ms": 3.25, "p50": 3.37, "p95": 4.58, "p99": 5.67} |
| 422 envelope (auth/login bad type) | {"mean_ms": 3.82, "p50": 3.82, "p95": 5.18, "p99": 6.24} |
| GET /api/auth/me (token) | {"mean_ms": 10.89, "p50": 10.85, "p95": 13.67, "p99": 14.51} |
| request-id echo | echoed=True (5.06 ms) |
| guarded pipeline M2->M7 (real engines) | 15642 ms wall; selection=INSUFFICIENT selected=0; M6=BLOCKED M7=BLOCKED |
|   stage M2 prepare (guarded run) | READY_FOR_MATCHING in 1070 ms |
|   stage M3 match (guarded run) | COMPLETE in 666 ms |
|   stage M4 trust gate (guarded run) | COMPLETE in 5123 ms |
|   stage M5 spatial (guarded run) | COMPLETE in 8702 ms |
|   stage M6 registration (guarded run) | BLOCKED in 41 ms |
|   stage M7 metrics (guarded run) | BLOCKED in 41 ms |
| guarded re-run same stage (no duplicate work) | 36 ms (BLOCKED) |
| M6 registration engine (suite tree) | 1028 ms -> COMPLETE |
| M7 metrics engine (suite tree) | 258 ms -> COMPLETE |
| RunLock acquire+release (uncontended) | 20.432 ms/op |
| RunLock single-writer guard (6 concurrent workers) | holders=1 (JOB_ALREADY_RUNNING rejected=5); total 28 ms |
| atomic_write_json vs direct (n=20) | atomic_mean_ms=8.48 | plain_mean_ms=5.35 | ratio=1.58x |
| atomic_write_npy vs np.save (n=20) | atomic_mean_ms=19.57 | plain_mean_ms=18.98 | ratio=1.03x |
| atomic_write_npz vs savez_compressed (n=20) | atomic_mean_ms=66.56 | plain_mean_ms=64.38 | ratio=1.03x |
