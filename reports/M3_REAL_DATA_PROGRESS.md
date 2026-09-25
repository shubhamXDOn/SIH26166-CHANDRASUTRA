# M3 — Real Data Baseline Matching (SIFT · AKAZE · ORB) — Progress Report

**Milestone:** M3 — Classical baseline matching: candidate correspondences via
explicit matcher contract (SIFT primary, AKAZE recommended, ORB auxiliary)
**Report date:** 2026-09-21
**Execution status:** `CASE C (no genuine OHRC/TMC-2 products on disk)`
**M3 TOOLING / STRUCTURAL VALIDATION = DONE**
**M3 REAL PRADAN MATCHING = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Deliver a production-grade classical baseline matcher that turns M2-validated
display products into **candidate correspondence observations** for genuine
OHRC × TMC-2 pairs — SIFT (primary), AKAZE (recommended), ORB (auxiliary) —
all sharing one explicit, deterministic, recorded contract. Candidates are
observations; they are **never inliers, never trusted, never registered**, and
no result here is a scientific accuracy or trust verdict. Only the M4 Trust
Gate (later milestone) may verify geometry; only the M6 registration engine may
register. Because genuine PRADAN `.img`+`.xml` are still absent (CASE C), M3
delivers the complete, honest tooling and verifies it on TEST_FIXTURE
correlated scenes under an explicit `REAL_DATA_BLOCKED` data gate.

## 2. Configuration (MB-M3-001)
- New `m3_baseline:` section in `configs/app.yaml` (id `MB-M3-001`,
  `configuration_version: 1`); `PipelineConfig.m3_baseline`, loader
  `setdefault`, `_M3B_DEFAULTS` and `m3_baseline_config()` added to
  `backend/app/config.py`.
- Explicit defaults, fully snapshotted into every artifact (no silent OpenCV
  defaults):
  - execution: `max_runtime_seconds 60`, `max_image_dimension 2048`,
    `max_features 4000`; visualization `enabled true`, `max_lines 120`,
    `max_side_px 960`.
  - sift detector `nfeatures 2000, n_octave_layers 3, contrast_threshold 0.04,
    edge_threshold 10, sigma 1.6`; matching `cross_check true,
    ratio_threshold 0.8, max_distance 350`.
  - akaze detector `MLDB, descriptor_size 0, descriptor_channels 3,
    threshold 0.001, n_octaves 4, n_octave_layers 4, diffusivity PM_G2`;
    matching `cross_check true, ratio_threshold 0.8, max_distance 100`.
  - orb detector `nfeatures 2000, scale_factor 1.2, nlevels 8,
    edge_threshold 31, fast_threshold 20`; matching `cross_check true,
    ratio_threshold 0.85, max_distance 60`.
- OpenCV keyword mapping fixed against cv2 5.0.0 (SIFT uses `nOctaveLayers/
  contrastThreshold/edgeThreshold`; ORB uses `scaleFactor/edgeThreshold/
  fastThreshold`; AKAZE uses `descriptor_type/descriptor_size/nOctaves/
  diffusivity`).

## 3. Common matcher contract
- `MatcherInput` (matcher id, uint8/uint16 2-D images, invalid masks `0=valid`)
  → `MatcherOutput` (full JSON-able record: status SUCCESS/BLOCKED/FAILED,
  keypoint counts, raw + candidate counts, per-correspondence
  `{x_a,y_a,x_b,y_b,score,descriptor_distance,match_index_a,match_index_b}`,
  score/distance summaries, runtime_ms, warnings, error code+detail, recorded
  configuration + determinism + environment snapshots, explicit filter funnel).
- `Correspondence` is a plain observation record with A/B indices kept intact
  (verified by independent brute-force nearest-neighbour symmetry checks).

## 4. Availability probing (honest, never fabricated)
- SIFT (`SIFT_create`) and ORB (`ORB_create`) are present in this build;
  AKAZE (`AKAZE_create`) is **absent** (OpenCV 5.0.0).
- `matcher_available()` returns `(False, reason)`; `capability_public()` emits
  `available: False` + long-form reason; a requested AKAZE run writes a
  truthful `MATCHER_NOT_AVAILABLE` blocked artifact. Nothing is simulated and
  no package is auto-installed.

## 5. Explicit filters (candidate funnel, all counted)
- Lowe ratio test (`knn k=2`, per-matcher ratio threshold), bidirectional
  cross-check (reverse k-NN with `cross_check`), and a per-matcher descriptor
  distance ceiling (`max_distance`). Every rejected/kept count is recorded in
  `filters.ratio_test/cross_check/distance/funnel` — e.g. SIFT
  `459 → after_ratio 341 → candidates 337`.

## 6. Resource-safe input resolution
- `_resize_recorded()` downsizes M2 display/mask products with recorded
  INTER_AREA resampling when the long edge exceeds `max_image_dimension`
  (masks follow with INTER_NEAREST, `0=valid` preserved); every effective
  dimension + factor is recorded; original `native_dimensions` and source
  product sha256 are kept. No naive full-resolution processing.

