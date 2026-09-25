# M7 — Trust Gate (Geometric Verification) — Progress Report

**Milestone:** M7 — a deterministic, auditable TRUST GATE that consumes ONE M3/M4 matcher
run artifact (optionally the run the M6 router dispatched) and records a geometric
verification verdict (`ACCEPT` / `REJECT` / `ABSTAIN` / `BLOCKED`) plus evidence: seeded
RANSAC over numpy DLT, affine→homography hierarchy (smallest technically valid model first,
never threshold-promoted), duplicate counting, source/target degeneracy checks, residual
statistics in the effective matcher plane, and spatial-sanity signals. The gate is a gate
state — NEVER a confidence score and NEVER a physical/registration accuracy claim
(`reference_status: REFERENCE_UNAVAILABLE`). No M8 spatial selection, no M9 registration
semantics.
**Report date:** 2026-09-23
**Execution status:** `CASE B (structural validation on correlated fixtures)`
**M7 TOOLING / STRUCTURAL VALIDATION = DONE** (58 M7 trust-gate tests + full M1–M7
regression green; no lint tooling exists in the repo)
**M7 GENUINE REAL-DATA TRUST VALIDATION = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Add a trust gate layer, downstream of M3/M4 candidate correspondences and M6 adaptivity,
that answers one question per matcher run — *"do these candidate correspondences hold
together under a smallest-defensible geometric model, within declared gates?"* — and
persists an immutable verdict + evidence bundle. The M7 gate:
- accepts a matcher run artifact explicitly, or resolves it through M6 routing provenance
  (the run the router actually dispatched), or falls back to the latest successful
  baseline/deep run for the pair;
- verifies coordinates are finite and in the declared effective matcher plane per side;
- counts exact duplicates (never silently destroys them) before verification;
- checks source/target degeneracy before any fit;
- fits the configured model hierarchy with a seeded numpy RANSAC, keeping the FIRST
  technically valid model — a valid smaller model is never promoted merely to fail an
  acceptance threshold more comfortably;
- derives residual statistics in pixels and a spatial-sanity signal;
- records an immutable, scan-rejected artifact and a decision hash.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M7 configuration + config loader (`TG-M7-001`) | `DONE` |
| `backend/app/trust_gate` package (states/config/contract/engine/service) | `DONE` |
| M7 API routers (status/runs/run/detail) | `DONE` |
| Frontend `TrustGateCard.jsx` wired into `Analysis.jsx` | `DONE` |
| Structural validation (58 M7 trust-gate tests + M1–M7 regression green) | `DONE` |
| Genuine real-data trust validation | `BLOCKED_PENDING_OPERATOR_DATA` |
| Configuration of record | `TG-M7-001` (version 1, `scientifically_tuned: false`) |

## 3. Honesty rules honoured
- **Determinism:** `verify()` is pure geometry over seeded RANSAC; identical artifacts and
  configuration produce identical `decision` + `evidence` and an identical 64-hex
  `decision_hash` (verified run-to-run, including across separate service invocations).
- **No fabrication:** a run that never reached `SUCCESS`, or reached `SUCCESS` with zero
  correspondences, is persisted `BLOCKED / CANDIDATES_MISSING` — never padded or guessed.
  Exact duplicate mappings are counted (source/target sharing points recorded), then the
  unique basis is verified.
- **Frame honesty:** coordinates are never silently rescaled or reinterpreted. If either
  side cannot declare its effective dimensions, the run is `BLOCKED / INVALID_COORDINATE_FRAME`.
- **Real-data gate:** a `PATH_A_REAL_DATA` pair fed by a `synthetically_derived` matcher
  artifact is refused (`BLOCKED / REAL_DATA_BLOCKED`) — a synthetic-derived verdict on real
  products would be misleading.
- **No threshold-shopping:** `_choose_model` returns the first technically valid fit in the
  declared order (affine first). A valid affine that fails `min_inlier_ratio` stays affine
  and is `REJECT`ed; the engine never upgrades to homography to pass a gate (enforced by test).
