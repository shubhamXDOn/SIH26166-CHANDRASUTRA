# SIH26166 — M0 Milestone Report

**Status: DONE**

M0 (Foundation) delivered and verified. The scientific pipeline is deliberately
dormant; nothing scientific is claimed to have run. M1 is the next milestone.

---

## 1. Objective

Build a reproducible development environment and a polished application
foundation for the SIH26166 prototype: launching backend + frontend, health
checks, configuration, logging, environment variables, data-directory
architecture with raw/derived separation, data-source documentation, testing
infrastructure, a premium scientific UI shell, and secure structural
preparation for authentication and AI — without implementing any advanced
scientific processing.

## 2. What was implemented

- **Backend (FastAPI, Python 3.14)** — app factory, lifespan (no deprecated
  `on_event`), unified error envelope, structured logging (console + rotating
  file), CORS, startup secrets checks.
- **Configuration** — `pydantic-settings` (env + `.env`) for runtime/secrets;
  `configs/app.yaml` for engineering-default placeholders with explicit
  "not scientifically tuned" marking; missing-config fails fast.
- **Data architecture** — `data/raw` (immutable) vs `data/derived`
  (reproducible); `data/README.md` + `data/raw/README.md` policy docs; backend
  data service never creates raw dirs.
- **API surface** — `/api/health`, `/api/meta`, `/api/data/status`,
  `/api/data/sensors`, `/api/auth/*` (501 stub until real auth milestone),
  `/api/ai/*` (status + 501 stub).
- **Auth foundation** — user/role schema, PBKDF2-HMAC-SHA256 hashing, JWT HS256
  signing (secret from env only), protected-guard dependency that fails closed
  (501 NOT_CONFIGURED) when auth is not configured. No fake login.
- **AI foundation** — `GeminiAssistant` service boundary; key backend-only;
  reports `NOT_CONFIGURED` without a key without crashing the app; no fake
  responses.
- **Frontend (React + Vite 7 + Tailwind)** — premium dark lunar-science UI:
  sidebar (icon rail on tablet, full on desktop), animated pipeline
  visualization with honest locked/ready states, Overview dashboard backed by
  real `/api/meta` + health polling, Data readiness, Analysis roadmap, Results
  empty-state, AI insights status, Settings (no secrets shown); toast + modal
  foundations; skeleton loading; professional empty/error/offline states.
- **Testing** — 28 pytest cases, root `smoke_test.py` (17 checks incl. real
  backend over HTTP and frontend→backend via Vite proxy), `frontend/ssr-smoke.mjs`
  headless render smoke, `npm run build`.
- **Dependencies** — `requirements.txt` pinned to versions verified on this
  machine (Python 3.14 / Windows); `npm audit` → 0 vulnerabilities (Vite 7).

## 3. Project structure

```
SIH26166/
├── backend/app/        main, config, logging_conf, errors, security, state,
│                       data, ai/service, api/{health,auth,data,ai,router,deps}
├── frontend/src/       components/{ui,Sidebar,Pipeline}, pages/{Overview,Data,
│                       Analysis,Results,AIInsights,Settings}, api.js
├── configs/            app.yaml (placeholders), README.md
├── data/               README.md + raw/… (immutable) + derived/… (reproducible)
├── reports/            this report
├── tests/              conftest.py + 4 test modules
├── smoke_test.py, requirements.txt, .env.example, .gitignore
└── README.md
```

## 4. Backend

- FastAPI 0.141 + Uvicorn 0.53, `backend.app.main:app`.
- Error envelope `{ "error": { code, message, user_message, severity,
  retryable, details } }`; raw stack traces never reach the UI.
- Structured logging with `pair_id`/`config_id`/`operation` extension points.
- Starts cleanly with zero environment secrets.

## 5. Frontend

- Servers a real API-driven shell; verifies backend health and metadata live.
- Pipeline stages: DATA = ready, VALIDATE…REPORT = locked, labelled honestly.
- Responsive: full sidebar ≥ `lg`, icon rail below, sticky header, scrollable
  tables.
- Guardrails: no fabricated metrics; "No experiment run yet"; "Awaiting M1".

## 6. Data foundation

- Logical tree resolved by `backend/app/data.py` (10 locations).
- Raw immutable by design (backend refuses to create raw dirs; tests assert it).
- Phase-A sensors documented (OHRC, TMC-2; LROC as future validation reference).
- First OHRC–TMC-2 pair acquisition explicitly deferred to M1 (no fake pair).

## 7. Configuration

- Runtime/secrets: environment + `.env` via `pydantic-settings`.
- Engineering placeholders: `configs/app.yaml` (no scientific thresholds).
- **Reproducibility**: config source is recorded; future results require
  Pair ID + Configuration ID.
- Missing YAML config → `AppConfigError` at startup (exact blocker reported).

