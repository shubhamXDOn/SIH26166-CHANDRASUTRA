# M9 — Registration & Image Alignment — Progress Report

**Milestone:** M9 — consumes ONE usable M8 spatial-selection artifact
(`SELECTED` / `SELECTED_WITH_WARNINGS`) for the pair, independently estimates a
DECLARED geometric transform under the smallest-valid policy (affine
least-squares preferred; normalized-DLT homography only when the affine matrix
is not mathematically usable or homography is explicitly requested), validates
it against declared engineering criteria, records residual diagnostics in px of
the effective matcher plane, and produces a derived aligned/warped output in
the target-B effective frame. The M9 status is a state
(`SUCCESS` / `SUCCESS_WITH_WARNINGS` / `ABSTAIN` / `BLOCKED` / `FAILED`) — NEVER
a numeric confidence, NEVER a "winner", NEVER a physical/geolocation accuracy
claim (`reference_status: REFERENCE_UNAVAILABLE`). The M7 verdict and the M8
status are never overridden.
**Report date:** 2026-09-23
**Execution status:** `CASE B (structural validation on correlated fixtures)`
**M9 TOOLING / STRUCTURAL VALIDATION = DONE** (74 M9 tests + M1–M8 / M10–M13
regression slices green; no lint tooling exists in the repo)
**M9 GENUINE REAL-DATA EXECUTION = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Deliver the registration / image-alignment stage on top of the M8 selected
correspondences: resolve EXACTLY ONE usable M8 artifact (explicit run or the
latest usable one for the pair), build the correspondence matrix strictly from
that artifact's recorded `selected[]` entries (per-point provenance
`m9_index → m8_index → m7_index → matcher correspondence`), fit a declared
transform, independently verify it (finite matrix, determinant, condition,
scale/shear bounds, forward residuals rmse/p95/max, homography denominator),
warp the source effective-plane display into the target-B effective frame as a
DERIVED artifact, and persist an immutable run record. The engineering
thresholds are declared, recorded, and never tuned to force acceptance
(`scientifically_tuned: false`). Registration residuals are geometric
measurements in the effective matcher plane — never a physical-accuracy claim.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M9 configuration + config loader (`RG-M9-001`) | `DONE` |
| `backend/app/registration_m9` package (states/config/contract/points/fit/validate/warp/service) | `DONE` |
| M9 API routers (9 routes under `/registration-m9` + pair-scoped) | `DONE` |
| Frontend `M9RegistrationCard.jsx` wired into `Analysis.jsx` (workspace + MODULE_PLAN) | `DONE` |
| Structural validation — 74 M9 tests passing | `DONE` |
| Mandatory M9 bug hunt (warp semantics CRITICAL + NaN residual found & fixed) | `DONE` |
| Real-data gate script executed | `DONE` → `BLOCKED` (PRADAN data absent) |
| Genuine real-data M9 execution (REAL PRADAN) | `BLOCKED_PENDING_OPERATOR_DATA` |
| Configuration of record | `RG-M9-001` (version 1, `scientifically_tuned: false`) |

## 3. Honesty rules honoured
- **Never overrides upstream:** the M7 verdict and the M8 status are read-only
  inputs; no code path rewrites them. M8 states outside the usable set lead to
  `BLOCKED / M8_SELECTION_NOT_AVAILABLE`, never to a reinterpreted selection.
- **Determinism everywhere:** affine is a direct least-squares solve; homography
  is a normalized DLT (two-point similarity normalization). No RNG, no iterative
  refinement; same M8 artifact + model ⇒ identical transform, residuals,
  decision and `decision_hash` (verified across separate runs).
- **Smallest-valid policy:** a technically valid affine is never re-fit as a
  homography to chase a better metric; homography is reserved for
  `AFFINE_INVALID_ESCALATED_HOMOGRAPHY` or explicit `EXPLICIT_HOMOGRAPHY`.
- **Frame honesty:** all coordinates and residuals are px in the declared
  effective matcher plane; the output frame is the target-B effective frame from
  the same M8 artifact, with a `BOUNDS_WARNED` warning if the display arrays
  disagree with the declared dims.
- **No fabrication:** missing M8 artifact → `BLOCKED / M8_SELECTION_NOT_AVAILABLE`;
  artifact structural tamper → `BLOCKED / INPUT_ARTIFACT_INVALID`; undeclared/non-
  positive dims → `BLOCKED / INVALID_COORDINATE_FRAME`; real pair + synthetic
  chain → `BLOCKED / REAL_DATA_BLOCKED`; fit/validation failure → honest
  `ABSTAIN` / `FAILED` states.