- **Never a confidence/accuracy claim:** artifacts are scan-rejected (case-insensitive, at
  any depth) for `confidence / final_confidence / best / winner / superior`. The RANSAC
  probability is persisted as `confidence_parameter` inside the algorithm block.
- **Not a registration surrogate:** the gate records `reference_status: REFERENCE_UNAVAILABLE`
  and its license text states the verdict is geometric verification under configured
  thresholds, never physical/registration ground truth.
- **Fixity:** artifacts are written once and never overwritten; relative paths only.

## 4. Configuration (TG-M7-001)
New `m7_trust_gate:` section in `configs/app.yaml` (id TG-M7-001, version 1,
`derived_rel: metadata/m7_trust`, `scientifically_tuned: false`); `_M7T_DEFAULTS` +
`m7_trust_gate_config()` in `backend/app/config.py` (cached, YAML fallback, deep-merge),
loaded via `TrustGateConfig.from_dict`.

| Block | Key values |
| --- | --- |
| decision | `zero_candidates: ABSTAIN`, `min_candidates: 8`, `min_inliers: 8`, `min_inlier_ratio: 0.30`, `max_residual_rmse_px: 8.0`, `max_residual_median_px: 5.0`, `max_residual_p95_px: 12.0`, `max_runtime_seconds: 60` |
| geometry | models `[affine, homography]`, `preferred_model: affine`, `attempt_hierarchy: true`; ransac `max_iterations: 2000`, `inlier_threshold_px: 4.0`, `confidence_parameter: 0.99`, `seed: 20260923` |
| degeneracy | `min_unique_points: 6`, `max_condition_number: 1e6` |
| spatial_sanity | `min_extent_px: 5.0`, `strip_ratio_warn: 0.02` |
| duplicates | `policy: keep_first_record_counts` |
| resource | `max_candidates: 500000` |
| reference_status | `REFERENCE_UNAVAILABLE` |
| forbidden_vocabulary | `[confidence, final_confidence, best, winner, superior]` |

Thresholds are engineering defaults registered in the artifact; none are tuned against
downstream registration results.

## 5. Decision & evidence contract
`decision` = `{state, reasons, explanation, block_code, abstain_code}` where `state ∈
(ACCEPT, REJECT, ABSTAIN, BLOCKED)`. Stable codes: block — `PROCESSING_NOT_RUN`,
`MATCH_RUN_NOT_AVAILABLE`, `PRODUCT_MISSING`, `CANDIDATES_MISSING`,
`INVALID_COORDINATE_FRAME`, `INVALID_INPUT`, `REAL_DATA_BLOCKED`,
`TRUST_ESTIMATION_FAILED`, `RESOURCE_LIMIT`; abstain — `ZERO_CANDIDATES`,
`INSUFFICIENT_CANDIDATES`, `DEGENERATE_GEOMETRY`, `NO_VALID_MODEL`, `RESOURCE_LIMIT`;
reject — `INSUFFICIENT_INLIERS`, `LOW_INLIER_RATIO`, `RESIDUAL_EXCEEDED`,
`SPATIAL_SANITY_FAILED`, `MODEL_INVALID`.

`evidence` (all decision branches, consistent schema): `candidate_count`,
`verified_count`, `deduplicated_candidate_count`, `exact_duplicate_count`,
`source_sharing_points`, `target_sharing_points`, `inlier_count`, `outlier_count`,
`inlier_ratio`, `model` (+ `model_attempts`), `residual_statistics`
(count/mean/median/rmse/p90/p95/max/min, units `px in effective matcher plane`),
`spatial_sanity` (PASS/WARN/FAIL + reasons), `degeneracy` (detected/flags/reason).
Model block: `model_type`, `model_algorithm` (`DLT_RANSAC_NUMPY_SEEDED`),
`model_parameters` (models, preferred_model, inlier_threshold_px, max_iterations,
confidence_parameter, seed_used, iterations_used), `model_matrix`, `model_valid`,
`determinant_linear_part`.

