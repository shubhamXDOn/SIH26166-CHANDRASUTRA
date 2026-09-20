# M11 Report — Hardening, Reliability, Performance & Jury-Readiness (CHANDRASUTRA · SIH26166)

**Milestone:** M11 — make the M0–M10 pipeline stable, secure, observable, fast,
recoverable and jury-demo reliable **without new features, fabricated results,
or scientific retuning.**

- **Status: DONE (engineering)** — 42-case hardening bug-hunt (B01–B40), all
  existing suites regression-green, live environment smoke **101/101 PASS**,
  measured performance table reproduced by `scripts/measure_performance.py`.
- M11 adds **no new science**: every scientific stage still honestly reports
  its true state, and real-data runs remain **BLOCKED** on PRADAN approval.

---

## 1. What M11 delivers

1. **Crash-safe atomic artifacts.** `backend/app/hardening.py` provides
   `atomic_write_json / atomic_write_npy / atomic_write_npz / atomic_write_text
   / atomic_write_bytes` — temp-file + `os.replace` + directory fsync, with
   temp-file cleanup. Every M2–M7 service status/summary/manifest JSON, M4 tile
   trust JSON, M5 selected-correspondences NPZ, M6 registered-image/mask NPY and
   M7 report artefact is written atomically. A crash can leave the *previous*
   valid artifact — never a truncated or half-written one.
2. **Single-writer run guard with interruption reconciliation.** `RunLock`
   (in-process registry + on-disk `.run.lock` mutex) rejects concurrent runs on
   the same pair with `409 JOB_ALREADY_RUNNING` — parallel runs are **never**
   started. A lock older than the stale budget (`RUN_STALE_BUDGET_SECONDS`,
   default 600 s) is treated as a crash leftover: the interrupted run is first
   marked honest `FAILED / RUN_INTERRUPTED`, then the new run may proceed.
   `guard_run` wraps every pipeline stage endpoint and records bounded run
   events (`_MAX_RUN_EVENTS`) for the ops surface.
3. **Honest timeout states.** A running-out-of-budget stage never reports
   `COMPLETE`. M4 Trust Gate: `timed_out → FAILED` with `block_code="TIMEOUT"`
   and reason `TG_NOT_RUN`; `summary.json` carries `"timed_out": true`. M5
   Spatial: `timeout_flagged → FAILED` with `block_code=SPATIAL_TIMEOUT` and
   reason `SPATIAL_RUNTIME_TIMEOUT`. Corresponding M2/M3/… stages keep their
   existing honest TIMEOUT outcomes.
4. **Unified, correlating error envelope.** Every failure (404, 413, 422, 5xx,
   auth, scientific-block) returns the same structured envelope with `code`,
   `message`, `user_message`, `details` and a `request_id`. `X-Request-ID` is
   accepted (sanitized), echoed and included in logs/records — client ↔ backend
   correlation without leaking arbitrary header values.
5. **Ordered request bodies.** `BodySizeLimitMiddleware` rejects over-limit
   bodies (`HTTP_MAX_BODY_BYTES`, default 8 MB) with `413 LIMIT_EXCEEDED`
   before any pipeline code runs — including **declared** `Content-Length`
   over-limit requests (verified over real HTTP).
6. **Readiness ≠ liveness.** `/api/ready` reports 8 services
   (`backend, database, filesystem, configuration, authentication,
   ai_capability, deep_matcher, scientific_data`) with honest per-service state;
   optional/blocked capabilities degrade `ready=true`, hard failures flip
   `ready=false` (503). `scientific_data` stays `BLOCKED / REAL_DATA_UNAVAILABLE`
   — never fabricated.
7. **Admin ops surface.** `/api/ops/overview` (admin-only, enforced at the
   dependency level) exposes system, services, recent runs/failures — and
   provably **no** secrets, absolute paths or tracebacks (bug-hunted in B32).
8. **Auth durability.** The SQLite auth database runs in **WAL** mode with a
   `busy_timeout` so read/write contention during login/strict sessions never
   produces `database is locked` (B30).
9. **Runtime validation.** `create_app` validates production/demo config (demo
   requires `app_debug=false`), ensures derived directories and fails fast on
   unsafe settings (B09).