- **Never a confidence/accuracy claim:** artifacts are scan-rejected for
  `confidence / final_confidence / best / winner / superior / perfect / accurate`;
  reference status stays `REFERENCE_UNAVAILABLE`; license text calls residuals
  geometric measurements.
- **Fixity:** one artifact per run under `data/metadata/m9_registration`, never
  overwritten; relative paths only.

## 4. Configuration (RG-M9-001)
`configs/app.yaml` `m9_registration:` block (id RG-M9-001,
`derived_rel: metadata/m9_registration`, `scientifically_tuned: false`); cached
`m9_registration_config()` in `backend/app/config.py`; frozen dataclasses in
`registration_m9/config.py`. (Distinct from the legacy M6
`registration_configuration_id: RG-M6-001` and the Gemini AI `m9:` block
`ai_configuration_id: AI-M9-001`.)

| Block | Key values |
| --- | --- |
| model | `preference: smallest_valid`, `min_points_affine: 4`, `min_points_homography: 5`, `normalized_dlt: true` |
| validation | `max_rmse_px: 3.0`, `max_p95_px: 5.0`, `max_residual_max_px: 10.0`, `max_transform_condition: 1e6`, `min_abs_determinant: 1e-4`, `max_abs_coefficient: 1e4`, `min_homography_denominator: 1e-6`, `max_scale_change: 20.0`, `min_scale_factor: 1e-3` |
| warp | `interpolation: linear`, `border_mode: constant`, `fill_value: 0`, `dtype: uint16`, `output_dimensions: target_b_frame`, `max_output_rows/cols: 32768` |
| execution | `max_runtime_seconds: 120` |
| reference_status | `REFERENCE_UNAVAILABLE` |
| forbidden_vocabulary | `[confidence, final_confidence, best, winner, superior, perfect, accurate]` |

All thresholds are engineering defaults recorded in the artifact; none are tuned.

## 5. Status, warning, block, abstain and fail contract
`decision` = `{state, reasons, explanation, block_code, abstain_code}` with
`state ∈ (SUCCESS, SUCCESS_WITH_WARNINGS, ABSTAIN, BLOCKED, FAILED)`.
- warnings: `WARP_INPUT_MISSING`, `WARP_OUTPUT_SKIPPED`, `SCALE_CHANGE_LARGE`,
  `SHEAR_ANISOTROPY`, `NON_FINITE_POINTS_DROPPED`, `DUPLICATE_POINTS_DROPPED`,
  `HOLE_FILLED_VISUALIZATION`, `BOUNDS_WARNED`;
- block codes: `M8_SELECTION_NOT_AVAILABLE`, `REAL_DATA_BLOCKED`,
  `PRODUCT_MISSING`, `INVALID_COORDINATE_FRAME`, `INPUT_ARTIFACT_INVALID`,
  `UNKNOWN_CONFIG`;
- abstain codes: `INSUFFICIENT_SELECTED_POINTS`, `DEGENERATE_GEOMETRY`,
  `NO_VALID_TRANSFORM`, `RESOURCE_LIMIT`;
- fail codes: `TRANSFORM_FIT_ERROR`, `WARP_FAILED`, `ARTIFACT_WRITE_FAILED`.

`registration` (SUCCESS branches): `model_type`, `selection_reason`,
`algorithm`, `matrix 3x3`, `transform_hash`, residual statistics
(`count/rmse/p95/max/finite_count` in px of the effective matcher plane),
`checks`, `warnings`, `issues`, reverse-residual statistics, diagonality,
identity/similarity flags, `fit_diagnostics`. `warp`: `available`,
output dimensions, interpolation/border/fill/dtype, relative artifact refs
(registered npy, valid mask npy, preview, five visualization PNGs),
`valid_pixel_fraction`, `source_product_sha256`.

## 6. Resolution & provenance chain
`RegistrationM9Service.run(pair_id, m8_run_id?, model)`: explicit `m8_run_id`
must resolve to the pair (unknown/wrong-pair → 404) and be `SELECTED` /
`SELECTED_WITH_WARNINGS`; otherwise the LATEST usable M8 run for the pair is
resolved (newest first). Any M8 state outside the usable set →
`BLOCKED / M8_SELECTION_NOT_AVAILABLE`. Image hashes (`input_hashes`) capture
both the M8 artifact sha and the effective-plane display sha used in the warp.
Provenance chain: `M2 → M3/M4 (→ M6 adaptivity) → M7 trust gate → M8 spatial
selection → M9 registration`. `m7_trust_run_id`, `matcher_run_id`
and `matcher_id` are propagated from the M8 artifact for audit trail.