## 7. Determinism + reproducibility
- Fixed input + fixed configuration ⇒ fixed output within a library build.
  Deterministic rerun equality is asserted (modulo wall-clock `runtime_ms`) for
  SIFT and ORB; OpenCV version, numpy version, Python and platform are recorded
  in every artifact so reruns are comparable across builds.

## 8. Persistence & provenance
- Unique run ids `m3-<pair_id>-<matcher>-<hex8>` → artifacts written atomically
  to `data/metadata/m3_matching/<run_id>.json` (never overwritten; defensive
  halt on collision). Provenance: relative `source_product.rel` + sha256 for
  each side, `source_gate` (data_source_gate / source_class A/B),
  `synthetically_derived`, and a `license` that states candidates are
  observations, not a verdict. Absolute filesystem paths never leak into
  artifacts (the config `source` is recorded as its file name only).

## 9. Real-data gate (machine-readable)
- `real_data_gate()` scans the raw inventory and reports
  `REAL_DATA_BLOCKED` (no genuine PRADAN products), `REAL_DATA_AVAILABLE`
  (genuine OHRC×TMC-2 present), or `REAL_DATA_STATUS_UNKNOWN`. Exposed on
  `GET /matching/{pair_id}/baseline/status.data_gate`. On this tree the gate is
  `REAL_DATA_BLOCKED`, consistent with `scripts/activate_real_data.py` exit 2.

## 10. Service & API surface
- `BaselineMatcherService` (`backend/app/matching/baseline.py`) with `run`,
  `read`, `list_runs`, `latest_for_pair`, `resolve_processed_inputs` (requires
  M2 `READY_FOR_MATCHING`; else `PROCESSING_NOT_RUN`; missing/corrupt products
  ⇒ `PRODUCT_MISSING`), `capabilities_public`, `_write_visualization` (PNG
  side-by-side with deterministic candidate lines).
- Routes (declared before `/{pair_id}` in `api/matching.py`):
  `GET /baseline/capabilities`, `GET /runs/{run_id}`,
  `GET /runs/{run_id}/visualization`, `POST /{pair_id}/baseline/run` (under
  `guard_run`, tag `m3_baseline`), `GET /{pair_id}/baseline/status`,
  `GET /{pair_id}/baseline/runs`; plus `GET /pairs/{pair_id}/matches` in
  `api/pairs.py`. Unknown run/pair → 404; unknown matcher → 422.

## 11. Frontend workspace
- `frontend/src/components/BaselineMatchingCard.jsx` + wiring in
  `pages/Analysis.jsx`: matcher selector with honest availability badges
  (AKAZE disabled + NOT_AVAILABLE reason), RUN button guarded against
  double-submit and viewer roles, keypoint/candidate counts, descriptor
  distance + score summaries, candidate-line PNG preview, BLOCKED detail,
  full evidence `<pre>`, explicit **Candidate ≠ Trusted ≠ Registered** legend,
  and a SYNTHETIC/operator-data source badge. `npm run build` clean (vite
  7.3.6, 48 modules).

## 12. Test coverage (`tests/test_m3_realdata.py`, 28 tests)
Groups: contract interface/serialization; SIFT candidates; SIFT/ORB
deterministic rerun; AKAZE registered-and-truthful-unavailable; correspondence
schema validity; coordinate semantics under translation (median error < 4 px);
score/distance summary bounds; explicit ratio-filter sharpening; cross-check
never-increases + independent brute-force mutual-nearest-neighbour symmetry;
empty-keypoint block; tiny-window block; low-texture no-fabrication;
incompatible-scenes no-crash/no-claim; missing-product `PRODUCT_MISSING`;
unprepared pair `PROCESSING_NOT_RUN`; unknown pair/matcher 404/422; fixture-only
`REAL_DATA_BLOCKED`; real-shaped pair shared gates; synthetic separation
(`TEST_FIXTURE` + `PATH_B_SYNTHETIC_ONLY`, never `REAL_PRADAN`); artifact
persistence + unique run ids + no-absolute-path provenance; API success flow
(status / get-run / visualization PNG / runs / pairs-matches); AKAZE blocked
artifact; M1 raw immutability regression; M2 products presence regression;
M13-style honesty structure (no `confidence`/`final_confidence` fields);
frontend build.

## 13. Milestone regression (all green)
- `test_m1.py test_m1_realdata.py test_m2.py test_m2_realdata.py test_m3.py
  test_m3_realdata.py test_m8.py` — **148 passed**.
- `test_m10.py test_m11.py test_m12.py test_m13.py` — **150 passed**.
- `test_backend.py test_config.py test_m4.py` — **51 passed**.
- `npm run build` — clean.

## 14. Representative execution (TEST_FIXTURE correlated scene, E2E)
- SIFT: 459 / 502 keypoints, 459 raw → 341 after ratio → **337 candidates**
  (~463 ms, 700×520 effective windows).
