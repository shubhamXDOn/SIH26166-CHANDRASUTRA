# M2 Report — Preprocessing & Scene Conditioning (CHANDRASUTRA · SIH26166)

**Milestone:** M2 — Trustworthy preprocessing, overlap evidence, sensor-native
crops, per-tile scene-condition analysis, and a matcher-readiness contract that
will feed the M3 matcher adapters.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-16
**Status:**
- **Engineering: DONE** — the full M2 PREPARE pipeline is implemented, tested
  (74 backend tests passed, 34/34 environment smoke checks), exercised end to
  end on synthetic fixtures, and wired into a functional Analysis workspace UI.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as M1.
  M2 truthfully reports **BLOCKED (no validated real pair available)** through
  `/api/processing/overview` and per-pair status rather than simulating a run.
  A real pair without documented geometry is blocked at the overlap gate.

> **Honesty rule:** PREPARE never fabricates a result. Every gate is a real
> check against files on disk — validation, raw SHA-256, ground-footprint
> overlap, per-tile masks/statistics, condition estimators. `BLOCKED` is a
> first-class, visible outcome. Synthetic fixtures exist **only** in automated
> tests; they are never registered as benchmark pairs.

---

## 1. What M2 delivers

### 1.1 Processing configuration (`configs/app.yaml` → `m2:`)

- `PC-M2-001` / v1 — the runnable configuration exposed by
  `GET /api/processing/configurations` (default configuration).
- Policy defaults (engineering, config-tracked, reproducible):
  - Overlap: `min_overlap_px: 64`, strategy `footprint_intersection`,
    `require_geometry: true`.
  - Crops: `size_px: 512`, `stride_px: 256`, min tile width/height 16,
    `min_valid_fraction: 0.5`.
  - Masking: NaN/Inf, saturation (`saturation_dn: 65535`), negative, zero-valid
    rules. Display normalization: pixel-percentile 1/99. Radiometric
    normalization explicitly `not_applicable` (labels carry no calibration).
  - Condition thresholds: `texture_low_dn: 8.0`, `texture_high_dn: 60.0`,
    `empty_valid_fraction: 0.02`.
  - Matcher readiness must satisfy all of `raw_integrity_ok, preprocess_ok,
    overlap_valid, tiles_generated, tiles_usable, condition_evaluated`.

### 1.2 PREPARE lifecycle (`backend/app/processing/`)

States: `NOT_STARTED → BLOCKED → READING → PREPROCESSING →
PREPARING_OVERLAP → GENERATING_CROPS → ANALYZING_CONDITION →
READY_FOR_MATCHING` (and `FAILED`). Each stage records its own status, so a
run that stops early shows exactly which step blocked.

1. **READING** — re-reads the registered pair's raw products, re-verifies
   SHA-256 against registration hashes (`RAW_INTEGRITY_OK` or block
   `RAW_INTEGRITY_MISMATCH`), loads arrays via portable PDS4 label detection
   (`lines`/`samples`/`data_type` + `offset_bytes` for labels; numpy-memmap
   container fallback).
2. **PREPROCESSING** — per sensor (OHRC, TMC-2): written `invalid-mask`
   (bitflags `1=NAN_INF 2=SATURATED 4=NEGATIVE 8=UNKNOWN`), display-normalized
   16-bit `u16` array, `stats.json`. Raw files are never modified; orientation
   stays as-recorded (`record_footprint_or_request` / `block` fallback);
   resampling is `applied: false` in this milestone.
3. **PREPARING_OVERLAP** — geometry is required: real pairs without documented
   ground geometry block `NO_GEOMETRY`; missing GSD blocks `NO_GSD`. Sensor-native
   ground footprints (`row_offset_m` / `col_offset_m` per sensor) intersect to
   a confirmed overlap polygon; no intersection blocks `NO_OVERLAP`. Evidence is
   written to `diagnostics/overlap.json` (not asserted — computed).
4. **GENERATING_CROPS** — sensor-native tiles (`CS-PNNN-T###`) at config
   stride/size within the confirmed overlap. Tiles outside/partially outside the
   sensor footprint are flagged `clipped` / `too_small` (small tiles are not
   claimable); `min_valid_fraction` gates tiles whose masked-invalid area is
   too large (`TILES_UNUSABLE` block only if **no** usable tile exists for a
   sensor). Per-sensor honest counts: `tiles_generated` / `usable_counts`.
5. **ANALYZING_CONDITION** — per-tile, per-sensor scene-condition estimators
   (texture metrics, valid fraction, intensity statistics) classified against
   the config thresholds into e.g. `LOW_TEXTURE` / `GOOD_TEXTURE` /
   `HIGH_TEXTURE` — written `diagnostics/conditions.json`. Deterministic;
   empty observations are classified `UNKNOWN`.
6. **MATCHER READINESS** — a contract for the M3 matcher adapters:
   `READY` / `CONDITIONAL` (e.g. fixture textures beyond calibrated bounds) /
   `BLOCKED`, listing the satisfied and missing readiness requirements.

### 1.3 Provenance & reproducibility

- Every run writes `derived/processing/<pair>/<config>/`:
  `processing_status.json` (run log), `processing_manifest.json`
  (step → relative path + SHA-256, no absolute paths), per-sensor
  `preprocessed_display_u16.npy`/`invalid_mask_u8.npy`/`stats.json`,
  `crops/tiles.json`, `diagnostics/overlap.json`, `diagnostics/conditions.json`,
  `<tile>_preview.png` (derived preview, lazy-generated on request).