## 7. Point handling (strict subset, provenance-preserving)
`points.py` `prepare_points(selected, cfg)`: each `selected[]` entry — recorded
by M8 with `m8_index/m7_index/match_index_a/b/x_a/y_a/x_b/y_b/residual` — is
copied, tagged with a fresh sequential `m9_index`, and checked. Non-finite
coordinates and duplicate `(x_a, y_a, x_b, y_b)` pairs are dropped with an
explicit warning (`NON_FINITE_POINTS_DROPPED` / `DUPLICATE_POINTS_DROPPED`) and
reported; the fitted set is a strict subset of the M8-selected
correspondences — new points are never invented. Below `min_points_affine`
(4) → `ABSTAIN / INSUFFICIENT_SELECTED_POINTS`; degenerate (zero-Area /
all-collinear) geometry → `ABSTAIN / DEGENERATE_GEOMETRY`. Configuration
snapshot keys (`min_points_affine/homography`, `forbidden_vocabulary`,
`reference_status`) are validated against `RG-M9-001`, else
`BLOCKED / UNKNOWN_CONFIG`.

## 8. Model fit (fit.py)
- **Affine** `fit_affine`: linear least-squares over the
  `[x, y, 1]_{A} → [x, y]_{B}` design, direct `np.linalg.lstsq` (no RNG).
- **Homography** `fit_homography_normalized_dlt`: Hartley-style two-point
  similarity normalization of both sides, 9-parameter DLT design matrix, SVD
  null-vector solution, de-normalization `H = T_b^{-1} · H_norm · T_a`,
  `H/H[2,2]` normalization with a degenerate-homogeneous guard.
- **`choose_and_fit(pts_a, pts_b, cfg, requested_model)`**: `auto` → fit affine;
  usable (finite, non-singular linear part) and enough points ⇒
  `SMALLEST_VALID_AFFINE`; otherwise escalate to homography (
  `AFFINE_INVALID_ESCALATED_HOMOGRAPHY`) or fail. `affine` / `homography`
  force the model (`SMALLEST_VALID_AFFINE` / `EXPLICIT_HOMOGRAPHY`). Requested
  model is case-normalized so lowercase API values behave identically.
  Diagnostics record `algorithm`, counts, rank/condition, `fit_residual`,
  `normalization`, `dlt_condition`, and an explicit `rng: NONE` policy.
- Independent verification (`validate.py`): matrix finite, determinant of the
  linear part, condition number, singular-value scale/skew bounds, max
  coefficient magnitude, homography denominator spread across the source
  corners + selected points, forward (and reverse) residual statistics,
  diagonality/identity/similarity flags. Acceptance = every check true.

## 9. Residual diagnostics (definitions & units)
`residual_vector_lengths(pts_a, pts_b, matrix)` returns the per-point Euclidean
2-norm of `apply_matrix(matrix, pts_a) − pts_b`, i.e. the geometric distance in
px of the effective matcher plane between each M8-selected target point and the
transformed source point. `residual_statistics` reports `count`,
`rmse`, `p95`, `max`, `finite_count`, and each per-point residual is stored in
`points[].residual_px` (non-finite residuals sanitised to `null`). Thresholds
`max_rmse_px ≤ 3.0`, `max_p95_px ≤ 5.0`, `max_residual_max_px ≤ 10.0` are
checked; non-finite residuals are flagged `residuals_finite`. Reverse
statistics (B→A under the inverse) are recorded too. Everything is a
geometric observation in the declared plane — never physical accuracy.

## 10. Warp (warp.py) — derived aligned output
`warp_to_frame(src_a_display, matrix, out_h, out_w, cfg)` samples the source
display array into the target-B effective frame using an explicit inverse
homography map (`dst(x, y) → src` built from `H⁻¹`) via `cv2.remap` with
`INTER_LINEAR`, `BORDER_CONSTANT`, `fill_value 0`; degenerate denominator
locations are sent off-bounds. Outputs: `registered_image.npy` (to the declared
`uint16` dtype, integer-clipped), `valid_mask.npy` (pixel-exact validity),
`registered_preview.png` (derived preview PNG) and five diagnostic PNGs —
before/after panels, B-vs-registered checkerboard, absolute difference map,
red-green overlay, and per-point residual-vector plot (target green ←
transformed-source red). Missing display arrays → `SUCCESS_WITH_WARNINGS` +
`WARP_INPUT_MISSING`; any warp failure → `WARP_OUTPUT_SKIPPED`. The output is a
derived artifact of a geometric computation — no physical/geolocation accuracy
claim. `build_*` visualisations are best-effort under a `HOLE_FILLED_VISUALIZATION`
warning.

