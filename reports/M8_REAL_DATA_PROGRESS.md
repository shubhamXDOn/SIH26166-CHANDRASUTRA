# M8 — Spatial Reliability + Balanced Correspondence Selection — Progress Report

**Milestone:** M8 — consumes ONE ACCEPTED M7 trust gate artifact and its referenced M3/M4
matcher run, deterministically RECOVERS the trusted inlier correspondence set (re-verify,
never re-decide), computes per-side spatial bookkeeping evidence in the declared effective
matcher plane (coverage, occupancy, entropy, extent, centroid, spread) and records a
deterministic `GRID_BALANCED` selection as correspondence evidence only. The M8 status is a
state (`SELECTED` / `SELECTED_WITH_WARNINGS` / `ABSTAIN` / `BLOCKED` / `FAILED`) — NEVER a
numeric confidence, NEVER a "winner", NEVER a registration/accuracy claim
(`reference_status: REFERENCE_UNAVAILABLE`). The M7 verdict is never overridden.
**Report date:** 2026-09-23
**Execution status:** `CASE B (structural validation on correlated fixtures)`
**M8 TOOLING / STRUCTURAL VALIDATION = DONE** (53 M8 tests + M7 battery green; no lint
tooling exists in the repo)
**M8 GENUINE REAL-DATA EXECUTION = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Add a spatial reliability layer downstream of the new M7 trust gate: take the *accepted*
trusted inlier correspondences, prove they can be recovered byte-for-byte from the recorded
M7 artifact (deterministic re-verification against the artifact's own configuration
snapshot), quantify how those inliers occupy the effective matcher plane per side, and
record a reproducible, spatially balanced subset of them. The selection is evidence for
later stages (e.g. M9-style fitting) — it introduces no new points, no new decision and no
accuracy semantics. Boundaries are the M7 verdict (immutable), the declared effective
dimensions (frame honesty), the config snapshot (recoverability), and the vocabulary guard.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M8 configuration + config loader (`SR-M8-001`) | `DONE` |
| `backend/app/spatial_m8` package (states/config/grid/analysis/selection/engine/recovery/contract/service) | `DONE` |
| M8 API routers (status/runs/run/detail under `/spatial-m8`) | `DONE` |
| Frontend `M8SpatialReliabilityCard.jsx` wired into `Analysis.jsx` | `DONE` |
| Structural validation (53 M8 tests + M7 trust-gate battery green) | `DONE` |
| Real-data gate script executed | `DONE` → `BLOCKED` (PRADAN data absent) |
| Genuine real-data M8 execution (REAL PRADAN) | `BLOCKED_PENDING_OPERATOR_DATA` |
| Configuration of record | `SR-M8-001` (version 1, `scientifically_tuned: false`) |

## 3. Honesty rules honoured
- **Never re-decide M7:** recovery re-runs the exact snapshot config; any divergence in
  decision, decision-hash, dedup counts or inlier count → `BLOCKED / NONDETERMINISTIC_RECOVERY`.
- **Determinism everywhere:** no RNG in recovery, grid, analysis or selection; same M7
  artifact ⇒ identical decision + evidence + `decision_hash` (verified across separate runs).
- **Selection is a strict subset:** `selected ⊆ trusted` by construction; per-point
  `m8_index → m7_index → matcher correspondence index (+ match_index_a/b)` provenance kept.
- **Frame honesty:** coordinates are never rescaled; out-of-frame points are clipped only
  for occupancy bookkeeping and flagged `BOUNDARY_POINTS_REPORTED` (`edge_policy: REPORT_ONLY`).
- **No fabrication:** missing trust run → `BLOCKED / NO_TRUST_RUN`; non-ACCEPT trust →
  `BLOCKED / TRUST_NOT_ACCEPTED`; unrecoverable matcher → `BLOCKED / MATCH_RUN_UNRECOVERABLE`;
  real pair + synthetic trust → `BLOCKED / REAL_DATA_BLOCKED`.
- **Never a confidence/accuracy claim:** artifacts are scan-rejected for
  `confidence / final_confidence / best / winner / superior`; reference status stays
  `REFERENCE_UNAVAILABLE`.
- **Fixity:** one artifact per run under `data/metadata/m8_spatial`, never overwritten.

## 4. Configuration (SR-M8-001)
`configs/app.yaml` `m8_spatial:` block (id SR-M8-001, `derived_rel: metadata/m8_spatial`,
`scientifically_tuned: false`); `_M8S_DEFAULTS` + cached `m8_spatial_config()` in
`backend/app/config.py`; frozen dataclasses in `spatial_m8/config.py`.