10. **Frontend & deployment resilience.** `frontend/src/api.js` adds a fetch
   timeout (60 s default, clear `REQUEST_TIMEOUT` error), a per-session
   `X-Request-ID`, and richer error metadata (`request_id`, `details`);
   `nginx.conf` caps body size (8 MB), forwards `X-Request-ID`, sets generous
   proxy timeouts, and adds security headers + a CSP for the SPA; compose/
   `.env.example` expose the new hardening knobs.

## 2. Bug-hunt corpus B01–B40 (`tests/test_m11.py`, 42 tests — all green)

| Group | Behaviours verified |
| --- | --- |
| **Smoke/correlation** | B01 health reports M11; B02 meta keeps M11 + canonical config; B03 readiness-not-liveness; B04 request-id echoed on success; B05 envelope carries request_id |
| **Envelopes / limits / validation** | B06 oversized body → honest 413; B07 schema failures use unified envelope; B08 unknown route → NOT_FOUND envelope; B09 env validation + honest demo visibility; B10 unsanitized request ids replaced, never echoed |
| **Readiness integrity** | B11 scientific BLOCKED is honest, not fatal; B12 optional capabilities never fail the service; B13 hard dependency failure not-ready 503; B14 ready truth-table; B15 payload shape contract |
| **Atomic writes / run guard** | B16 atomic JSON never partial; B17 replace-failure preserves previous artifact; B18 RunLock rejects concurrent owner (409 class); B19 stale lock reconciled + run marked interrupted; B20 guarded run records success/failure; B20b run events recorded; B20c NPY/NPZ atomic |
| **Timeout honesty** | B21 M4 timeout never reports COMPLETE; B22 M4 run decision ties timeout to FAILED; B23 M5 timeout → SPATIAL_TIMEOUT; B24 M5 summary truthfully tracks timed-out; B25 M5 decision never COMPLETE on timeout |
| **Auth interplay** | B26 unconfigured auth fails closed; B27 health/ready stay public; B28 pipeline reads require a session; B29 admin-only ops enforced; B30 auth DB durable under WAL |
| **Ops overview** | B31 shape; B32 no secrets/paths; B33 failure flags honest scientific status; B34 run events surface durations; B35 ops requires admin role, not just any session |
| **Posture sweep** | B36 runtime hardening constants present; B37 router-level run guards wired; B38 pipeline routers use guard_run; B39 execution budgets declared; B40 run events bounded + error-coded |

## 3. Real defects found and fixed while hardening

- **`RunLock` failed to create its directory** on pairs whose run directory did
  not exist yet — a `FileNotFoundError` on first guarded run. Fixed in
  `RunLock._acquire_file` (`parent.mkdir(parents=True, exist_ok=True)`), which
  also protects every call site.
- **`/api/ops/overview` was wired with router-level `Depends(AdminUser)`, which
  this FastAPI build rejects** (`422 query.args/query.kwargs`) — the ops surface
  was broken. Routers now use the parameter-anatated dependency form
  (`def endpoint(_admin: AdminUser)`) and all 42 M11 tests pass.
- **404/422 envelope `request_id` missing** before pass — the error handler now
  carries the current request id (B05/B08).
- **Body-limit probe raced the real HTTP client**: with an 8 MB body, the server
  answered 413 instantly and closed, but the client's still-uploading socket
  could see a reset instead of the code. The test now **declares** the oversized
  `Content-Length` without streaming the payload, deterministically exercising
  the up-front 413 guard over real HTTP (smoke `m11-body-limit`).

## 4. Verification

| Suite | Result |
| --- | --- |
| `tests/test_backend.py` | green |
| `tests/test_m1.py` … `tests/test_m8.py` | green |
| `tests/test_m9.py` | **68 passed** re-run after the systematic M10→M11 milestone-assertion bump |
| `tests/test_m10.py` | 31 passed (auth/WAL) |
| `tests/test_m11.py` | **42 passed** (B01–B40) |
| Full regression `pytest tests -q` | **484 passed** (final run; includes B01–B40) |
| `smoke_test.py` (live HTTP, real auth, 101 probes incl. `m11-*`) | **101/101 PASS** |
| `frontend/ssr-smoke.mjs` | **PASS** (all pages render) |
| `npm run build` | PASS |

## 5. Measured performance

Measured live on this machine by `scripts/measure_performance.py` → `perf/results.md`.

- Machine: Windows-11 10.0.26200 · Python 3.14.1 · 12 CPUs · AMD64
- Method: real backend app over TestClient (same ASGI path as uvicorn),
  synthetic **correlated OHRC/TMC-2 TEST FIXTURES** (never real data).