## 6. State machine (pure engine + pre-flight)
`verify(coords, cfg)` in `engine.py`:
1. `None`/empty → `ABSTAIN / ZERO_CANDIDATES`.
2. NaN/Inf in any coordinate → `BLOCKED / INVALID_INPUT` (with `non_finite_count`).
3. candidates > resource cap → `ABSTAIN / RESOURCE_LIMIT` (recorded, never truncated).
4. dedup first occurrences (keep-first policy); `verified < min_candidates` →
   `ABSTAIN / INSUFFICIENT_CANDIDATES`.
5. source+target degeneracy (insufficient/identical/collinear/high-cond) →
   `ABSTAIN / DEGENERATE_GEOMETRY`.
6. hierarchy fit; no technically valid model → `ABSTAIN / NO_VALID_MODEL`.
7. inlier gates (count, ratio, residual stats, spatial FAIL) → `REJECT` with the
   failing reasons; else `ACCEPT` with explicit OK reasons.
Wall-clock budget: if the recorded run exceeds `max_runtime_seconds`, the verdict is
overridden to `ABSTAIN / RESOURCE_LIMIT` with the discarded result noted.

## 7. Resolution & provenance
`TrustGateService.run(pair_id, matcher_run_id, routing_run_id)` resolves the input artifact:
explicit `matcher_run_id` (via `DeepMatcherService.read_any`, baseline or deep) → explicit
`routing_run_id` (reads the M6 artifact's `execution.runs[final_route].run_id`) → newest
routing run for the pair that dispatched a matcher run → latest successful baseline/deep
run. Provenance (`matcher_run_id`, `matcher_id`, `routing_run_id`, `routing_mode`) and
`experiment_id` (`EXP-M7-<MODE|NONE>-<matcher>-TG-M7-001`) are persisted. A matcher run of
a different pair raises `404`; no available artifact raises
`404 … MATCH_RUN_NOT_AVAILABLE`.

## 8. API surface (all auth-guarded)
- `GET /api/pairs/{pair_id}/trust/status` — configured TG-M7-001 view + latest run.
- `GET /api/pairs/{pair_id}/trust/runs` — list of trust runs (newest first).
- `POST /api/pairs/{pair_id}/trust/run` — body `{matcher_run_id?, routing_run_id?}`;
  writes one artifact via `guard_run` (derived_stage `trust-gate`, tag `m7_trust_gate`).
- `GET /api/trust/runs/{run_id}` — full artifact read (404 for unknown; no collision with
  the existing M4 `/{pair_id}` trust namespace).

## 9. Persistence & provenance
One artifact per run under `data/metadata/m7_trust/<run_id>.json` (ids
`tg7-<pair>-<8hex>`), never overwritten. Each artifact records the configuration snapshot,
decision + evidence, `decision_hash`, `runtime_ms`, frame block (side A/B effective
dimensions, resample factors, source products, `frame_declared`), input `sha256` refs,
source gate, `synthetically_derived`, `matcher_configuration_id`, provenance chain
`M2 -> M3/M4 (-> M6 adaptivity) -> M7`, environment snapshot (python/numpy/cv2 versions,
seeded-RNG policy) and license text.

## 10. Blocked-outcome matrix
| Condition | Outcome |
| --- | --- |
| No matcher artifact resolvable | `404 MATCH_RUN_NOT_AVAILABLE` (surfaced, never ghosted) |
| Matcher run not `SUCCESS` | `BLOCKED / CANDIDATES_MISSING` (persisted) |
| `SUCCESS` with zero correspondences | `BLOCKED / CANDIDATES_MISSING` (persisted) |
| Side A or B without declared effective dimensions | `BLOCKED / INVALID_COORDINATE_FRAME` |
| NaN/Inf candidate coordinates | `BLOCKED / INVALID_INPUT` |
| Real pair + synthetically-derived matcher artifact | `BLOCKED / REAL_DATA_BLOCKED` |
| Candidates > 500,000 | `ABSTAIN / RESOURCE_LIMIT` |
| Wall-clock budget exceeded | override → `ABSTAIN / RESOURCE_LIMIT` |

## 11. Frontend
`frontend/src/components/TrustGateCard.jsx` wired into `Analysis.jsx` as the
"Trust Gate · M7" workspace: state badge, status chips (config, preferred model, min
inliers/ratio, synthetic/real gate), matcher-run picker (auto / baseline / deep runs), Run
trust gate, verdict panel (state badge, reason codes, model, block/abstain codes,
explanation, candidates/verified/inliers/ratio, decision hash, provenance, runtime),
collapsible full evidence record, and trust-run list. Honest wording throughout;
`npm run build` passes (52 modules).

## 12. Test summary
`tests/test_m7_trust_gate.py` — **58 passed**. Coverage: config load + snapshot shape +
forbidden vocabulary; ZERO_CANDIDATES / INSUFFICIENT_CANDIDATES / INVALID_INPUT (NaN & Inf)
/ RESOURCE_LIMIT / DEGENERATE_GEOMETRY (source+target flags) / NO_VALID_MODEL-honest
abstain; ACCEPT on clean affine; ACCEPT with 40–45% outliers; REJECT on random noise;
REJECT/LOW_INLIER_RATIO with NO promotion to homography; REJECT/RESIDUAL_EXCEEDED under a
widened RANSAC threshold; REJECT/SPATIAL_SANITY_FAILED on a tiny cluster; ACCEPT with
SPATIAL WARN (CONCENTRATED_STRIP); forced homography path (3×3 matrix, `model_valid`, seed
recorded); duplicate counting (exact, source/target sharing); determinism; residual units
& stats; identical-point batch → honest ABSTAIN; contract validator (all four states,
missing/bad decision, vocabulary leaks at any depth, `confidence_parameter` allowed);
service resolution (explicit run, M6 routing provenance with mode/experiment, latest-run
fallback, pair mismatch 404, unknown run 404, missing artifact 404); blocked artifacts
(non-SUCCESS, zero candidates, missing input block, undeclared frame); REAL_DATA_BLOCKED
via synthetic artifact on a real pair and ACCEPT when the real artifact is not synthetic;
status/runs/read; no-overwrite; no forbidden words / no absolute paths; E2E over correlated
fixtures (baseline matcher → ACCEPT-level verdict, routing provenance E2E, auto-resolve
latest, artifact on disk, decision_hash round-trip, runs list + detail).

## 13. Regression (M1–M7)
Batched `.venv\Scripts\python.exe -m pytest` across the whole suite, all green:
config/dirs/backend/security/M6-routing/M5-condition/M7-trust 154; M1+M2+M3+M7+M8+M9 199;
M4+M5+M6 184; M10+M11+M12+M13 150; real-data orchestration (M1–M4) 94 → **781 passed,
0 failed** (the M7 file adds 58 tests on top of the previous 723).

## 14. Known limitation / operator step
Genuine OHRC/TMC-2 trust validation remains `BLOCKED_PENDING_OPERATOR_DATA` — the gate
consumes M3/M4/M6 run artifacts, which are themselves gated on real products. Once real
`.img`+`.xml` products are provisioned, run
`.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`; matchers and the
M7 gate then run under the normal source gate, and a real-data pair fed by a
synthetically-derived artifact is refused honestly.

## 15. Definition of Done mapping
- [x] Trust gate package/service/API/frontend (TG-M7-001).
- [x] Deterministic geometric verification; decision-hash determinism verified.
- [x] Model hierarchy with smallest-first policy; no threshold-promotion.
- [x] Frame, candidates, real-data and resource pre-flight gates.
- [x] All four decision states with stable, persisted codes.
- [x] Forbidden vocabulary scan-enforced on artifacts.
- [x] Persisted artifacts, no overwrite, no absolute paths.
- [x] 58 M7 tests green; report written.
- [x] No M8 spatial selection / M9 registration semantics introduced.
- [ ] Real-data trust validation — awaits operator data provisioning.

## 16. Sign-off status
**M7 TOOLING / STRUCTURAL VALIDATION = DONE**
**M7 GENUINE REAL-DATA TRUST VALIDATION = BLOCKED_PENDING_OPERATOR_DATA**