| Block | Key values |
| --- | --- |
| grid | `rows: 8`, `cols: 8`, `edge_policy: REPORT_ONLY` |
| selection | `policy: GRID_BALANCED`, `max_selected: 4000`, `min_trusted: 4`, `min_selected: 1`, `min_per_occupied_cell: 1`, `min_occupied_cells: 4`, `tie_break: residual_then_original_index`, `limit_applied_warning: true` |
| coverage | `low_coverage_ratio: 0.25`, `concentration_ratio: 0.60` |
| execution | `max_runtime_seconds: 60` |
| reference_status | `REFERENCE_UNAVAILABLE` |
| forbidden_vocabulary | `[confidence, final_confidence, best, winner, superior]` |

All thresholds are engineering defaults registered in the artifact; none are tuned.

## 5. Status, warning, block and abstain contract
`decision` = `{state, reasons, explanation, block_code, abstain_code}` with `state ∈
(SELECTED, SELECTED_WITH_WARNINGS, ABSTAIN, BLOCKED, FAILED)`.
- warnings: `CONCENTRATED_SOURCE`, `CONCENTRATED_TARGET`, `LOW_SOURCE_COVERAGE`,
  `LOW_TARGET_COVERAGE`, `FEW_OCCUPIED_CELLS`, `SELECTION_LIMIT_APPLIED`,
  `BOUNDARY_POINTS_REPORTED`;
- block codes: `NO_TRUST_RUN`, `TRUST_NOT_ACCEPTED`, `TRUST_PAIR_MISMATCH`,
  `MATCH_RUN_UNRECOVERABLE`, `NONDETERMINISTIC_RECOVERY`, `INVALID_COORDINATE_FRAME`,
  `REAL_DATA_BLOCKED`, `INVALID_INPUT`, `INVALID_RECOVERY_STATE`;
- abstain codes: `ZERO_TRUSTED`, `FEW_TRUSTED`, `NO_VALID_SELECTION`, `RESOURCE_LIMIT`.

`evidence` (SELECTED branches): `trusted_count`, `selected_count`, `excluded_count`,
`limit_applied`, `analysis` (frame/grid + per-side `a`/`b` blocks), `selection_record`
(policy, tie_break, max_selected, `selected[]` entries with m8/m7/match indices, x/y coords,
9-dp residuals, `excluded_indexes`), and `frame` (EFFECTIVE_MATCHER_PLANE, side A/B
effective dims).

## 6. Trusted-set recovery (deterministic re-verification)
`spatial_m8/recovery.recover_trusted(trust_artifact, matcher_payload)` is audit recovery,
not a new decision:
1. require `decision.state == ACCEPT` else `BLOCKED / TRUST_NOT_ACCEPTED`;
2. reconstruct `TrustGateConfig.from_dict(artifact["configuration"])` (snapshot);
3. require declared effective dimensions for both sides else
   `BLOCKED / INVALID_COORDINATE_FRAME`;
4. require the matcher artifact's candidate correspondences else
   `BLOCKED / MATCH_RUN_UNRECOVERABLE`;
5. re-run `trust_gate.engine.verify(coords, cfg)`; require the recovered decision to equal
   the recorded decision **and** the recomputed 64-hex hash to equal `decision_hash`;
6. mirror the M7 dedup (round-to-6dp, keep-first) and require `deduplicated_candidate_count`
   to match the artifact;
7. compute the forward-residual mask (`< inlier_threshold_px` from the snapshot) and require
   the inlier count to match the artifact;
8. emit trusted entries with `m8_index/m7_index/match_index_a/b/x_a/y_a/x_b/y_b/score/
   descriptor_distance/residual` and the explicit provenance chain
   "M7 ACCEPT → deterministic re-verification → M8 trusted set".

## 7. Grid cell bookkeeping (frame honesty)
`grid.py`: deterministic integer `floor` partitioning into `rows×cols` cells over each
side's declared effective dimensions. Out-of-frame / non-finite points are flagged
(`edge_flags`) and clipped into a boundary cell purely for occupancy accounting; the
`REPORT_ONLY` policy means they are never dropped silently and never reinterpreted.

## 8. Per-side spatial analysis (definitions & units)
`analysis.py` `_side_block`, all in `px in effective matcher plane`:
- `count`, `occupied_cells`, `total_cells`, `coverage_ratio = occupied/total`;
- `max_cell_count`, `concentration_ratio = max_cell/n` (threshold 0.60);
- `entropy_normalized` — Shannon entropy over the cell distribution, normalised 0..1,
  `None` for 0/1 occupied cells ("no distribution to measure");
- `extent` (min/max per axis + `span_x_px/span_y_px/extent_diag_px`), `centroid`,
  `spread` (`std_x_px/std_y_px`).
Every value is rounded to 9 dp and is bookkeeping evidence — never accuracy.