## 8. Security

- `.env` git-ignored; `.env.example` committed; no secret in source/tests/git.
- Gemini key backend-only; `public_dict()` never leaks secrets (tested).
- No plaintext passwords (PBKDF2 tested); JWT secret from env with `>=32 B`
  guidance; debug-mode gated docs; CORS configurable.
- `npm audit` 0 vulnerabilities.

## 9. AI foundation

- `GeminiAssistant` boundary; `NOT_CONFIGURED` without key; `/api/ai/status`
  and `/api/ai/explain` contract; app never crashes on missing key (tested).

## 10. Tests executed

- `pytest tests -q` → **28 passed** (2 third-party deprecation warnings from
  Starlette's own testclient, not actionable from our code).
- `python smoke_test.py` → **17/17 PASS** (imports, config, data dirs, real
  backend HTTP health, frontend toolchain, SSR render, frontend→backend proxy).
- `npm run build` (Vite 7) → success; `node ssr-smoke.mjs` → all pages render.

## 11. Bugs found

1. `security.py` imported `UnauthorizedError` from `config` (wrong module) → ImportError.
2. `configs/app.yaml` stage list typed as `list[str]` but YAML holds dicts → 7 pydantic errors.
3. `to_jsonable()` did not handle dataclasses → `/api/data/status` TypeError on `d["exists"]`.
4. 404 handler returned `status_code=exc.http_status` (`HTTPException` has none) → AttributeError.
5. `tests/conftest.py` shadowed `get_state` → recursion hazard (fixed to `_get_state`).
6. Route introspection broke on Starlette 1.6 `_IncludedRouter` (no `.path`).
7. Smoke-test: `start` of `npm` (a `.cmd` shim) fails on Windows → used `npm.cmd`.
8. Frontend: `data_raw/README.md` wrongly git-ignored → added allow rule.
9. Frontend: `ssr-smoke.mjs` used top-level `await` inside non-async arrows → restructured.
10. Frontend: SSR-loading `react` itself failed (`module is not defined`) → import React directly.
11. Overview StatCard "Data readiness" condition was unreachable (`=== 10`).
12. Sidebar rendered logo twice at desktop breakpoints.
13. Sidebar fixed `w-64` squeezed tablet widths → icon rail below `lg`.
14. Overview did not recover `/api/meta` after backend came back online.
15. FastAPI `on_event` deprecation warnings → migrated to lifespan.
16. PyJWT insecure-key warnings in tests → longer test secrets.
17. Unused/misleading `CurrentUser` alias + stale imports in `security.py`.

## 12. Bugs fixed

All 17 above fixed; full regression after fixes (below) is green.

## 13. Regression results

- `pytest tests -q` → 28 passed.
- `smoke_test.py` → OVERALL PASS (17/17).
- `npm run build` → ✓ built; `node ssr-smoke.mjs` → OVERALL PASS.
- Manual: fresh backend + frontend start, `/api/health` 200, proxy `/api/health`
  200, page refresh (SPA served), navigation functions (SSR render of every page).

## 14. Evidence

- `logs/backend.log` (file + console structured logs).
- `smoke_test.py` output: `OVERALL: PASS` — 17 checks.
- `pytest` output: `28 passed`.
- `frontend/dist/` production build (~188 kB JS / ~26 kB CSS, gzip ~57 kB).
- `npm audit`: `found 0 vulnerabilities`.
- Health payload:
  `{"status":"ok","application":"SIH26166","version":"0.1.0","environment":"development",...}`

## 15. Known limitations

- M0 performs no scientific processing (by design; pipeline dormant).
- Auth endpoints return `501 NOT_CONFIGURED`; no user storage yet.
- AI explain is stub-only; real Gemini calls are a later milestone.
- Repo pinned/verified on Windows + Python 3.14; other platforms should
  re-pin after verification (per Rule 24).
- 2 deprecation warnings originate inside Starlette's testclient, not our code.

## 16. Deferred items

- Real OHRC–TMC-2 pair download/registration (M1).
- Preprocessing, overlap/crop, condition estimator, matcher adapters (M2).
- Adaptive routing (M3), Trust Gate (M4), spatial selection (M5), registration
  (M6), metrics/reporting (M7), deep matcher benchmarks (M8), real Gemini (M9),
  full auth (M10), hardening (M11), final validation (M12).

## 17. Exact next milestone

**M1 — Real data intake & validation**: acquire at least one documented
OHRC–TMC-2 pair from ISSDC PRADAN (PDS4), verify metadata/provenance, confirm
overlap, register the pair (Pair ID), keep raw immutable, and expose validated
pair metadata through the existing `/api/pairs` namespace.

## 18. Git commit / hash

Initial foundation commit and the final report commit (hash below):

- `git log --oneline` after this milestone — see repository history.