## 11. State machine (service decision ladder)
Resolution → gates → `prepare_points` → `choose_and_fit` → `validate_transform`
→ warp → decision. `validate` failure → `ABSTAIN / NO_VALID_TRANSFORM` and the
per-check issues are recorded verbatim. Wall-clock budget enforced at the
service: an over-budget `SUCCESS`-class result is discarded and recorded
`ABSTAIN / RESOURCE_LIMIT`. Allocation/env/config errors → `FAILED /
TRANSFORM_FIT_ERROR | WARP_FAILED | ARTIFACT_WRITE_FAILED`. SUCCESS branches
persist `registration` + `warp`; `warnings` promote the state to
`SUCCESS_WITH_WARNINGS`. Each run records a `decision_hash` over the deterministic
decision block and an environment snapshot (python/platform/numpy, RNG policy
`NONE`).

## 12. API surface (all auth-guarded; mutating POST analyst-only)
- `GET /api/pairs/{pair_id}/registration-m9/status` — RG-M9-001 view + latest run.
- `GET /api/pairs/{pair_id}/registration-m9/runs` — registration runs (newest first).
- `POST /api/pairs/{pair_id}/registration-m9/run` — body
  `{m8_run_id?, model: auto|affine|homography}`; writes one artifact via
  `guard_run` (derived_stage `registration-m9`, tag `m9_registration`).
- `GET /api/registration-m9/runs/{run_id}` — full artifact read (404 if unknown).
- `GET /api/registration-m9/runs/{run_id}/visualization` — warp visualization
  index (preview + allow-listed names).
- `GET /api/registration-m9/runs/{run_id}/preview` — registered preview PNG.
- `GET /api/registration-m9/runs/{run_id}/visualizations/{name}` — allow-listed
  PNG (unknown name → 404; no path traversal).
- `GET /api/registration-m9/runs/{run_id}/registered` — `registered_image.npy`.
- `GET /api/registration-m9/runs/{run_id}/valid-mask` — `valid_mask.npy`.
Namespaced under `/registration-m9` to avoid collision with the legacy M6
`/api/registration` router (the M1–M8/M10–M13 routes are untouched; OpenAPI
registers all nine new routes).

## 13. Persistence & provenance
One artifact per run under `data/metadata/m9_registration/<run_id>.json`
(ids `m9r-<pair>-<8hex>`; run-id regex-guarded), plus warp outputs under
`data/metadata/m9_registration/warp/<run_id>/`. `atomic_write_npy` /
`atomic_write_json` + a vocabulary guard: an artifact containing any forbidden
token is refused at write time. Absolute paths are never stored (`_rel` produces
forward-slash relative refs). Each artifact records: configuration snapshot,
decision + `decision_hash`, `registration` block, `warp` block, per-point
provenance, source gate + `synthetically_derived`, `input_hashes`
(M8 artifact + display arrays), `runtime_ms`, environment snapshot and license
text (geometric registration only; no accuracy claim). No artifact is ever
overwritten (unique run ids + no-overwrite write helper).

## 14. Blocked / abstain / fail outcomes matrix
| Condition | Outcome |
| --- | --- |
| No M8 artifact resolvable for the pair (none, or none usable) | `BLOCKED / M8_SELECTION_NOT_AVAILABLE` (persisted) |
| Resolved M8 state outside `SELECTED` / `SELECTED_WITH_WARNINGS` | `BLOCKED / M8_SELECTION_NOT_AVAILABLE` (persisted) |
| M8 artifact structurally invalid (missing/failed soft frames, bad selected entries) | `BLOCKED / INPUT_ARTIFACT_INVALID` |
| Undeclared / non-positive effective dims | `BLOCKED / INVALID_COORDINATE_FRAME` |
| Real pair + synthetically-derived chain | `BLOCKED / REAL_DATA_BLOCKED` |
| Config snapshot mismatch | `BLOCKED / UNKNOWN_CONFIG` |
| Selected points below `min_points_affine` | `ABSTAIN / INSUFFICIENT_SELECTED_POINTS` |
| Degenerate / zero-Area / collinear subset | `ABSTAIN / DEGENERATE_GEOMETRY` |
| Fitted transform fails validation | `ABSTAIN / NO_VALID_TRANSFORM` (issues recorded verbatim) |
| Wall-clock budget exceeded | override → `ABSTAIN / RESOURCE_LIMIT` |
| Fit / warp / write exceptions | `FAILED / TRANSFORM_FIT_ERROR | WARP_FAILED | ARTIFACT_WRITE_FAILED` |
| Explicit m8_run_id unknown / wrong pair | `404` (raised, never ghosted) |