## 9. Selection algorithm (GRID_BALANCED)
`selection.py` `select_balanced(entries, cfg)`, O(N log N), no RNG:
1. sort by `(residual asc, original m7_index asc)`;
2. if `n <= max_selected` → select all, `limit_applied: false`;
3. else group by occupied source cell (row-major); **phase 1** guarantees
   `min_per_occupied_cell` per occupied cell; **phase 2** refills the remaining
   `max_selected` budget round-robin across occupied cells so concentrated regions cannot
   swallow the budget; `limit_applied: true` (+ `SELECTION_LIMIT_APPLIED` warning).
Engine-level guarantees: trusted below `min_trusted` → `ABSTAIN / FEW_TRUSTED`; zero →
`ABSTAIN / ZERO_TRUSTED`; selection below `min_selected` → `ABSTAIN / NO_VALID_SELECTION`.

## 10. State machine (engine decision ladder)
`engine.analyze_and_select(trusted, dims_a, dims_b, cfg)` (pure): dims check →
`BLOCKED / INVALID_COORDINATE_FRAME`; zero trusted → `ABSTAIN / ZERO_TRUSTED`; few trusted →
`ABSTAIN / FEW_TRUSTED`; warnings (concentration/coverage/occupied-cells/boundary) →
`SELECTED_WITH_WARNINGS` else `SELECTED`. Wall-clock budget enforced at the service: an
over-budget SELECTED/ABSTAIN result is discarded and recorded `ABSTAIN / RESOURCE_LIMIT`.

## 11. Resolution & provenance
`SpatialSelectionService.run(pair_id, trust_run_id?)`: explicit `trust_run_id` (must belong
to the pair, else 404) → latest `ACCEPT` M7 run for the pair → newest M7 run regardless of
state (surfaced as `TRUST_NOT_ACCEPTED`) → none ⇒ recorded `BLOCKED / NO_TRUST_RUN`. The
matcher payload is read via `DeepMatcherService.read_any(matcher_run_id)` from the trust
artifact. `experiment_id = EXP-M8-<trust_run>-<matcher>-SR-M8-001`; provenance chain
`M2 -> M3/M4 (-> M6 adaptivity) -> M7 trust gate -> M8 spatial selection`.

## 12. API surface (all auth-guarded; mutating POST analyst-only)
- `GET /api/pairs/{pair_id}/spatial-m8/status` — configured SR-M8-001 view + latest run.
- `GET /api/pairs/{pair_id}/spatial-m8/runs` — spatial runs list (newest first).
- `POST /api/pairs/{pair_id}/spatial-m8/run` — body `{trust_run_id?}`; writes one artifact
  via `guard_run` (derived_stage `spatial-m8`, tag `m8_spatial_selection`).
- `GET /api/spatial-m8/runs/{run_id}` — full artifact read (404 if unknown).
Namespaced under `/spatial-m8` to avoid collision with the legacy M5 `/api/spatial` router.

## 13. Persistence & provenance
One artifact per run under `data/metadata/m8_spatial/<run_id>.json` (ids
`m8s-<pair>-<8hex>`), never overwritten, relative paths only, vocabulary scan-rejected.
Each artifact records: configuration snapshot, decision + `decision_hash`, evidence, recovery
block (method `deterministic_re_verification_M7`, state, recovered hash, trusted count),
`trust_run_id`/`matcher_run_id`/`matcher_id`, source gate, `synthetically_derived`, frame,
provenance chain, `runtime_ms`, environment snapshot (python/platform/numpy, RNG policy
`NONE`) and license text (spatial bookkeeping only; no accuracy/registration claim).

## 14. Blocked / abstain outcomes matrix
| Condition | Outcome |
| --- | --- |
| No M7 trust run resolvable for the pair | `BLOCKED / NO_TRUST_RUN` (persisted) |
| Resolved trust run not `ACCEPT` | `BLOCKED / TRUST_NOT_ACCEPTED` (persisted) |
| Referenced matcher artifact missing / wrong pair | `BLOCKED / MATCH_RUN_UNRECOVERABLE` |
| Recovered decision or hash differs from artifact | `BLOCKED / NONDETERMINISTIC_RECOVERY` |
| Dedup or inlier count differs from artifact | `BLOCKED / NONDETERMINISTIC_RECOVERY` |
| Side dims undeclared/non-positive, trusted empty / too few | `BLOCKED / INVALID_COORDINATE_FRAME`, `ABSTAIN / ZERO_TRUSTED`, `ABSTAIN / FEW_TRUSTED` |
| Selection below `min_selected` | `ABSTAIN / NO_VALID_SELECTION` |
| Wall-clock budget exceeded | override → `ABSTAIN / RESOURCE_LIMIT` |
| Real pair + synthetically-derived trust chain | `BLOCKED / REAL_DATA_BLOCKED` |
| Explicit trust run: unknown / wrong pair | `404` (raised, never ghosted) |

