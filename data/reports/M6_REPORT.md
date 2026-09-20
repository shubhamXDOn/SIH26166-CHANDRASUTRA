# M6 Report — Registration Engine, Verified Alignment & Jury-Ready Registration Workspace (CHANDRASUTRA · SIH26166)

**Milestone:** M6 — verified sensor-pixel alignment workspace that consumes the
M5 `selected_correspondences.npz`, fits a homography (with affine fallback) in
sensor pixel space, validates the fit with residual / symmetric-transfer /
numerics gates plus an independent recomputation, warps the M2 product into the
target window, and writes a jury-ready registration workspace with a
SHA-256 manifest and an M2 → M3 → M4 → M5 → M6 provenance chain.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-17
**Status:**
- **Engineering: DONE** — the full M6 registration pipeline is implemented,
  tested (283 backend tests total, 83 dedicated to M6 including the bug-hunt
  B-series and the hardening feature set), deterministically exercised on
  correlated synthetic fixtures (homography fit + affine fallback, COMPLETE
  state, transform / validation / warp product / manifest / provenance across
  identical runs), containerised for deployment, and SSR-smoke-green in the
  frontend. `npm run build` passes.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as
  M1–M5. M6 truthfully reports **BLOCKED** via `/api/registration/overview`
  and per-pair status rather than fabricating any alignment claim. Synthetic
  fixtures exist only in automated tests and a controlled TEMP e2e script —
  never as benchmark pairs.

> **Honesty rule:** M6 produces **diagnostics, never proof.** Residual means,
> p95 values, symmetric-transfer maxima, condition numbers and verdicts are
> measurements of fit *in the recorded pixel grid*, not evidence of physically
> exact lunar registration. Every summary, manifest and API response carries
> diagnostics-as-measurements wording and "no scientifically tuned lunar
> thresholds exist yet". FAILED, INSUFFICIENT and BLOCKED are first-class
> states; a verdict never fabricates scientific confidence.

---

## 1. What M6 delivers

### 1.1 Registration configuration (`configs/app.yaml` → `m6:`)

- `RG-M6-001` / v1 — the sole registered configuration exposed by
  `GET /api/registration/configurations` and referenced in `/api/meta` as
  `m6_config`. Pydantic-backed `RegistrationConfig` mirrors every field
  (`backend/app/registration/config.py`), including string→number coercion.
- Transform: `preferred_type homography`, `affine_fallback true`,
  `min_inliers_for_homography 4`, `min_inlier_ratio_for_homography 0.5`,
  RANSAC `max_iterations 2000`, `inlier_threshold_px 3.0`, `seed 42` (seeded →
  deterministic), `refine false`.
- Validation: `max_symmetric_transfer_px 12.0`, `max_residual_mean_px 10.0`,
  `max_residual_median_px 6.0`, `max_residual_p95_px 15.0`,
  `min_inlier_ratio 0.3`, `min_inliers 6`, `max_condition_number 100000`,
  min absolute determinant `1e-6` (degeneracy/reversal guard).
- Warp: `method forward_mapping`, `output_bounds target_bounds`,
  `fill_value 0`, `dtype uint16` (clip + round on save),
  `output_interpolation linear`, `output_image_format png`,
  `visualization_normalization minmax`, `max_output_rows 20000`,
  `max_output_cols 20000` (a target larger than the bound fails the run
  explicitly — `OUTPUT_BOUNDS_INVALID` — instead of guessing).
- Execution: `max_runtime_seconds 120`.
- Source: `engineering defaults`, `scientifically_tuned false`, with an
  explicit "no scientifically tuned lunar thresholds" note — policy values,
  not science claims.

### 1.2 Coordinate contract (`backend/app/registration/coord_space.py`)

- M3 `x_a/y_a/x_b/y_b` are **tile-local sensor pixels**; M5 mapping translates
  them via the M5 `mapping.json` `scene_x/scene_y` into the pair overlap in
  normalised coordinates.
