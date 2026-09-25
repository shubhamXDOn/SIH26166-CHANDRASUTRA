# CHANDRASUTRA — Trustworthy Lunar Image Intelligence (SIH26166)

**Smart India Hackathon 2026 · Problem SIH26166**

A reliability-first scientific platform for **correspondence and registration of
heterogeneous lunar imagery** (Chandrayaan-2 OHRC ⇄ TMC-2), built around
**adaptive reliability** — condition-aware matcher strategy, independent
verification, measurable diagnostics, and principled abstention.

> **Current milestone: M13 — Final release · CHANDRASUTRA v1.0.0 (SIH26166).**
> M1–M12 are complete and frozen, and M13 packages the engineering proof for
> jury presentation: an aggregate release-status API (`/api/m13`), an evidence
> explorer and report centre in the app, honest measurements, release docs and
> tooling, and a 40-case B01–B40 bug-hunt corpus. Full regression is green —
> `pytest tests` 561/561, environment smoke 101/101, frontend build + SSR PASS,
> Docker Compose config VALID. Frozen evidence is intact:
> `EXP-EE0EBE7187E5` · `FINAL_EVIDENCE_SHA256`
> `c8fbab19dee75ce92870755bdf5202ad1402ee97166a8bdbfc3db8dfd7557e37` ·
> configuration fingerprint
> `9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce` — and
> every honesty contract holds: real mission data stays **BLOCKED** on official
> PRADAN approval, reference is `NOT_AVAILABLE`, physical accuracy is
> `NOT_CLAIMED`, provenance is **PARTIAL · HOLD** (M8/M9 honestly NOT_RUN), and
> hosted latency is `NOT_MEASURED`. See `RELEASE_NOTES.md`,
> `DEPLOYMENT.md`, `REAL_DATA_ONBOARDING.md` and
> `M13_FINAL_RELEASE_REPORT.md`.

---

## Table of contents

