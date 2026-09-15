# CHANDRASUTRA — Trustworthy Lunar Image Intelligence (SIH26166)

**Smart India Hackathon 2026 · Problem SIH26166**

A reliability-first scientific platform for **correspondence and registration of
heterogeneous lunar imagery** (Chandrayaan-2 OHRC ⇄ TMC-2), built around
**adaptive reliability** — condition-aware matcher strategy, independent
verification, measurable diagnostics, and principled abstention.

> **Current milestone: M1 — Real Data & Metadata.** The pair registry, PDS4
> metadata intake, validation and the functional Data workspace are **DONE**.
> Acquisition of the first real OHRC–TMC-2 pair is **BLOCKED** on official
> PRADAN account approval (no anonymous downloads); nothing is fabricated —
> with zero real files on disk the registry honestly reports zero pairs.
> Scientific matching starts at M2.

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
| M2+       | Preprocessing, condition analysis, matchers   | pending |
| M3+       | Trust Gate, spatial reliability, registration | pending |
| M4–M12    | Metrics, benchmarks, AI assistance, hardening | pending |

Milestone reports: `reports/M0_REPORT.md` (foundation) and
`reports/M1_REPORT.md` (real data & metadata).

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
scan/probe/next-id), path-traversal rejection, 404 behaviour, M1 aggregates,
and a full 29-check environment smoke test over a live HTTP stack.

## Repository structure

```
CHANDRASUTRA/
├── backend/            FastAPI application
│   └── app/
│       ├── main.py         app factory + lifespan
│       ├── config.py       Settings (env/.env) + PipelineConfig (YAML) + m1_config
│       ├── logging_conf.py structured logging setup
│       ├── errors.py       unified error envelope + handlers
│       ├── security.py     auth/authorization foundation
│       ├── state.py        app singletons
│       ├── data.py         data architecture service
│       ├── loader.py       M1 PDS4 parser + CH-2 product loader/previews
│       ├── pairs.py        M1 pair registry + validation domain
│       ├── ai/service.py   Gemini boundary (NOT_CONFIGURED-safe)
│       └── api/            health, meta, data, pairs, auth, ai routers
├── frontend/           React + Vite + Tailwind UI
│   └── src/components, src/pages
├── configs/app.yaml    engineering defaults + m1 section (no scientific thresholds)
├── data/               raw (immutable) / derived (reproducible) — see data/README.md
│   └── metadata/       pairs.json, pairs.csv, pair_validation.json (M1 records)
├── tests/              pytest suite (backend incl. test_m1.py + fixturegen.py)
├── reports/            milestone reports (M0_REPORT.md, M1_REPORT.md)
├── smoke_test.py       end-to-end environment smoke test (M1 checks)
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
| M2 | Safe preprocessing, overlap/crop, condition estimator, matcher adapters (baselines) |
| M3 | Adaptive routing & matcher strategy selection                     |
| M4 | Trust Gate — independent verification                            |
| M5 | Spatial reliability / spatial selection                          |
| M6 | Registration (homography/affine) + diagnostics                   |
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
  real metadata intake and validation. Scientific pipelines start at M2.
- No OHRC–TMC-2 pair is downloaded or registered yet: official downloads require
  a PRADAN account with administrator approval (see `reports/M1_REPORT.md` for
  the exact blocker and unblocking steps). The registry is kept honestly empty.
- Auth endpoints are contract stubs (`501 NOT_CONFIGURED`) until the real
  authentication milestone.
- AI explanations are only available after real Gemini integration + key.
- Requirements are pinned for Windows / Python 3.14 as installed and verified;
  re-verify before promoting to another platform.