| Metric | Value |
| --- | --- |
| pair register+validate | ~233 ms |
| GET /api/health | mean 3.8 ms · p50 4.0 · p95 5.1 · p99 5.3 |
| GET /api/ready | mean 17.8 ms · p50 15.7 · p95 20.4 · p99 21.9 |
| GET /api/meta | mean 6.5 ms · p50 6.7 · p95 8.2 · p99 8.8 |
| GET /api/data/status | mean 16.9 ms · p50 17.2 · p95 21.8 · p99 24.7 |
| GET /api/pairs | mean 12.2 ms · p50 12.1 · p95 15.1 · p99 16.0 |
| GET /api/pairs/next-id | mean 11.2 ms · p50 11.5 · p95 15.1 · p99 16.1 |
| GET /api/ops/overview (admin) | mean 105 ms · p50 107 · p95 143 · p99 162 |
| 404 envelope (GET /api/nope) | mean 3.3 ms · p50 3.4 · p95 4.6 · p99 5.7 |
| 422 envelope (auth/login bad type) | mean 3.8 ms · p50 3.8 · p95 5.2 · p99 6.2 |
| GET /api/auth/me (token) | mean 10.9 ms · p50 10.9 · p95 13.7 · p99 14.5 |
| request-id echo | echoed=True in ~5 ms |
| guarded pipeline M2→M7 (real engines) | ~15.6 s wall: M2 1.07 s · M3 0.67 s · M4 5.12 s · M5 8.70 s · M6/M7 **BLOCKED** in 0.04 s (honest INSUFFICIENT selection, see §6) |
| guarded re-run of a finished stage | ~36 ms — no duplicate work |
| M6 registration engine (suite tree) | ~1 028 ms → COMPLETE |
| M7 metrics engine (suite tree) | ~258 ms → COMPLETE |
| RunLock acquire+release (uncontended) | ~20 ms/op |
| RunLock single-writer guard (6 concurrent workers) | 1 holder; **5 rejected with JOB_ALREADY_RUNNING** in 28 ms total |
| atomic_write_json vs direct (n=20) | 8.5 vs 5.4 ms (1.6×; includes directory fsync) |
| atomic_write_npy vs np.save (n=20) | 19.6 vs 19.0 ms (1.03×) |
| atomic_write_npz vs savez_compressed (n=20) | 66.6 vs 64.4 ms (1.03×) |

## 6. Honest boundaries

- **Real-data stages remain BLOCKED** on official PRADAN approval; nothing is
  fabricated and every stage reports its true state (`scientific_data =
  BLOCKED / REAL_DATA_UNAVAILABLE`).
- The synthetic correlated engine chain ends with an **honest INSUFFICIENT M5
  selection** (0 selected correspondences) on the small fixture window — the
  abstention is the correct engineering outcome, not a bug (B11/B33 capture it).
  M6/M7 therefore report BLOCKED for that chain; their engine compute is
  measured separately on a suite-validated tree (section 5).
- Performance figures are **measured, not cached**: reproduce with
  `.\.venv\Scripts\python.exe scripts\measure_performance.py`.
- M11 is engineering-layer reliability; it changes **no** scientific threshold
  or algorithm.

## 7. Key files

- `backend/app/hardening.py` — atomic writes, `RunLock` + stale reconciliation,
  `guard_run`, run events, request-id helpers.
- `backend/app/middleware.py` — request context (id echo + access log) and body
  size limit.
- `backend/app/errors.py` — unified envelope incl. 404/413/422 + `request_id`.
- `backend/app/api/ready.py`, `backend/app/api/ops.py` — readiness + admin ops.
- `backend/app/trust/service.py`, `backend/app/spatial/service.py` — atomic
  writes + honest timeout states.
- `backend/app/registration/service.py`, `backend/app/metrics/service.py` —
  atomic NPY/JSON/text writes.
- `backend/app/auth/service.py` — WAL + busy_timeout.
- `tests/test_m11.py` — B01–B40 corpus.
- `scripts/measure_performance.py`, `perf/results.md` — reproduced measurements.
- `smoke_test.py` — M11 live-HTTP probes (`m11-*`, 101/101).
- `frontend/src/api.js`, `frontend/nginx.conf`, `docker-compose.yml`,
  `.env.example` — frontend/container hardening.