1. [Problem & proposed solution](#problem--proposed-solution)
2. [Architecture at a glance](#architecture-at-a-glance)
3. [Milestone status](#milestone-status)
4. [Setup (backend)](#setup-backend)
5. [Run (backend)](#run-backend)
6. [Setup + run (frontend)](#setup--run-frontend)
7. [Environment variables](#environment-variables)
8. [Testing](#testing)
9. [Repository structure](#repository-structure)
10. [Data policy](#data-policy)
11. [Official data source](#official-data-source)
12. [Development roadmap M0–M12](#development-roadmap-m0m12)
13. [Scientific integrity rules](#scientific-integrity-rules)
14. [AI integration policy](#ai-integration-policy)
15. [Limitations](#limitations)

---

## Problem & proposed solution

Lunar imagery arrives from multiple sensors with very different resolutions,
illumination, geometry and radiometry. Naively matching such heterogeneous
images — and trusting a generic matcher — produces unreliable registrations.

Our pipeline (to be implemented across M1–M12):

```
REAL DATA → VALIDATION → SAFE PREPROCESSING → OVERLAP/CROP → CONDITION ANALYSIS
→ MATCHER STRATEGY → CANDIDATE CORRESPONDENCES → TRUST GATE → SPATIAL RELIABILITY
→ REGISTRATION → METRICS → VISUALIZATION → SUCCESS / FAILURE / ABSTAIN
```

We do **not** claim to invent SIFT, AKAZE, RIFT2, SuperPoint, SuperGlue, LoFTR,
RANSAC, homography or affine registration. Those are components/baselines. The
contribution is the **reliability-oriented system** around them: condition-aware
strategy selection, independent verification, spatial reliability, measurable
diagnostics and **principled abstention** (a result may legitimately end as
ABSTAIN when evidence is insufficient).

## Architecture at a glance

- **Backend** — FastAPI (Python 3.14), environment-driven `pydantic-settings`,
  YAML engineering defaults, structured logging, unified error envelope,
  auth + AI service boundaries, data-directory service.
- **Frontend** — React + Vite + Tailwind CSS. No heavy UI libraries. Premium
  dark "lunar science" interface; dashboard, pipeline visualization, data
  readiness, analysis roadmap, results, AI insights and settings pages.
- **Data** — `data/raw` (immutable) ⋄ `data/derived` (reproducible) layout.

## Milestone status

| Milestone | Scope                                         | Status |
| --------- | --------------------------------------------- | ------ |
| M0        | Reproducible env, app shell, foundations      | **DONE** (committed) |
| M1        | Real OHRC–TMC-2 data intake & metadata        | **DONE (engineering)** — real download BLOCKED on PRADAN approval, see `reports/M1_REPORT.md` |
| M2        | Preprocessing, overlap/crops, condition analysis, matcher readiness | **DONE (engineering)** — real-data execution BLOCKED (see `reports/M2_REPORT.md`) |
| M3        | Matcher adapters & adaptive strategy, candidate correspondences | **DONE (engineering)** — real-data execution BLOCKED (see `reports/M3_REPORT.md`) |
| M4        | Trust Gate — independent geometric verification | **DONE (engineering)** — real-data execution BLOCKED (see `reports/M4_REPORT.md`) |
| M5        | Spatial reliability — scene grid, reliable regions, reliability-aware selection | **DONE (engineering)** — real-data execution BLOCKED (see `reports/M5_REPORT.md`) |
| M6        | Registration engine — verified alignment, transform fit + fallback, warp output, validation verdicts, diagnostics, manifest + provenance, jury-ready workspace | **DONE (engineering)** — real-data execution BLOCKED (see `reports/M6_REPORT.md`) |
| M7        | Metrics — quality/similarity diagnostics, completeness, honest reporting | **DONE (engineering)** — see `reports/M7_REPORT.md` |
| M8        | Mental-deep expansion — deep-matcher adapters + benchmark harness | **DONE (engineering)** — see `reports/M8_REPORT.md` |
| M9        | AI assistant — real Gemini explanatory layer | **DONE (engineering)** — see `reports/M9_REPORT.md` |
| M10       | Authentication/authorization — users, sessions, roles, audit | **DONE (engineering)** — see `reports/M10_REPORT.md` |
| M11       | Hardening — atomic writes, run guards, error envelope, timeout honesty, readiness/ops endpoints, frontend resilience, perf measurements | **DONE (engineering)** — see `reports/M11_REPORT.md` |
| M12       | Full reproducibility suite, final validation & presentation | **DONE (engineering)** - see `reports/M12_FINAL_SCIENTIFIC_REPORT.md` |

Milestone reports: `reports/M0_REPORT.md` (foundation),
`reports/M1_REPORT.md` (real data & metadata),
`reports/M2_REPORT.md` (preprocessing & scene conditioning),
`reports/M3_REPORT.md` (adaptive matcher & candidate correspondences),
`reports/M4_REPORT.md` (Trust Gate & independent geometric verification),
`reports/M5_REPORT.md` (spatial reliability & reliability-aware selection),
`reports/M6_REPORT.md` (registration engine & verified alignment),
`reports/M7_REPORT.md` (metrics & diagnostics),
`reports/M8_REPORT.md` (deep-matcher expansion & benchmarks),
`reports/M9_REPORT.md` (AI assistant & Gemini boundary), and
`reports/M10_REPORT.md` (authentication/authorization), and
`reports/M11_REPORT.md` (hardening, performance, jury-readiness), and
`reports/M12_FINAL_SCIENTIFIC_REPORT.md` (final evidence: reproducibility RUN A/B/C,
raw-integrity gate, audits, cross-check, evidence freeze).

## Setup (backend)

Prerequisites: **Python 3.10+** (developed on 3.14), **Node.js ≥ 20**.

```powershell
# 1. virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. dependencies (pinned to versions verified on this machine)
pip install -r requirements.txt

# 3. environment configuration
Copy-Item .env.example .env      # then edit as needed
```

The app always starts, even with an empty `.env`. Without `AUTH_SECRET_KEY` every
protected endpoint **fails closed** with `501 AUTH_NOT_CONFIGURED` (health,
meta and `/auth/status` stay public). Set the key and a bootstrap admin to turn
authentication on — see `.env.example`.

## Run (backend)

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
# → http://127.0.0.1:8000/api/health
# → OpenAPI docs (only when APP_DEBUG=true): http://127.0.0.1:8000/api/docs
```

Key endpoints (all under `/api`):

| Endpoint             | Purpose                                            |
| -------------------- | -------------------------------------------------- |
| `GET /health`        | structured health payload                          |
| `GET /meta`          | non-secret runtime/app metadata for the UI         |
| `GET /data/status`   | M1 live data + pair-registry aggregates            |
| `GET /data/sensors`  | Phase-A sensor catalog (OHRC, TMC-2, LROC ref)     |
| `GET /pairs`         | metadata-only list of registered pairs             |
| `GET /pairs/next-id` | deterministic next Pair ID (`CS-PNNN`)             |
| `GET /pairs/scan`    | list candidate products under `data/raw`           |
| `GET /pairs/probe`   | read one product's PDS4 metadata                   |
| `POST /pairs/register` | register a real pair (hashes raws, never copies) |
| `GET /pairs/{id}`    | full pair detail + completeness                    |
| `GET/POST /pairs/{id}/validate` | run & persist pair validation          |
| `GET /pairs/{id}/preview/{side}` | derived PNG preview (lazy)            |
| `GET /processing/configurations` | available processing configs (`PC-M2-001`) |
| `GET /processing/overview` | M2 aggregate — honestly BLOCKED until a validated real pair exists |
| `POST /processing/{id}/prepare` | run PREPARE (validate → masks → overlap → crops → conditions → readiness) |
| `GET /processing/{id}/status` | PREPARE run state + matcher readiness |
| `POST /processing/{id}/reset` | wipe `derived/processing/<pair>` (raw untouched) |
| `GET /processing/{id}/manifest` | provenance hash manifest |
| `GET /processing/{id}/conditions` | per-tile condition distribution |
| `GET /processing/{id}/tiles` | tile list + indicators (`/tiles/{tile}/preview` = PNG) |
| `GET /matching/configurations` | available matcher configurations (`MC-M3-001`) |
| `GET /matching/overview` | M3 aggregate — honestly BLOCKED until a validated real pair exists |
| `POST /matching/{id}/run` | run MATCH (routing → matchers → candidate filters) |
| `GET /matching/{id}/status` | MATCH run state + summary + blocked code |
| `POST /matching/{id}/reset` | wipe `derived/matches/<pair>` (raw + M2 untouched) |
| `GET /matching/{id}/manifest` | matching provenance manifest (relative paths + SHA-256) |
| `GET /matching/{id}/decisions` | per-tile routing decisions |
| `GET /matching/{id}/candidates` | candidate-correspondence index (observations) |
| `GET /matching/{id}/tiles[...]/candidates` | per-tile candidate points + distance + score |
| `GET /trust/configurations` | available trust configurations (`TG-M4-001`) |
| `GET /trust/overview` | M4 aggregate — honestly BLOCKED until a validated real pair exists |
| `POST /trust/{id}/run` | run Trust Gate (independent geometric verification) |
| `GET /trust/{id}/status` | Trust Gate run state + gate verdict + block code |
| `POST /trust/{id}/reset` | wipe `derived/trust/<pair>` (raw + M2 + M3 untouched) |
| `GET /trust/{id}/manifest` | trust provenance manifest (relative paths + SHA-256) |
| `GET /trust/{id}/summary` | trust run summary |
| `GET /trust/{id}/tiles` | per-tile verdict cards (TRUSTED/REJECTED/INSUFFICIENT/FAILED) |
| `GET /trust/{id}/tiles/{tile}` | single tile verdict (model, spatial, cross-check evidence) |
| `GET /spatial/configurations` | available spatial reliability configurations (`SR-M5-001`) |
| `GET /spatial/overview` | M5 aggregate — honestly BLOCKED/empty until a validated real pair exists |
| `POST /spatial/{id}/run` | run SPATIAL (grid → reliability → components → selection) |
| `GET /spatial/{id}/status` | spatial gate state + block code |
| `POST /spatial/{id}/reset` | wipe `derived/spatial/<pair>` (M4/M3/M2/raw untouched) |
| `GET /spatial/{id}/manifest` | spatial provenance manifest (POSIX relative paths + SHA-256) |
| `GET /spatial/{id}/summary` | spatial run summary (grid, tiles, scene, reliability, selection) |
| `GET /spatial/{id}/map` | reliability map incl. `visualization.grid` + legend |
| `GET /spatial/{id}/components` | connected-region explorer |
| `GET /spatial/{id}/cells` | full per-cell evidence table |
| `GET /spatial/{id}/selection` | selection policy outcome + reason + selected IDs |
| `GET /spatial/{id}/mapping` | scene mapping (tile → normalised box) |
| `GET /spatial/{id}/selected-correspondences` | npz field list + counts |
| `GET /registration/configurations` | available registration configurations (`RG-M6-001`) |
| `GET /registration/overview` | M6 aggregate — honestly BLOCKED/empty until a validated real pair exists |
| `POST /registration/{id}/run` | run REGISTRATION (select M5 evidence → fit → validate → warp) |
| `GET /registration/{id}/status` | registration run state + block code |
| `POST /registration/{id}/reset` | wipe `derived/registration/<pair>` (M5/M4/M3/M2/raw untouched) |
| `GET /registration/{id}/manifest` | registration provenance manifest (relative paths + SHA-256) |
| `GET /registration/{id}/summary` | registration run summary (transform, mapping, correspondences, warp) |
| `GET /registration/{id}/transform` | fitted transform matrix + source/target space declarations |
| `GET /registration/{id}/diagnostics` | residual / symmetric-transfer / numerical diagnostics |
| `GET /registration/{id}/validation` | verdict, checks, issues + independent recompute block |
| `GET /registration/{id}/provenance` | M2→M6 provenance chain |
| `GET /registration/{id}/selected-evidence` | M5-selected evidence summary consumed by the run |
| `GET /registration/{id}/visualizations` | comparison montages list (before/after, difference, correspondences, footprint) |
| `GET /registration/{id}/visualizations/{name}` | one visualization PNG |
| `GET /registration/{id}/registered-product` | registered array / valid mask / preview + meta envelope |
| `GET /registration/{id}/registered-product/array` | registered image `.npy` (uint16 per config) |
| `GET /registration/{id}/registered-product/valid-mask` | valid-pixel mask `.npy` |
| `GET /registration/{id}/registered-product/preview` | registered image PNG preview |
| `GET /auth/status`   | public auth status (configured, registration, TTLs, session state) |
| `POST /auth/login`   | sign in → JWT access token + HttpOnly refresh cookie |
| `POST /auth/refresh` | rotate refresh session (token in cookie only) |
| `POST /auth/logout`  | revoke all the user's refresh sessions |
| `POST /auth/register`| self-registration (account created disabled, admin activates) |
| `GET /auth/me`       | current user identity (SafeUser) |
| `POST /auth/me/password` | change own password (invalidates other sessions) |
| `GET /auth/users`    | admin — list users                          |
| `PATCH /auth/users/{id}` | admin — update role / active state      |
| `DELETE /auth/sessions/{id}` | admin — revoke one refresh session  |
| `GET /auth/security-summary` | admin — user/session/audit aggregates |
| `GET /ai/status`     | AI service status (NOT_CONFIGURED without a key)   |

## Setup + run (frontend)

```powershell
cd frontend
npm install
npm run dev            # → http://localhost:5173  (proxies /api → 127.0.0.1:8000)
```

Production build: `npm run build` (outputs to `frontend/dist`).

## Setup + run (Docker)

A reproducible deployment ships with the repository. Docker Compose builds two
containers — a FastAPI backend (`/api`) and an nginx frontend that statically
serves the built SPA and proxies `/api` to the backend.

```powershell
# 1. environment (secrets stay out of git)
Copy-Item .env.example .env      # then edit as needed (AUTH_SECRET_KEY etc.)

# 2. build + run
docker compose up --build
# → UI: http://localhost           (nginx serves frontend/dist, proxies /api)
# → API health: http://localhost:8000/api/health
```

Notes:

- The backend container mounts a named volume at `/data` so raw + derived data
  survive container rebuilds (`DATA_ROOT=/data`).
- The backend image installs `requirements.txt` (pinned Python 3.14 verified
  versions) and runs `uvicorn backend.app.main:app`.
- The frontend image builds `frontend/dist` from source (no committed bundle)
  and serves it with nginx; `ssr-smoke.mjs` is excluded from the image.
- The nginx proxy (M11 hardened) caps request bodies at 8 MB, forwards
  `X-Request-ID` correlation, keeps generous proxy timeouts, and adds baseline
  security headers + CSP for the SPA.
- Health checks are wired for the backend service; the UI reports honestly when
  the backend is unreachable.
- For a non-Docker production run, serve `frontend/dist` with any static host
  and point `/api` at the backend (see `frontend/nginx.conf` for the proxy
  configuration).

## Environment variables

See `.env.example` for the full annotated list. Key items:

| Variable           | Required | Notes                                          |
| ------------------ | -------- | ---------------------------------------------- |
| `APP_ENV`          | no       | `development` \| `production`                  |
| `APP_DEBUG`        | no       | enables `/api/docs` + verbose errors           |
| `BACKEND_HOST/PORT`| no       | uvicorn bind target                            |
| `CORS_ORIGINS`     | no       | comma-separated browser origins                |
| `LOG_LEVEL`        | no       | Python logging level                           |
| `AUTH_SECRET_KEY`  | auth*  | JWT signing secret; required to enable auth (fail-closed 501 without it). Generate via `python -c "import secrets; print(secrets.token_urlsafe(64))"` |
| `AUTH_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` | auth* | admin created on first startup when both are set |
| `AUTH_ACCESS_TTL_SECONDS` | no   | access-token lifetime (default 900s)            |
| `AUTH_REFRESH_TTL_SECONDS`| no   | refresh-session lifetime (default 604800s)      |
| `AUTH_REGISTER_ENABLED`  | no   | allow self-registration (default true)         |
| `HTTP_MAX_BODY_BYTES`    | no   | request body cap (413 `LIMIT_EXCEEDED` beyond it; default 8000000) |
| `RUN_STALE_BUDGET_SECONDS` | no | pipeline run lock age treated as interrupted/crashed (default 600s) |
| `DEMO_MODE`              | no   | honest "synthetic demonstration" marker; never fabricates results |
| `REQUEST_ID_HEADER`      | no   | header used/echoed for request correlation (default `x-request-id`) |
| `GEMINI_API_KEY`   | later    | backend-only Gemini key; never sent to the browser |

`.env` is git-ignored. **Never commit secrets.**

## Testing

```powershell
# backend unit/integration tests
.\.venv\Scripts\python.exe -m pytest tests -q

# full environment smoke test (starts real backend + frontend, checks proxy)
.\.venv\Scripts\python.exe smoke_test.py

# frontend headless render smoke (no browser needed)
cd frontend && node ssr-smoke.mjs

# frontend production build
cd frontend && npm run build
```

The M1 suite covers everything from M0 plus: pair schema & registry
determinism, PDS4 label parsing (missing/corrupt/unknown-field cases), CH-2
filename decoding, SHA-256 integrity, raw immutability, overlap/evidence rules,
full coverage of `/pairs` endpoints (register/detail/validate/preview/
scan/probe/next-id), path-traversal rejection, 404 behaviour, M1 aggregates.
The M2 suite adds: processing configuration defaults, the PREPARE happy path to
`READY_FOR_MATCHING` with the full derived layout, raw immutability during
processing, manifest relative-only paths + SHA-256, tiles/conditions/preview
endpoints, reset, `NO_GEOMETRY` / `NO_OVERLAP` / `NO_GSD` blocks, mask
bitflags, display normalization, condition determinism + `UNKNOWN`, overlap
slicing, overview honest-BLOCKED, route wiring, and M2 endpoint behaviour.
The M3 suite adds: matcher configuration + rejection, configurations endpoint
(dynamic availability), adapter capability matrix, SIFT/ORB shifted-window
correspondences, mask steering, adaptive engine selection vs condition + scale
gap, unavailable/constraint recording, determinism + `final_confidence` absence,
candidate filter counts/ordering, mask/border/duplicate rejection, honest
INSUFFICIENT_CANDIDATES / MATCHER_FAILED / NO_FEATURES / TIMEOUT outcomes,
artifact roundtrip + "not a verdict" licensing, the full MATCH lifecycle to
COMPLETE with the derived layout, manifest relative-only + SHA-256, BLOCK /
404 / 422 paths, reset scoping, and bug-hunt regressions (non-finite rejection,
path-traversal guard, zero-dims border skip). The M4 suite adds: trust
configuration registration/load/endpoint, RANSAC + affine geometry (translation
recovery, noise rejection, collinear degeneracy, symmetric transfer,
determinism), spatial diagnostics (occupancy, cluster fail, zero-inlier safety),
per-tile engine verdicts (TRUSTED, INSUFFICIENT, collinear/cluster reject,
cross-check, residual-policy, determinism), the full Trust Gate lifecycle over a
real M3 run (COMPLETE / FAILED gates), honest BLOCKED, overview aggregates,
unknown pair/config behaviour (404 + service block), manifest provenance, reset
scoping, path-traversal safety, runtime TIMEOUT, and re-run determinism. The
M5 suite adds: spatial configuration registration/load/endpoint, scene mapping
(tile-origin + overlap resolution, boundary/out-of-scene reasons), the overlap-
normalised grid and per-cell evidence, connected components + fragmentation,
`SUPPORTED_REGION` selection, the full spatial lifecycle over a real M4 run
(COMPLETE / BLOCKED), honest overview, unknown pair/config behaviour (404 +
service block), manifest provenance (POSIX relative-only paths), npz provenance
fields + determinism + cap enforcement, reset scoping, and a 22-case bug hunt
(boundary tolerance, homogeneous-w exclusion, confidence absence, path leaks,
UTF-8, NaN-free scene arrays, re-entrancy, orientation). The M6 suite adds:
registration configuration registration/load/endpoint, tile-local → sensor-pixel
conversions, strict npz loader hardening (missing keys, length mismatch,
non-finite, `scene_side` validity, scene bounds), homography/affine fit +
fallback + validation verdicts on synthetic correspondences, the warp pipeline
(max output-dimension bounds, interpolation, `uint16` dtype enforcement),
independence (seeded-RANSAC determinism, residual + symmetric-transfer
recomputation), transform `source_space`/`target_space` declarations, the full
registration lifecycle over a real M5 run (COMPLETE / INSUFFICIENT / BLOCKED,
reset isolation), manifest + provenance (relative paths only, SHA-256),
diagnostics + validation artefacts, the `/visualizations`,
`/registered-product` and `/selected-evidence` endpoints, and a bug-hunt
regression set. The M7 suite adds metrics configuration/engine/service coverage,
lifecycle runs over real M6 outputs, honest overview, manifest/provenance and
reset scoping. The M8 suite adds the deep-matcher expansion (router decisions,
benchmark harness over available matchers, honest unavailable reporting). The
M9 suite adds the AI assistant boundary (NOT_CONFIGURED-safe status, grounding
rules, no-secret guarantees, task endpoints). The M10 suite adds full
authentication/authorization coverage: configuration fail-closed behaviour,
login/refresh rotation, role matrix (viewer/analyst/admin), password rules,
account disable, audit + security summary, rate limiting, and a 30-case bug
hunt (JWT tampering, session revocation, secret-leak scans, privilege
boundaries, refresh replay). The M11 hardening suite (`tests/test_m11.py`,
B01–B40) adds: smoke/correlation probes, envelope behaviour (413 limit-exceeded,
404/wrong-method 405, 422 schema/defaults, `x-request-id` echo), readiness +
operator overview integrity (no path/secrets leakage), atomic write semantics
(no partial JSON/NPY/NPZ; crash-safe), `RunLock`/`guard_run` single-writer
behaviour (stale-lock reconciliation, serialized runs, run events capped),
timeout honesty (M4 trust gate FAILED + `TIMEOUT`, M5 spatial FAILED +
`SPATIAL_TIMEOUT`), auth/WAL interplay, and a posture sweep over auth-applied
endpoints. The environment smoke
test runs dozens of checks over a live HTTP stack
(backend endpoints, auth login + bearer probes, frontend render, vite proxy).

## Repository structure

```
CHANDRASUTRA/
├── backend/            FastAPI application
│   ├── Dockerfile          backend container (uvicorn, pinned requirements)
│   └── app/
│       ├── main.py         app factory + lifespan
│       ├── config.py       Settings (env/.env) + PipelineConfig (YAML) + m1…m9_config
│       ├── logging_conf.py structured logging setup
│       ├── errors.py       unified error envelope + handlers
│       ├── security.py     role/authz rules (viewer/analyst/admin) + route dependencies
│       ├── state.py        app singletons
│       ├── data.py         data architecture service
│       ├── loader.py       M1 PDS4 parser + CH-2 product loader/previews
│       ├── pairs.py        M1 pair registry + validation domain
│       ├── processing/     M2 PREPARE engine (masks, overlap, crops, conditions, manifest)
│       ├── matching/       M3 MATCH engine (adapters, routing, candidates, manifest)
│       ├── trust/          M4 Trust Gate engine (geometry, spatial, degeneracy, service, manifest)
│       ├── spatial/        M5 spatial reliability (mapping, grid, reliability, selection, service, manifest)
│       ├── registration/   M6 registration engine (config, engine, warp, coordinator, loader,
│       │                   diagnostics, visualize, manifest, provenance, service, states)
│       ├── metrics/        M7 metrics engine (config, engine, service, manifest)
│       ├── matching/m8     M8 deep-matcher expansion + benchmarks (deep adapters, routing, benchmark)
│       ├── auth/           M10 authentication (config, models, password hashing, tokens,
│       │                   sessions, audit, dependencies)
│       ├── hardening.py    M11 hardening (atomic writes, run lock, guarded runs, run events)
│       ├── m12/            M12 reproducibility & final evidence (config_freeze, raw_integrity,
│       │                   provenance, audits, crosscheck, package, report, reproducibility)
│       ├── ai/service.py   Gemini boundary (NOT_CONFIGURED-safe)
│       └── api/            health, meta, data, pairs, processing, matching, trust, spatial, registration, metrics, auth, ai, ready, ops routers
├── frontend/           React + Vite + Tailwind UI
│   ├── Dockerfile          two-stage build → nginx static host + /api proxy
│   ├── nginx.conf          SPA server block + /api reverse proxy
│   └── src/components, src/pages        (incl. Analysis workspace, Account + admin Security)
├── configs/app.yaml    engineering defaults + m1….m9 sections (no scientific thresholds)
├── docker-compose.yml  backend + frontend services (named /data volume)
├── data/               raw (immutable) / derived (reproducible) — see data/README.md
│   ├── metadata/       pairs.json, pairs.csv, pair_validation.json (M1 records)
│   ├── auth/           SQLite auth db — users, sessions, audit/security events (M10)
│   ├── derived/processing/   per-pair PREPARE outputs (M2: status, manifest, masks, crops, conditions)
│   ├── derived/matches/      per-pair MATCH outputs (M3: status, manifest, decisions, candidates, m8/)
│   ├── derived/trust/        per-pair TRUST outputs (M4: gate status, manifest, tile verdicts)
│   ├── derived/spatial/      per-pair SPATIAL outputs (M5: status, summary, reliability map, components, selection, npz)
│   ├── derived/registration/ per-pair REGISTRATION outputs (M6: status, transform, diagnostics,
│   │                         validation, registered/, visualizations/, manifest, provenance)
│   └── derived/metrics/      per-pair METRICS outputs (M7: status, summary, manifest)
├── tests/              pytest suite (incl. test_m1.py … test_m12.py + auth_helpers/conftest)
├── reports/            milestone reports (M0_REPORT.md … M12_FINAL_SCIENTIFIC_REPORT.md)
├── smoke_test.py       end-to-end environment smoke test (M1 + M2 + … + M12) — incl. auth login/token, ready, ops, request-id echo
├── requirements.txt    pinned Python dependencies
├── .env.example        environment template (secrets never committed)
└── .gitignore
```

## Data policy

- **Raw is immutable** — `data/raw/**` is read-only by design; all transforms
  write to `data/derived/<stage>/`.
- **Derived is reproducible** — regenerate from raw + configuration; no manual
  edits of correspondence points or outputs.
- **Metadata honesty** — unknown metadata stays UNKNOWN; never fabricated.
- **Overlap confirmed before matching** — pairs require validated spatial overlap.
- Full policy: `data/README.md`.

## Official data source

- ISRO / ISSDC PRADAN — https://pradan.issdc.gov.in/
- Chandrayaan-2 data — https://pradan.issdc.gov.in/ch2/
- FAQ — https://pradan.issdc.gov.in/ch2/faq.xhtml
- NASA LROC (future independent validation reference) — Lunar Reconnaissance Orbiter Camera

Phase-A prototype sensors: **OHRC** (~0.25 m/px) and **TMC-2** (~5 m/px).

Initial dataset: at least one documented OHRC–TMC-2 pair, later a second
challenging pair. **We do not download the mission archive, and we do not
substitute random/generated imagery as scientific evidence.** The first pair is
acquired properly as soon as PRADAN account approval is granted (M1 blocker —
see `reports/M1_REPORT.md`).

## Development roadmap M0–M12

| #  | Milestone                                                        |
| -- | ---------------------------------------------------------------- |
| M0 | **Foundation**: env, backend, premium UI, config, logging, tests — DONE |
| M1 | **Real data intake & metadata validation** — engineering DONE; first real OHRC–TMC-2 pair BLOCKED on PRADAN approval |
| M2 | **Preprocessing & scene conditioning** (masks, overlap, crops, conditions, matcher readiness) — engineering DONE; real-data execution BLOCKED, see `reports/M2_REPORT.md` |
| M3 | **Matcher adapters & adaptive strategy selection, candidate correspondences** — engineering DONE; real-data execution BLOCKED, see `reports/M3_REPORT.md` |
| M4 | **Trust Gate — independent geometric verification** (RANSAC geometry, degeneracy + residual + spatial reliability checks, symmetric cross-check, binary gate over candidate correspondences) — engineering DONE; real-data execution BLOCKED, see `reports/M4_REPORT.md` |
| M5 | **Spatial reliability & reliability-aware selection** (overlap-normalised scene grid, per-cell verified evidence, connected regions, SUPPORTED_REGION selection → selected_correspondences.npz) — engineering DONE; real-data execution BLOCKED, see `reports/M5_REPORT.md` |
| M6 | Registration (homography/affine) + diagnostics | **DONE (engineering)** — real-data execution BLOCKED, see `reports/M6_REPORT.md` |
| M7 | Metrics, visualization, SUCCESS / FAILURE / ABSTAIN reporting — **DONE (engineering)**, see `reports/M7_REPORT.md` |
| M8 | Deep matcher adapters + benchmarking vs baselines — **DONE (engineering)**, see `reports/M8_REPORT.md` |
| M9 | Real Gemini explanatory layer — **DONE (engineering)**, see `reports/M9_REPORT.md` |
| M10 | Authentication/authorization completion (users, sessions, roles, audit) — **DONE (engineering)**, see `reports/M10_REPORT.md` |
| M11 | Hardening & jury-readiness (atomic writes, run guards + stale-lock reconciliation, timeout honesty, unified error envelope, readiness/ops endpoints, frontend resilience, nginx/container hardening, measured performance) — **DONE (engineering)**, see `reports/M11_REPORT.md` |
| M12 | Full reproducibility suite, final validation & presentation (configuration freeze, raw-integrity + real-data gate, provenance chain, independent audits, cross-check, sealed evidence package, RUN A/B/C reproducibility, deterministic final report) — **DONE (engineering)**, see `reports/M12_FINAL_SCIENTIFIC_REPORT.md` |

(This is a working roadmap; milestones may be merged where engineering requires.)

## Scientific integrity rules

1. Never fabricate scientific values, matches, registrations, AI responses or metrics.
2. Results carry **Pair ID** and **Configuration ID** and are reproducible.
3. Matcher confidence is **not** the final truth signal.
4. Low homography residual is **not** proof of physically exact lunar registration.
5. Unknowns stay UNKNOWN; experiments are reproducible from config; raw data is immutable.
6. Outcomes may be ABSTAIN — declining to claim is a legitimate scientific result.

## AI integration policy

- Gemini is an **explanatory/assistive** layer around the scientific pipeline.
- It never performs or authorizes core registration.
- The API key is backend-only (`GEMINI_API_KEY` in `.env`); it is **never**
  exposed to browser code.
- Without a key the service reports `NOT_CONFIGURED` and the application runs
  normally. No fake AI answers are ever produced.
- Evidence grounding: every answer is validated against the evidence packet
  that was sent with the request (`M9-EVIDENCE-001` for M9 tasks,
  `M11-EVIDENCE-001` for full-pipeline M11 tasks covering M1..M10). Citations
  must reference milestones/metrics present in the sent packet or the response
  is rejected (`AI_INVALID_RESPONSE`).
- Full-pipeline M11 tasks: `explain-pipeline`, `summarize-pipeline`,
  `explain-trust`, `explain-spatial`, `explain-registration`,
  `explain-benchmark`, `explain-abstention` (POST `/api/ai/<task>`). They build
  the full M11 evidence packet (`M11-EVIDENCE-001`) before prompting.
- Honest state reporting: unrun milestones are reported as `NOT_STARTED`/
  `NOT_AVAILABLE`/`BLOCKED`; the reference is `REFERENCE_UNAVAILABLE` without
  provisioned real data; the AI never invents scientific results.

## Limitations

- M1 performs **no matching/registration**; the corpus is the pair registry plus
  real metadata intake and validation.
- M2 ends at the **matcher-readiness contract**: preprocessing, overlap/crops,
  condition analysis and readiness are real, but no correspondences are
  produced; scientific matching starts at M3.
- M3 produces **candidate correspondences as observations** — condition-aware
  strategy routing and explicit candidate filters are real, but nothing is a
  trust verdict until the independent Trust Gate actually executes.
- M4 has executed the **Trust Gate** on engineering fixtures; candidate sets are
  now independently verified (RANSAC/affine models, degeneracy + residual +
  spatial-reliability checks, symmetric cross-check) and carry a binary
  TRUSTED/BLOCKED verdict per tile. No accuracy/confidence metric is ever
  produced or shown, and real-data gate runs remain BLOCKED until PRADAN access
  is granted.
- M5 has executed **Spatial Reliability** on the same engineering fixtures (8×8
  grid, connected regions, a supported selection written to
  `selected_correspondences.npz`). The M5 outputs are **measured spatial
  evidence positions**, not a final registration/alignment model and not an
  accuracy claim; real-data spatial runs remain BLOCKED for the same reason.
- M6 has executed **Registration** on correlated synthetic fixtures (4
  correspondences, homography fit + affine fallback, warped registered output,
  validation verdict, diagnostics, manifest + provenance chain M2→M6, all
  deterministic). M6 outputs are **verified alignment measurements, not proof
  of physical lunar registration**; real-data registration runs remain BLOCKED
  for the same reason. Diagnostics never fabricate `confidence`, `accuracy` or
  a CE90/LE90 claim.
- No OHRC–TMC-2 pair is downloaded or registered yet: official downloads require
  a PRADAN account with administrator approval (see `reports/M1_REPORT.md` for
  the exact blocker and unblocking steps). The registry and the M2 overview are
  kept honestly empty/BLOCKED.
- Auth (M10) is **real server-side authentication**: SQLite users, Argon2id-ish
  (PBKDF2-SHA-256) password hashing, short-lived JWT access tokens, rotating
  refresh sessions stored as SHA-256 hashes in an HttpOnly SameSite cookie,
  viewer/analyst/admin roles enforced at the router level, a full security/
  audit event log, and rate limiting on login/refresh. No fake login exists —
  without `AUTH_SECRET_KEY` every protected endpoint fails closed with
  `501 AUTH_NOT_CONFIGURED`.
- AI explanations are only available after real Gemini integration + key.
- M11 hardening is **all engineering-layer**: crash-safe atomic artifact writes,
  a single-writer run lock with stale-lock (interrupted-run) reconciliation,
  honest `TIMEOUT` verdicts for Trust Gate and Spatial Reliability, unified
  404/413/422 envelopes with `X-Request-ID` correlation, readiness + operator
  overview endpoints, and frontend fetch timeouts/retry semantics. It adds
  **no new science**: real-data pipeline stages remain BLOCKED on PRADAN access.
- M12 final validation is an **evidence layer, not new science**: it independently
  re-verifies raw integrity, certifies the real-data gate decision (PATH B =
  deterministic SYNTHETIC_DATA_ONLY proof while real data remains BLOCKED on PRADAN
  approval), audits derived artifacts, cross-checks explanatory claims, and seals a
  byte-identical reproducible evidence package (`FINAL_EVIDENCE_SHA256`,
  RUN A/B/C reproducibly `REPRODUCIBLE`). Nothing is fabricated or presented as a
  real-data scientific result.
- Requirements are pinned for Windows / Python 3.14 as installed and verified;
  re-verify before promoting to another platform.