- Registration operates in **sensor pixel space** (`build_sensor_pixel_points`):
  normalised scene coordinates are converted back to sensor-A (side `a`) /
  sensor-B (side `b`) pixels using the M5 scene map before fitting. The
  homography therefore maps sensor-A pixels → sensor-B pixels, declared
  explicitly in `transform.json`, `summary.json` and the validation artefact
  as `source_space` `{"sensor": "a", "frame": "sensor_a_pixel"}`, `target_space`
  `{"sensor": "b", "frame": "sensor_b_pixel"}` and `direction
  "sensor_a_pixel -> sensor_b_pixel"`.
- Homogeneous-coordinate handling (`to_homogeneous`, `project`) rejects points
  with `w ≈ 0` and normalises; degenerate/invalid points are excluded from the
  fit via a validity mask before RANSAC.

### 1.3 Loader (`backend/app/registration/loader.py`)

- `load_selected_correspondences(data_root, pair_id, spatial_service)` reads
  the M5 `selected_correspondences.npz` and is strict:
  - M5 run must exist and be `COMPLETE` (`M5_NOT_AVAILABLE` / `M5_NOT_COMPLETE`).
  - M5 selection outcome must be `SELECTED` (`NO_SELECTION`).
  - All 13 expected npz keys present (`COORDINATE_LOAD_FAILED` on absent /
    corrupt file), equal array lengths (`LENGTH_MISMATCH`), and ≥ 4 finite
    coordinate pairs (`INSUFFICIENT_EVIDENCE`).
  - `scene_side` values must be ∈ {`a`, `b`} and `scene_x/scene_y` must lie in
    the normalised `[0, 1]` range — invalid values raise structured
    `COORDINATE_LOAD_FAILED` causes.
- Every rejection is a machine-readable, structured error — never a partial
  guess. The service maps loader failures to honest `BLOCKED` /
  `INSUFFICIENT` states.

### 1.4 Fit + fallback (`backend/app/registration/engine.py`)

- `fit_and_validate(...)` tries homography via a seeded RANSAC
  (`estimate_homography`, seed 42, `RandomState` → deterministic output) with
  `max_iterations 2000` and `inlier_threshold_px 3.0`. When homography fails
  or earns too few inliers, an affine fallback (`estimate_affine` via M4 trust
  primitives) engages with selection reason `FALLBACK_DEGENERATE` /
  `FALLBACK_INSUFFICIENT_INLIERS`.
- Failed models produce structured errors (`HOMOGRAPHY_FIT_FAILED`,
  `AFFINE_FIT_FAILED`, `MODEL_INVALID`, `TIMEOUT`) that surface as `FAILED` /
  `INSUFFICIENT` states, never a silent guess.
- Residuals and symmetric transfer are recomputed on the fitted matrix using
  the trusted M4 primitives (`_compute_residuals_forward`,
  `compute_symmetric_transfer`), not the fit package's internal error metric.
- Output: `transform.json` with `transform_type`, 3×3 `matrix`,
  `source_space` / `target_space` / `direction`, `inlier_count`,
  `inlier_ratio` and `seed_used`. Determinism is regression-tested.

### 1.5 Warp + output (`backend/app/registration/warp.py`, `service.py`)

- `_warp_evidence` picks the tile contributing the most selected evidence,
  builds a `WarpSpec` (source crop + target window), and `warp_tile`
  forward-maps into `registered/registered_image.npy` (uint16, clip+round per
  config), `registered/valid_mask.npy`, `registered/registered_image.png` and
  `registered/registered_meta.json` (dtype, out_rows/out_cols, source/target
  tile, transform type, valid-fraction).
- Max output-dimension guards (`max_output_rows/max_output_cols`) fail the run
  explicitly with `OUTPUT_BOUNDS_INVALID` instead of allocating unbounded
  buffers; failures are recorded in `status.json` reasons and `summary.json`.
- `visualizations/` montages are best-effort derived inspection aids written
  by `backend/app/registration/visualize.py`: `registered_overlay`,
  `before_after`, `difference_overlay`, `correspondences`, `footprint`.
  They are **never** treated as scientific evidence.

### 1.6 Diagnostics, validation, provenance (`diagnostics.py`, `manifest.py`, `provenance.py`)