## 15. Determinism proof
`test_m9_registration.py` verifies: (a) two successive `run()` calls for the
same pair produce identical artifacts (`fit_residual`, matrix entries,
`decision_hash`); (b) `fit_affine` / `fit_homography_normalized_dlt` produce
identical matrices across independent invocations; (c) DLT back-error sanity
(≈5.7e-14 for a pure homography) confirms both matrix conventions agree; (d)
the affine-first escalation only triggers on `AFFINE_INVALID_ESCALATED_HOMOGRAPHY`;
(e) the API-run path re-runs an existing pair without overwriting the earlier
artifact. RNG policy: `NONE` everywhere (`feed_dict`/`_environment_snapshot`
carry it into every artifact).

## 16. Mandatory bug hunt — findings & fixes
| Severity | Finding | Fix |
| --- | --- | --- |
| CRITICAL | `cv2.warpPerspective` in this build applies the matrix with FORWARD (src→dst) semantics (non-standard; inverse-mapping assumption returned all-zeros / misaligned output). | Warp rewritten as an explicit inverse-homography map (`dst→src`) built from `H⁻¹` and executed via `cv2.remap`, which honours the declared maps of the build; alignment verified numerically (spot lands at the transformed position; homography spot + valid-fraction checked). New regression test `test_warp_places_content_at_transformed_position`. |
| HIGH | Per-point `residual_px` could emit non-finite values into the JSON artifact (non-strict JSON). | Non-finite residuals are sanitised to `null` in `points[].residual_px`; aggregate stats already excluded them with an explicit note. |
| MEDIUM | `validate.py` crashed with `TypeError: bad operand type for abs(): NoneType` on a non-finite matrix in the determinant/condition issue writers. | Guarded: non-computable det/cond now emit explicit `SINGULAR_OR_TINY_DETERMINANT … not computable` / `HIGH_TRANSFORM_CONDITION … not computable` issues (covered by `test_validate_rejects_non_finite_matrix`). |
| MEDIUM | `choose_and_fit` compared the requested model against upper-case constants, so a lower-case `"homography"` silently fell through to `auto` and returned affine. | `requested_model` is case-normalized before branching (`test_choose_and_fit_explicit_homography` now asserts `HOMOGRAPHY`). |
| LOW | `m9_run_summary` read `decision_hash` only from the nested decision block, which is absent on blocked/fail runs. | Falls back to the top-level `decision_hash` (asserted in `test_service_status_shape_and_list_runs`). |

Also exercised: x/y swap (none — consistent `(x, y)` order across points,
apply, matrices, canvases), src/target reversal (warp verified content lands at
the B-frame position given by the A→B matrix), matrix convention (column-
homogeneous consistent across fit/validate/warp/residual vectors), homography
denominator (fit + warp + validate guards), singular matrices (lstsq +
`_matrix_usable` + inverse guard + validate), overwrite protection, path
leakage (regex run ids + allow-listed visualization names + relative refs only).

## 17. Real-data gate
`.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`
executed: status `BLOCKED` — "Real PRADAN data is not present yet: no genuine
OHRC product under `data/raw/ohrc`; no genuine TMC-2 product under
`data/raw/tmc2`". Gate evidence written to
`data/metadata/real_data_activation.json` (`products_scanned: 0`,
`source_breakdown` all zero). A real pair whose M8 artifact is
synthetically-derived is refused by M9 (`REAL_DATA_BLOCKED`), mirroring the
M7/M8 gates. No REAL PRADAN execution is simulated.