- ORB: 1987 / 2000 keypoints, 1987 raw → 1242 after ratio → **999 candidates**
  (~154 ms).
- AKAZE: **BLOCKED · MATCHER_NOT_AVAILABLE** (OpenCV 5.0.0 lacks
  `AKAZE_create`); blocked artifact persisted with the reason.
- `data_gate`: `REAL_DATA_BLOCKED`; `synthetically_derived: true`,
  `source_gate.data_source_gate = PATH_B_SYNTHETIC_ONLY` on all fixture runs.

## 15. Bugs found & fixed during the hunt
1. `run_baseline_contract` ignored the injected configuration when building the
   detector (`_detector_for` re-read the on-file config) — now threads the
   explicit `cfg` through, so test-injected configurations are honoured.
2. `real_data_gate()` passed a `Path` where `scan_raw_products()` expects the
   Settings object → gate silently degrades to `REAL_DATA_STATUS_UNKNOWN`;
   signature corrected and wired with the Settings object.
3. Absolute config path leaked into persisted artifacts via
   `configuration.source` — snapshots now record only the config file name.
4. Strictest work needed in-kernel: `x_b`/`y_b` A/B reading was validated
   independently (translation test + brute-force symmetry) so coordinate
   semantics are proven, not assumed.
5. Test-side fixes: `runtime_ms` wall-clock excluded from determinism equality;
   npm resolved via `npm.cmd` on Windows; AKAZE blocked payload shape
   (`matcher` carries the blocked `MatcherOutput`, never fabricated).

Remaining honest limits (not bugs): AKAZE is registered but truly unavailable
in this OpenCV build (real blocker, not a fallback); candidate counts depend on
scene texture; genuine real-data matching is impossible without genuine files.

## 16. Honesty enforcements
- Candidates are produced and stored **only** as observations; no RANSAC /
  homography / inlier / trust / registration logic exists anywhere in the
  baseline path.
- Artifacts carry the "not a scientific accuracy or trust verdict" license; the
  word `confidence` never appears in any persisted run artifact.
- Synthetic (TEST_FIXTURE) runs are flagged `synthetically_derived` +
  `PATH_B_SYNTHETIC_ONLY` and are never presented as genuine PRADAN results.
- Blocked is a first-class written outcome for every gate
  (MATCHER_NOT_AVAILABLE / PROCESSING_NOT_RUN / PRODUCT_MISSING /
  INVALID_INPUT / REAL_DATA_BLOCKED).

## 17. Artifacts (added/modified)
- `backend/app/matching/baseline.py` (**new** — contract, contract runner,
  availability probe, config resolution + snapshots, real-data gate, service,
  run summary, runner util), `backend/app/config.py` + `configs/app.yaml`
  (**MB-M3-001**), `backend/app/api/matching.py` (**baseline routes**),
  `backend/app/api/pairs.py` (**`GET /pairs/{pair_id}/matches`**),
  `frontend/src/components/BaselineMatchingCard.jsx` (**new**),
  `frontend/src/pages/Analysis.jsx` (**wired**),
  `tests/test_m3_realdata.py` (**new, 28 tests**),
  `reports/M3_REAL_DATA_PROGRESS.md` (**this file**). The pre-existing M3
  adaptive engine (`matching/engine.py`, adapters, `test_m3.py`) is untouched
  and green — the baseline is additive, not a replacement.

## 18. Boundary conditions verified
- Empty/constant image → `BLOCKED INVALID_INPUT` ("Not enough features");
  smaller than 8×8 → blocked; low-texture never fabricates candidates;
  incompatible noise-vs-noise scenes never crash and never exceed the raw match
  funnel; mask conventions (`0=valid`) survive resize and are converted
  correctly for OpenCV; duplicate/no-op runs are unique; path-traversal run ids
  are rejected by `_safe_run_id`.

## 19. Blocked item (operator)
Genuine `.img`+`.xml` under `data/raw/ohrc` and `data/raw/tmc2` are still
absent. On copy:
```
.\.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data
```
then re-run M2 PREPARE and `POST /api/matching/<pair>/baseline/run` for
sift/akaze/orb; the `data_gate` flips to `REAL_DATA_AVAILABLE` and genuine
PRADAN matching becomes possible (fixture-derived results remain
structure-validation only).

## 20. Final state
**DONE** (M3 tooling, contract, filters, persistence, API, UI, tests,
regression), **BLOCKED** (genuine PRADAN matching — pending operator data,
plus AKAZE `NOT_AVAILABLE` in this OpenCV build). No M14 introduced; M0–M13
preserved and re-verified.

---

**Milestone:** M3 — classical baseline matching (SIFT · AKAZE · ORB)
**STATUS:** TOOLING/STRUCTURAL VALIDATION DONE — REAL PRADAN MATCHING BLOCKED_PENDING_OPERATOR_DATA
**VERIFIED-ON:** 2026-09-21
**NEXT:** operator copies real files → activate → M2 PREPARE → baseline runs → report; revisit AKAZE when an OpenCV build ships `AKAZE_create`.