- **Diagnostics** are measurements: inlier counts, residual mean/p95, outliers,
  symmetric-transfer max, determinant, condition number, runtime, seed, plus
  the source `source_space` / `target_space` declaration. They carry a
  "diagnostics are measurements" note.
- **Validation** (`validation.json`) records the binary verdict from the fit
  quality gates, `checks`, `issues`, a `state` of `VALIDATED` (verdict PASS) or
  `FAILED_VALIDATION`, and an `independent_check` block: residuals and
  symmetric transfer **recomputed from the fitted matrix** via M4 trust
  primitives with `recomputed: true`, `method`, residual stats,
  `symmetric_transfer_max_px` and `consistent_with_fit`.
- **Manifest** (`registration_manifest.json`) lists every produced artefact
  with SHA-256 hashes and POSIX **relative** paths only (no absolute /
  home / pair-path leaks) plus the M2 → M6 provenance chain.
- **Provenance** (`provenance.json`) chains M2 → M3 → M4 → M5 → M6; each node
  records `milestone`, `artifacts` and `sha256`, always derived, never
  fabricated. The manifest hashes provenance deterministically (provenance is
  written first).

### 1.7 Registration lifecycle (`backend/app/registration/service.py`, `/api/registration`)

States: `NOT_STARTED → BLOCKED → RUNNING → COMPLETE` (plus `FAILED` /
`INSUFFICIENT`). Block codes: `M5_NOT_AVAILABLE`, `M5_NOT_COMPLETE`,
`NO_SELECTION`, `INSUFFICIENT_EVIDENCE`, `COORDINATE_LOAD_FAILED`,
`MAPPING_LOAD_FAILED`, `UNKNOWN_CONFIG`; warp failures add an explicit reason
(e.g. `OUTPUT_BOUNDS_INVALID`) instead of a silent blank.

1. **Prerequisites** — an M5 COMPLETE run with a `SELECTED` outcome must exist;
   status/selection/summary are read from the M5 run directory.
2. **Run** — loads the selected correspondences, converts to sensor pixel
   space, fits + validates, warps, and writes all derived artefacts
   (`status.json`, `summary.json`, `transform.json`, `diagnostics.json`,
   `validation.json`, `provenance.json`, `registration_manifest.json`,
   `registered/`, `visualizations/`). Provenance is written before the manifest.
3. **Gate verdict** — `COMPLETE` only if fit + validation PASS; `INSUFFICIENT`
   when evidence or validation is insufficient; `FAILED` on unrecoverable
   error (including warp bounds); `BLOCKED` when M5 preconditions are not met.
   Re-runnable and deterministic.
4. **Reset** — removes only `derived/registration/<pair>` artefacts;
   M5/M4/M3/M2/raw data are untouched.
5. **Evidence recap** — `selected_evidence(pair_id)` reports exactly which M5
   evidence a run consumed (counts, unique tile/component IDs, scene sides,
   M5 state) without computing anything new.

### 1.8 M6 API surface (all under `/api/registration`)

| Endpoint | Purpose |
| --- | --- |
| `GET /configurations` | registered configurations (`RG-M6-001` default + full defaults incl. warp bounds/interp/normalization) |
| `GET /overview` | honest aggregate (`NOT_STARTED`/zero in a clean repo) |
| `GET /{pair_id}/status` | gate state, block code, reasons |
| `POST /{pair_id}/run` | run registration (unknown config → 404) |
| `POST /{pair_id}/reset` | wipe `derived/registration/<pair>` (upstream untouched) |
| `GET /{pair_id}/manifest` | jury-ready manifest (SHA-256, relative paths only) |
| `GET /{pair_id}/summary` | run summary (transform type, spaces, correspondences, warp, runtime) |
| `GET /{pair_id}/transform` | fitted transform matrix + source/target space declaration |
| `GET /{pair_id}/diagnostics` | residuals / inliers / numerics measurements |
| `GET /{pair_id}/validation` | verdict + checks + independent recompute block |
| `GET /{pair_id}/provenance` | M2 → M6 SHA-256 provenance chain |
| `GET /{pair_id}/selected-evidence` | recap of the M5 evidence the run consumes (404 before it exists) |
| `GET /{pair_id}/visualizations` | comparison montage list (kind, name, URL) |
| `GET /{pair_id}/visualizations/{name}` | one montage PNG (whitelisted kinds only, `.png` only) |
| `GET /{pair_id}/registered-product` | registered product envelope (array / valid-mask / preview URLs + meta) |
| `GET /{pair_id}/registered-product/array` | registered image `.npy` |
| `GET /{pair_id}/registered-product/valid-mask` | valid-pixel mask `.npy` |
| `GET /{pair_id}/registered-product/preview` | registered image PNG |