## 18. Frontend
`M9RegistrationCard.jsx` wired into `Analysis.jsx` as the
"Registration & image alignment · M9" workspace (plus a `registration-m9`
entry in `MODULE_PLAN`): state badge, status chips (config, model preference,
max rmse/p95, real-data gate, sensor classes), model picker (auto / affine /
homography), M8-run picker (auto → latest usable / explicit SELECTED runs),
Run registration (analyst-only, `guard_run`), BLOCKED explainer, result panel
(model, selection reason, correspondence count, residual RMSE px, accepted,
decision hash, warp, runtime), collapsible visualization gallery (preview +
allow-listed PNGs) and full evidence record, and the registration-runs list.
`npm run build` passes (54 modules).

## 19. Test summary
`tests/test_m9_registration.py` — **74 passed**. Coverage: config load +
distinctness from legacy M6 / AI M9 + forbidden vocabulary; contract validator
(valid, missing/bad decision, state/clean-hash, vocabulary leaks at depth);
point preparation (finite subset, dedup warnings, provenance, collapsed
geometry, min-points abstain); model fit (affine lstsq matches exact affine,
homography DLT matches a homography, affine-first auto, explicit homography
after case normalization, explicit affine, escalation, determinism, singular /
insufficient-points errors); validation (finite/non-finite matrix incl. the
`abs(None)` guard, residual stats incl. p95/rmse/max, checks, warnings for
anisotropic scale change, accepted-passthrough, homography denominator);
warp (shapes/settings, singular/non-finite/missing errors, dtype clipping,
content-at-transformed-position alignment regression, cast validation);
service (config status/list shape, resolution: none → M8_SELECTION_NOT_AVAILABLE,
unknown / wrong-pair m8 404, unusable M8 state block, end-to-end
`SUCCESS_WITH_WARNINGS` artifact on disk with correct fields, decision-hash
round-trip, warped output + relative paths, explicit-model honouring, no
overwrite, deterministic re-run, run-id guard, vocabulary safety, real-data
gate); API E2E over correlated fixtures (status/runs empty, unknown detail 404,
blocked without M8, full end-to-end run with list + detail + visualization
preview/allow-list, status after runs, visualization allow-list 404); M1–M8 +
M10–M13 regression smokes (configs, routes, legacy modules importable).

## 20. Regression
Targeted slices re-run green: `test_m8_spatial.py + tests_config + tests_dirs +
test_backend` = **74 passed**; `test_m7_trust_gate.py + test_m6_routing.py` =
**85 passed**; `test_m9.py` (AI suite) + `test_m5_condition.py` =
**109 passed**; plus the 74 M9 tests. App boots via `create_app(settings=...)`
and the OpenAPI schema registers all nine `/registration-m9` routes with the
legacy M6 `/api/registration` untouched. (Genuine REAL PRADAN executions and
the heavy matcher/processing real-data suites remain gated on operator data;
the milestone adds no code path to those modules.)

## 21. Known limitation / operator step
Genuine real-data registration is `BLOCKED_PENDING_OPERATOR_DATA`. M9 consumes
M8 selection artifacts, which are gated on real OHRC/TMC-2 products. Once
`.img`+`.xml` products are provided, run
`.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`; the
M2→…→M7→M8→M9 chain then executes under the normal source gate. Until then,
fixtures remain labelled `synthetically_derived` and real-data execution is
never simulated.

## 22. Definition of Done mapping
- [x] `registration_m9` package: states/config/contract/points/fit/validate/warp/service.
- [x] Resolution of ONE usable M8 artifact (explicit or latest; strict provenance).
- [x] Smallest-valid deterministic fit (affine lstsq; homography only on escalation / explicit request).
- [x] Independent validation + residual statistics in px of the effective matcher plane.
- [x] Derived aligned/warped output in the target-B effective frame (explicit map warp).
- [x] API under `/registration-m9` (9 endpoints, analyst-guarded POST) registered in `api/router.py`.
- [x] Imperishable artifacts under `metadata/m9_registration`, no overwrite, no absolute paths.
- [x] Vocabulary guard + `REFERENCE_UNAVAILABLE` on every artifact.
- [x] Mandatory bug hunt executed; CRITICAL warp-semantics bug fixed + regression-locked.
- [x] Real-data gate run; status `BLOCKED` (PRADAN data absent) reported honestly.
- [x] 74 M9 tests + M1–M8 / M10–M13 regression slices green; frontend card wired and building.
- [x] M7 verdict / M8 status never overridden; no physical-accuracy semantics introduced.
- [ ] Genuine REAL PRADAN registration — awaits operator data provisioning.

## 23. Sign-off status
**M9 TOOLING / STRUCTURAL VALIDATION = DONE**
**M9 GENUINE REAL-DATA EXECUTION = BLOCKED_PENDING_OPERATOR_DATA**