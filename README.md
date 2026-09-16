# CHANDRASUTRA — Trustworthy Lunar Image Intelligence (SIH26166)

**Smart India Hackathon 2026 · Problem SIH26166**

A reliability-first scientific platform for **correspondence and registration of
heterogeneous lunar imagery** (Chandrayaan-2 OHRC ⇄ TMC-2), built around
**adaptive reliability** — condition-aware matcher strategy, independent
verification, measurable diagnostics, and principled abstention.

> **Current milestone: M4 — Trust Gate (independent geometric verification).**
> Candidate correspondences from M3 are now independently verified: RANSAC
> homography/affine models, degeneracy + residual-policy + spatial-reliability
> checks, symmetric cross-check and a binary Trust Gate are **DONE** and fully
> tested (131 backend tests, 44/44 smoke checks, gate COMPLETE with 6/6 tiles
> TRUSTED on the correlated e2e fixture). Acquisition of the first real OHRC–TMC-2
> pair is still **BLOCKED** on official PRADAN account approval, so the M4 gate
> honestly reports a BLOCKED overview on the live app; nothing is fabricated.

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
| M5–M12    | Spatial reliability, metrics, benchmarks, AI assistance, hardening | pending |

Milestone reports: `reports/M0_REPORT.md` (foundation),
`reports/M1_REPORT.md` (real data & metadata),
`reports/M2_REPORT.md` (preprocessing & scene conditioning),
`reports/M3_REPORT.md` (adaptive matcher & candidate correspondences), and
`reports/M4_REPORT.md` (Trust Gate & independent geometric verification).

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

The app runs fine with an empty `.env` — `AUTH_SECRET_KEY` and `GEMINI_API_KEY`
are optional until their future milestones.

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
| `GET /auth/status`   | authentication foundation status (no fake login)   |
| `GET /ai/status`     | AI service status (NOT_CONFIGURED without a key)   |

## Setup + run (frontend)

```powershell
cd frontend
npm install
npm run dev            # → http://localhost:5173  (proxies /api → 127.0.0.1:8000)
```

Production build: `npm run build` (outputs to `frontend/dist`).

## Environment variables

See `.env.example` for the full annotated list. Key items:

| Variable           | Required | Notes                                          |
| ------------------ | -------- | ---------------------------------------------- |
| `APP_ENV`          | no       | `development` \| `production`                  |
| `APP_DEBUG`        | no       | enables `/api/docs` + verbose errors           |
| `BACKEND_HOST/PORT`| no       | uvicorn bind target                            |
| `CORS_ORIGINS`     | no       | comma-separated browser origins                |
| `LOG_LEVEL`        | no       | Python logging level                           |
| `AUTH_SECRET_KEY`  | later    | JWT signing secret; generated via `token_urlsafe(64)` |
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
environment smoke test runs **44 checks** over a live HTTP stack
(backend endpoints, frontend render, vite proxy).

## Repository structure

```
CHANDRASUTRA/
├── backend/            FastAPI application
│   └── app/
│       ├── main.py         app factory + lifespan
│       ├── config.py       Settings (env/.env) + PipelineConfig (YAML) + m1_config + m2_config
│       ├── logging_conf.py structured logging setup
│       ├── errors.py       unified error envelope + handlers
│       ├── security.py     auth/authorization foundation
│       ├── state.py        app singletons
│       ├── data.py         data architecture service
│       ├── loader.py       M1 PDS4 parser + CH-2 product loader/previews
│       ├── pairs.py        M1 pair registry + validation domain
│       ├── processing/     M2 PREPARE engine (masks, overlap, crops, conditions, manifest)
│       ├── matching/       M3 MATCH engine (adapters, routing, candidates, manifest)
│       ├── trust/          M4 Trust Gate engine (geometry, spatial, degeneracy, service, manifest)
│       ├── ai/service.py   Gemini boundary (NOT_CONFIGURED-safe)
│       └── api/            health, meta, data, pairs, processing, matching, trust, auth, ai routers
├── frontend/           React + Vite + Tailwind UI
│   └── src/components, src/pages        (incl. Analysis workspace — M2/M3/M4)
├── configs/app.yaml    engineering defaults + m1/m2/m3/m4 sections (no scientific thresholds)
├── data/               raw (immutable) / derived (reproducible) — see data/README.md
│   ├── metadata/       pairs.json, pairs.csv, pair_validation.json (M1 records)
│   ├── derived/processing/   per-pair PREPARE outputs (M2: status, manifest, masks, crops, conditions)
│   ├── derived/matches/      per-pair MATCH outputs (M3: status, manifest, decisions, candidates)
│   └── derived/trust/        per-pair TRUST outputs (M4: gate status, manifest, tile verdicts)
├── tests/              pytest suite (incl. test_m1.py … test_m4.py + fixturegen.py)
├── reports/            milestone reports (M0_REPORT.md … M4_REPORT.md)
├── smoke_test.py       end-to-end environment smoke test (M1 + M2 + M3 + M4 checks, 44 total)
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
| M5–M6 | Spatial reliability / spatial selection (real-data depth); registration (homography/affine) + diagnostics |
| M7 | Metrics, visualization, SUCCESS / FAILURE / ABSTAIN reporting    |
| M8 | Deep matcher adapters + benchmarking vs baselines                |
| M9 | Real Gemini explanatory layer                                    |
| M10 | Authentication/authorization completion                          |
| M11 | Hardening, performance, accessibility                           |
| M12 | Full reproducibility suite, final validation & presentation      |

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
- No OHRC–TMC-2 pair is downloaded or registered yet: official downloads require
  a PRADAN account with administrator approval (see `reports/M1_REPORT.md` for
  the exact blocker and unblocking steps). The registry and the M2 overview are
  kept honestly empty/BLOCKED.
- Auth endpoints are contract stubs (`501 NOT_CONFIGURED`) until the real
  authentication milestone.
- AI explanations are only available after real Gemini integration + key.
- Requirements are pinned for Windows / Python 3.14 as installed and verified;
  re-verify before promoting to another platform.