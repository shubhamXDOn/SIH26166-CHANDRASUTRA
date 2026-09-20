# M1 Report — Real Data & Metadata (CHANDRASUTRA · SIH26166)

**Milestone:** M1 — Real OHRC–TMC-2 data intake, pair registry and validation
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-15
**Status:**
- **Engineering: DONE** — data intake, pair registry, PDS4 metadata parsing,
  validation, previews, Data workspace UI, full test/regression suite.
- **Real-data acquisition: BLOCKED** — official product downloads require a
  PRADAN account with administrator approval; no anonymous path exists, so no
  real CH-2 `.img`/`.xml` products could be downloaded in this environment.
  Details + exact unblocking steps in [Real-data blocker](#real-data-blocker).

> **Honesty rule:** no pair is registered, no GSD/dimensions/coordinates/hashes
> are claimed, and no overlap is asserted without real files. The registry stays
> empty (CS-P001 reserved) until approved real products are placed under
> `data/raw`. Synthetic fixtures are used **only** in automated tests and are
> never registered as benchmark pairs.

---

## 1. What M1 delivers

### 1.1 Real-data intake pipeline (backend)

- **CH-2 product format support** (`backend/app/loader.py`):
  - Parses detached **PDS4 labels** (`.xml`) namespace-agnostically — no html
    regex soup, no assumption about prefix.
  - Recovers: product ID, instrument, observation time, processing level,
    product type, dimensions, data type, **nominal GSD** (from the label —
    0.25 m/px OHRC, 5 m/px TMC-2), footprint/illumination when present.
  - Opens arrays lazily via `np.memmap`, maps PDS4 sample types to numpy dtypes.
  - Computes **SHA-256** of the raw file (recorded at registration).
  - Generates **derived 8-bit PNG previews** under
    `data/derived/visualizations/previews/` (raw file never touched).
  - Structured failure reporting (`PRODUCT_READ_FAILED`,
    `LABEL_PARSE_FAILED`, `DTYPE_UNSUPPORTED`, …).
  - Official naming decoder:
    `ch2_<inst>_<phase><type><cam>_<UTC>_<P><prd>_<orbit>.img/.xml`.

- **Pair registry & provenance** (`backend/app/pairs.py`):
  - `PairRecord` full M1 schema with **future scientific fields
    `null`/`NOT_RUN`** until measured (preprocessing_config_id, matcher,
    candidate_matches, inliers, inlier_ratio, rmse, spatial_coverage, runtime,
    final_status, …).
  - Canonical records: `data/metadata/pairs.json` + `data/metadata/pairs.csv`
    (atomic tmp+rename writes; CSV is a flat subset of the JSON).
  - Deterministic Pair IDs `CS-P001`, `CS-P002`, … (`next_pair_id`).
  - Path safety: raw files must be relative, inside `data/raw`, and inside a
    configured allowed location; traversal is rejected.
  - `metadata_completeness`: counts real vs UNKNOWN among 22 core fields.
  - **Validation** re-verifies on demand: file existence, label existence,
    readability, dimension/dtype equivalence, **hash re-verification**,
    overlap-evidence rule, pair-ID format. `status` = VALID/INVALID;
    `raw_integrity` = VERIFIED/PARTIAL/FAILED; `benchmark_ready` only for
    CONFIRMED overlap + documented evidence.
  - Validation result persisted to `data/metadata/pair_validation.json`.

### 1.2 M1 API surface (all under `/api`)

| Endpoint | Purpose |
| --- | --- |
| `GET /data/status` | M1 aggregates (pairs registered/valid/confirmed, raw products on disk, metadata completeness average, first pair status, source + access note) |
| `GET /data/sensors` | Phase-A sensor catalog (OHRC, TMC-2, LROC reference) |
| `GET /pairs` | metadata-only pair list (no files opened) |
| `GET /pairs/next-id` | deterministic next Pair ID (`CS-PNNN`) |
| `GET /pairs/scan` | list candidate products under `data/raw` without opening |
| `GET /pairs/probe?path=` | read one product's metadata via its PDS4 label |
| `POST /pairs/register` | register a real pair (references + hashes raws; never copies/moves) |
| `GET /pairs/{pair_id}` | full detail + completeness |
| `GET/POST /pairs/{pair_id}/validate` | run (and persist) validation |
| `GET /pairs/{pair_id}/preview/{side}` | derived PNG preview (lazy) |

Errors use the unified envelope `{error:{code,message,user_message,severity,retryable,details}}`;
absolute server paths are scrubbed from all payloads.

### 1.3 M1 frontend

- Rebranded product identity: **CHANDRASUTRA** everywhere (title, sidebar,
  header pill `M1 · Real Data & Metadata`, Overview hero, meta endpoint).
- **Data workspace** (`frontend/src/pages/Data.jsx`) — new functional page:
  - DATA SOURCE panel (PRADAN, access status, product placement instructions).
  - REGISTERED PAIRS table (sensors, dimensions, nominal GSD, overlap,
    metadata %, validation status) with row-inspection.
  - **Pair inspection** view: Image A/B product cards (metadata + live derived
    preview + SHA-256), DATA INTEGRITY panel (existence/labels/readability/
    hashes), OVERLAP EVIDENCE panel (with honest UNKNOWN framing), metadata
    table + completeness, validation check log, "Validate now".
  - **Ingestion wizard** (Scan → Select → Read metadata → Review → Register &
    validate): indeterminate progress, no fake percentages, structured error
    screen, honest evidence-required gating, `benchmark_ready` rules.
- Overview now reports real M1 metrics (valid/registered pairs, benchmark-ready
  count, metadata %, raw products on disk) and an updated pipeline visualization
  (Data ready · Validate reflects real state · M2+ locked).
- Settings shows the loaded `m1:` configuration; AIInsights stays honestly empty.

## 2. Verification performed

| Check | Result |
| --- | --- |
| `pytest tests` | **56 passed** (28+ new M1 tests: schema, registry determinism/duplicates, PDS4 parsing, missing/corrupt products, hash verification, raw immutability, overlap rules, all new endpoints, path traversal, route wiring) |
| `npm run build` (vite) | PASS |
| `node frontend/ssr-smoke.mjs` | PASS (all pages render headless) |
| `smoke_test.py` | **29/29 PASS** (env, imports, config, directories, live HTTP health/meta, all M1 endpoints incl. next-id/scan/traversal rejection/404s, frontend proxy) |
| Live edge-case curl matrix | invalid pair IDs → 404 envelope; missing files → 404; bad overlap → 422 (with files); traversal → 422; unknown-pair preview/validate → 404 |

Test fixtures (`tests/fixturegen.py`) generate **clearly-labelled synthetic**
CH-2 OHRC/TMC-2 products with real-style names and PDS4 labels; they exist only
for software validation. No synthetic pair is ever registered as a benchmark.

## 3. Real-data blocker

**What blocks M1's "first real pair":**

1. Official OHRC / TMC-2 archives (ISSDC **PRADAN**:
   https://pradan.issdc.gov.in/ch2/ , and browse tool
   https://chmapbrowse.issdc.gov.in/) require an account **and administrator
   approval** before any product download is permitted.
2. Confirmed by probing both portals: no anonymous download path; unauthenticated
   fetches are rejected and pages redirect to login/registration.
3. No real `.img`/`.xml` files are present locally — only the immutable skeleton
   (`data/raw/**/.gitkeep`). Completing registration would require inventing
   files, which this project does not do.

**Consequences (honest):** `data/metadata/pairs.json` is empty, `CS-P001` is
reserved, `GET /data/status` reports 0 pairs, `metadata_completeness` reads 0.0,
and the Data workspace shows its empty state. Every engineering path is ready to
consume real products the moment they exist.

**Exact unblocking steps (manual, ~30 min, one time):**

1. Register at https://pradan.issdc.gov.in/ and request access to the
   Chandrayaan-2 (CH-2) OHRC + TMC-2 datasets; wait for approval.
2. Locate one OHRC and one TMC-2 product covering the same region by date/orbit
   via the map-browse tool or PRADAN search.
3. Download each `.img` **and** its `<product>.xml` PDS4 label.
4. Place them, unchanged:
   - `data/raw/ohrc/` (OHRC)
   - `data/raw/tmc2/` (TMC-2)
5. Run the app, open **Data → Load / Register Pair**, scan, select, add the
   documented overlap basis (same orbit swath / map-browse footprints), register
   → pair `CS-P001` is created and validated automatically.
6. Re-run `smoke_test.py` — the new `m1-pairs-*` checks will flip from 0 to 1.

## 4. Next (M2+, not started)

Safe preprocessing (radiometric/geometric), overlap/crop from the registered
pair, condition estimator, matcher strategy selection, correspondence, Trust
Gate, registration, metrics — all intentionally deferred. M1 ends at raw
intake, metadata and validation.

## 5. Artifacts

- `backend/app/loader.py`, `backend/app/pairs.py`, `backend/app/api/pairs.py`,
  `backend/app/api/data.py`, `backend/app/config.py` (`m1_config`),
  `backend/app/api/health.py`, `backend/app/main.py`, `backend/app/api/router.py`
- `frontend/src/pages/Data.jsx`, `frontend/src/pages/Overview.jsx`,
  `frontend/src/pages/Settings.jsx`, `frontend/src/pages/AIInsights.jsx`,
  `frontend/src/components/Sidebar.jsx`, `frontend/src/App.jsx`,
  `frontend/index.html`
- `tests/fixturegen.py`, `tests/test_m1.py`, `smoke_test.py` (M1 checks)
- `configs/app.yaml` (new `m1:` section), `data/README.md`,
  `data/raw/README.md`, `README.md`