- Everything in `derived/` is reproducible from `raw` + configuration.

### 1.4 M2 API surface (all under `/api/processing`)

| Endpoint | Purpose |
| --- | --- |
| `GET /configurations` | available processing configurations (`PC-M2-001` default) |
| `GET /overview` | honest aggregate: **BLOCKED** with reason when no validated real pair exists |
| `GET /{pair_id}/status` | full run state, stage log, blocked reason, matcher readiness, manifest/conditions presence |
| `POST /{pair_id}/prepare` | run PREPARE for the pair (optional `configuration_id`, `geometry`) |
| `POST /{pair_id}/reset` | wipe `derived/processing/<pair>` (raw + registry untouched) |
| `GET /{pair_id}/manifest` | provenance hash manifest |
| `GET /{pair_id}/conditions` | per-tile condition distribution |
| `GET /{pair_id}/tiles` | tile list with indicators per tile |
| `GET /{pair_id}/tiles/{tile_id}` | single tile detail |
| `GET /{pair_id}/tiles/{tile_id}/preview` | tile preview PNG |

### 1.5 M2 frontend — Analysis workspace

- **Overview** now reports M2 readiness: hero milestone "M2 · Preprocessing &
  Scene Conditioning", pipeline `preprocess` stage reflects real state
  (complete → warning → locked), benchmark-ready StatCard mentions matcher-ready
  pairs, "Open Analysis" navigates (BLOCKED is a first-class outcome).
- **Analysis page** (new, `Analysis.jsx`): pair + configuration selectors,
  live status with stage progress, PREPARE and Reset buttons, blocked/failed
  banners with specific codes, matcher-readiness requirement cards, tile
  explorer with per-tile indicators + PNG previews, condition distribution,
  provenance manifest modal, module roadmap.
- **Data page**: each pair inspection now shows its M2 processing-readiness
  card (state badge, blocked reason, "Open in Analysis").

## 2. Verification performed

| Check | Result |
| --- | --- |
| `pytest -q` | **74 passed** (18 new M2 tests in `tests/test_m2.py`: config, happy-path READY + derived layout, raw immutability, manifest relative-only + SHA-256, tiles/conditions/preview endpoints, reset, NO_GEOMETRY / NO_OVERLAP blocks, PAIR_NOT_VALID, mask bitflags, display normalization, determinism + UNKNOWN conditions, overlap slicing unit, overview-honest-empty, route wiring) |
| `smoke_test.py` | **34/34 PASS** — incl. live-HTTP `m2-configurations`, `m2-overview-honest-zero` (BLOCKED on empty registry), unknown-pair status/prepare → 404 |
| `npm run build` (vite) | PASS |
| `node frontend/ssr-smoke.mjs` | PASS — all pages including the new Analysis workspace render headless |

Full-preparation path (state `READY_FOR_MATCHING`, level `CONDITIONAL`) is
exercised in tests with synthetic geometry (OHRC 200×256 at (0,0), TMC-2
300×384 at (80,60), gsd 1.0 → 120 px × 196 px overlap) via `geometry.source:
TEST_FIXTURE`. This remains the only route to full readiness until real
products arrive.

## 3. Real-data blocker (unchanged from M1, expressed in M2 terms)

- Official OHRC/TMC-2 archives (ISSDC PRADAN, https://pradan.issdc.gov.in/ch2/)
  require an account **and administrator approval**; no anonymous download
  exists.
- `/api/processing/overview` therefore returns `blocked: true` with reason
  "M2 real-data processing: BLOCKED — no validated real pair is available."
- Real pairs **with** geometry would run PREPARE now; real pairs **without**
  geometry block at `NO_GEOMETRY` (preprocessing still proceeds and is
  reported).
- Unblocking steps: identical to those in `reports/M1_REPORT.md` (register +
  request CH-2 OHRC/TMC-2 access, place `.img` + `.xml` under `data/raw/ohrc`
  and `data/raw/tmc2`, run the app, register the pair, then run PREPARE from
  the Analysis workspace).

## 4. Next (M3+, not started)

M3 begins beyond the matcher-readiness boundary: matcher adapters (baselines),
adaptive strategy selection by condition, and eventually candidate
correspondence. M2 intentionally stops at the readiness contract; the matcher
pipeline, Trust Gate, registration and metrics remain pending.

## 5. Artifacts

- `backend/app/processing/` — `config.py`, `states.py`, `masking.py`,
  `normalize.py`, `geometry.py`, `overlap.py`, `crops.py`, `conditions.py`,
  `manifest.py`, `service.py`.
- `backend/app/api/processing.py`, `backend/app/api/router.py` (wired),
  `backend/app/config.py` (`m2_config`), `backend/app/data.py`
  (`derived/processing` tree), `backend/app/api/health.py` (`/meta`
  `m2_config`).
- `tests/test_m2.py` (18 tests), `smoke_test.py` (M2 checks).
- `frontend/src/pages/Analysis.jsx` (new), `frontend/src/pages/Data.jsx`,
  `frontend/src/pages/Overview.jsx`, `frontend/src/App.jsx`.
- `configs/app.yaml` (new `m2:` section).