## 15. Real-data gate
`.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data` executed:
status `BLOCKED` — "Real PRADAN data is not present yet: no genuine OHRC product under
`data/raw/ohrc`; no genuine TMC-2 product under `data/raw/tmc2`". Gate evidence written to
`real_data_activation.json`. A real pair whose trust artifact is synthetic-derived is refused
by M8 (`REAL_DATA_BLOCKED`), mirroring the M7 gate. No REAL PRADAN execution is simulated.

## 16. Frontend
`M8SpatialReliabilityCard.jsx` wired into `Analysis.jsx` as the "Spatial selection · M8"
workspace: state badge, status chips (config, policy, grid, max-selected, real-data gate),
trust-run picker (auto → latest ACCEPT / explicit ACCEPT runs), Run spatial selection
(analyst-only), result panel (selected/excluded counts, source/target coverage, decision
hash, runtime, tone, reason/blocks), collapsible full evidence record, and spatial-runs
list. `npm run build` passes (53 modules).

## 17. Test summary
`tests/test_m8_spatial.py` — **53 passed**. Coverage: config load/forbidden vocabulary;
contract validator (valid, missing/bad decision, state, vocabulary leaks at depth);
grid (exact-boundary REPORT_ONLY flag, out-of-frame clipping incl. NaN, occupancy counts vs
positions); spatial analysis (metrics + units, concentration flag, low coverage + `INDEPENDENT`
coverage recomputation compared to engine output, entropy/degenerate cases, determinism);
selection (subset-of-inputs proof, per-cell minimum, round-robin budget ceiling, residual
priority, stability, limit flag); engine (INVALID_COORDINATE_FRAME, ZERO/FEW trusted abstain,
SELECTED state + selected⊆trusted proof, warnings + tone, boundary warning, determinism +
frame/units); recovery (ACCEPT → RECOVERY_OK + determinism, reproduction of M7 inlier
residuals contiguously under threshold with per-entry origin mapping, non-ACCEPT block,
tampered hash block, tampered inlier-count block, missing frame block, missing
correspondences block); service (404 without pair, NO_TRUST_RUN, TRUST_NOT_ACCEPTED,
end-to-end SELECTED artifact on disk with coordinates ⊆ matcher correspondences and
decision-hash round-trip, vocabulary-safe + no overwrite, deterministic two runs, unknown /
wrong-pair trust 404, real-data gate, status/list shape, run-id guard, provenance chain);
API E2E over correlated fixtures (status/runs empty, unknown detail 404, no-trust →
NO_TRUST_RUN, unknown trust 404, full register→prepare→baseline→trust→spatial E2E with list +
detail, status after runs).

## 18. Regression
M7 + M8 batteries run together: **111 passed** (`test_m7_trust_gate.py` 58 +
`test_m8_spatial.py` 53). Config/security/dirs suite green (17). App boots and the OpenAPI
schema registers all four `/spatial-m8` routes with the legacy M5 `/api/spatial` untouched.
(Genuine REAL PRADAN executions and the heavy matcher/processing real-data suites remain
gated on operator data; the milestone adds no code path to those modules.)

## 19. Known limitation / operator step
Genuine real-data spatial selection is `BLOCKED_PENDING_OPERATOR_DATA`. M8 consumes M7 trust
artifacts, which are gated on real OHRC/TMC-2 products. Once `.img`+`.xml` products are
provided, run `.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`;
the M2→M7→M8 chain then executes under the normal source gate.

## 20. Definition of Done mapping
- [x] `spatial_m8` package: states/config/grid/analysis/selection/engine/recovery/contract/service.
- [x] Deterministic M7 trusted-set recovery with hash + count cross-checks; refusal to re-decide.
- [x] GRID_BALANCED selection (per-cell minimum + round-robin budget), `selected ⊆ trusted`.
- [x] Per-side coverage/occupancy/entropy/extent bookkeeping in the effective matcher plane.
- [x] API under `/spatial-m8` (4 endpoints, analyst-guarded POST) registered in `api/router.py`.
- [x] Imperishable artifacts under `metadata/m8_spatial`, no overwrite, no absolute paths.
- [x] Vocabulary guard + REFERENCE_UNAVAILABLE on every artifact.
- [x] Real-data gate run; status `BLOCKED` (PRADAN data absent) reported honestly.
- [x] 53 M8 tests + M7 battery green; frontend card wired and building.
- [x] No M9 registration / accuracy semantics introduced.
- [ ] Genuine REAL PRADAN spatial selection — awaits operator data provisioning.

## 21. Sign-off status
**M8 TOOLING / STRUCTURAL VALIDATION = DONE**
**M8 GENUINE REAL-DATA EXECUTION = BLOCKED_PENDING_OPERATOR_DATA**