`/api/meta` exposes `m6_config` (with `registration_configuration_id:
RG-M6-001`).

### 1.9 M6 frontend (Analysis workspace, downstream of Spatial Reliability)

- **RegistrationPanel.jsx** — run/reset controls, gate-state badge (live
  `Registration {state}`), BLOCKED / INSUFFICIENT / FAILED message cards,
  transformation card (type, matrix, `source_space → target_space` frame
  line), diagnostics (inliers/residuals/symmetric-transfer/determinant/
  condition), validation verdict + per-check passes + **independent recompute**
  block, provenance chain, and a **visualization gallery** (before/after,
  difference overlay, correspondences, footprint, registered overlay) with a
  toggle between montages, plus the honesty note (`LOW RESIDUAL ≠ PHYSICALLY
  EXACT REGISTRATION`).
- **Overview.jsx** — M6 as a pipeline stage with live registration completion
  counts (complete/total/blocked) via `useRegistrationOverview`, and an
  honest "Milestone M6 — Verified Registration" hero badge tied to the
  milestone banner.
- **Data.jsx / Results.jsx** — per-pair registration status chip in pair
  inspection, registration completion card, M6 milestone summaries.

### 1.10 Deployment

- `docker-compose.yml` orchestrates two containers: a FastAPI backend
  (`python:3.14-slim`, pinned `requirements.txt`, uvicorn on :8000) and an
  nginx frontend (`node:22-alpine` build → `nginx:1.27-alpine` static host)
  that proxies `/api/` to the backend.
- Backend `DATA_ROOT` maps to the named volume `chandrasutra_data` at `/data`
  so raw + derived data survive rebuilds; health checks are wired; the UI
  reports honestly when the backend is unreachable.
- `README.md` documents `docker compose up --build`, `Copy-Item .env.example
  .env`, the volume layout and health-check URLs.

---

## 2. Bug hunt + hardening (B-series, 36 cases)

The M6 bug-hunt / hardening corpus (`tests/test_m6.py` §9–§10) exercises:

| ID | Title | Key check |
|----|-------|-----------|
| B1 | No fabricated confidence/accuracy | API/manifest never emit `confidence`, `accuracy` or a CE90/LE90 claim |
| B2 | Manifest has no absolute paths | every manifest path is POSIX-relative (`derived/...` only) |
| B3 | No home-directory leak | CWD/home prefix never appears in manifest or provenance |
| B4 | Diagnostics are measurements, not proof | diagnostics carry the honesty note, no scientific threshold claim |
| B5 | Fit in sensor pixel space | transform maps sensor-A → sensor-B pixels; `source_space`/`target_space` declared |
| B6 | Homography preferred, affine fallback | `transform_type` == `homography` when fit passes; `affine` + reason on fallback |
| B7 | Determinism across runs | identical pair + config → identical matrix, verdict, diagnostics |
| B8 | Re-run is not re-entrant | second run overwrites artefacts cleanly |
| B9 | Fresh pair is honest | `NOT_STARTED`, no fabricated verdict |
| B10 | BLOCKED when M5 selection missing | `NO_SELECTION` / `M5_NOT_AVAILABLE` block codes |
| B11 | Unknown config run → 404 | `RG-XXXX` run → block / 404 |
| B12 | Unknown pair → 404 | `/registration/CS-P999/**` → HTTP 404 |
| B13 | Loader rejects length mismatch | npz with mismatched arrays → `LENGTH_MISMATCH` cause |
| B14 | Loader rejects corrupt npz | truncated file → structured `COORDINATE_LOAD_FAILED` |
| B15 | Warp respects output bounds | registered output sized to the target window |
| B16 | No registered overlay claimed as proof | summary carries the honesty note on COMPLETE |
| B17 | Manifest hash is deterministic | SHA-256 of a given npz rewrites identically |
| B18 | w=0 homogeneous point excluded | zero-w correspondence never enters the fit |
| B19 | Degenerate (near-zero det) blocked | determinant guard → FAILED, not a silent overwrite |
| B20 | Symmetric-transfer max bounded | `symmetric_transfer_max_px ≤` limit on PASS |
| B21 | P95 residual bounded | residual p95 ≤ limit on PASS |
| B22 | Provenance chain length == 5 | M2→M6 node count and milestone ids verified |
| B23 | Provenance written before manifest | manifest hashes provenance deterministically |
| B24 | Reset is scoped | only `derived/registration/<pair>` removed; upstream untouched |
| B25 | End-to-end determinism | overview + status + verdict identical on re-run |
| B26 | **Loader rejects invalid scene_side** | `scene_side` outside {`a`,`b`} → `COORDINATE_LOAD_FAILED` |
| B27 | **Loader rejects out-of-range scene coords** | `scene_x/y` outside `[0,1]` → `COORDINATE_LOAD_FAILED` |
| B28 | **Validation independent recompute** | `validation.json` `state` VALIDATED + `independent_check.recomputed` true + `consistent_with_fit` true |
| B29 | **Transform/summary declare spaces** | `source_space`/`target_space`/`direction` present with correct frames |
| B30 | **Registered dtype enforced** | `registered_image.npy` is exactly `uint16`; meta records dtype/out_rows/out_cols |
| B31 | **Warp bounds failure is explicit** | target exceeding `max_output_rows` → `FAILED` + `OUTPUT_BOUNDS_INVALID` reason, not a silent blank |
| B32 | **Visualization listing + whitelist** | montages listed; unknown kind / non-`.png` → 404 |
| B33 | **Registered product endpoints** | array / valid-mask / preview served with correct media types |
| B34 | **Selected-evidence recap** | truthful count of consumed M5 evidence; 404 before it exists |
| B35 | **Config surface is complete** | `refine`, warp bounds, interpolation, format, normalization exposed via config endpoint |
| B36 | **Test isolation (no shared-config mutation)** | no test mutates the module-level `m6_config()` defaults (deep-copied in tests) |

All 36 cases pass as part of the 83-test M6 suite.

---

## 3. Regression

| Suite | Result |
|-------|--------|
| `pytest tests/test_m6.py -q` | **83 passed** in ~267 s |
| `pytest tests/ -q` (full) | **283 passed** in ~298 s |
| `smoke_test.py` (live HTTP: M1–M6) | **54/54 PASS** (overall PASS) |
| `npm run build` (frontend) | **built OK (vite, 41 modules)** |
| `node frontend/ssr-smoke.mjs` | **OVERALL PASS (11 SSR renders incl. RegistrationPanel, SpatialReliabilityPanel, TrustPanel, Pipeline)** |

No M1–M5 regressions observed; M5 trust/matching suites remain green.

---

## 4. Known limitations

1. **No scientifically tuned thresholds** — RANSAC iterations, residual bounds,
   inlier ratios and condition-number limits are **engineering defaults**
   (`scientifically_tuned false`), not laboratory-tuned lunar values. Every
   config carries the "no scientifically tuned lunar thresholds exist yet"
   note.
2. **Low residual ≠ physical truth** — validation verdicts certify a *fit in
   the recorded sensor pixel grid*, not physical registration accuracy. M6
   never claims CE90/LE90 or scientific alignment precision; `refine` is off
   and no accuracy/confidence fields exist.
3. **Real-data execution** — BLOCKED on PRADAN approval. M6 truthfully reports
   **BLOCKED** for real pairs; synthetic fixtures exercise the full code path
   in automated tests and a controlled TEMP e2e script only.
4. **Homography is a convenience model** — with affine fallback it captures
   planar (or locally planar) sensor geometry, not a rigorous photogrammetric
   model. Scientific registration remains a future milestone.
5. **Visualizations are best-effort** — montage generation never fails a run;
   the API serves only whitelisted `.png` kinds and reports honestly when they
   are absent.