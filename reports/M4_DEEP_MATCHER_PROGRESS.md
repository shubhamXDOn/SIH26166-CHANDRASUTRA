# M4 — Strong/Deep Matcher Integration (SuperPoint + SuperGlue) — Progress Report

**Milestone:** M4 — integrate the primary deep matcher (SuperPoint + SuperGlue)
through the SAME M3 candidate-correspondence contract, with honest capability
probing; LoFTR and RIFT2 remain declared, explicitly non-available OPTIONAL matchers.
**Report date:** 2026-09-22
**Execution status:** `CASE B (no genuine OHRC/TMC-2 products on disk)`
**M4 TOOLING / STRUCTURAL VALIDATION = DONE**
**M4 REAL PRADAN DEEP MATCHING = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Deliver a production-grade strong/deep matcher (SuperPoint + SuperGlue via the
official pretrained checkpoints) that turns M2-validated display products into
**candidate correspondence observations** for genuine OHRC × TMC-2 pairs.
The deep matcher reuses the exact M3 `MatcherInput → MatcherOutput` contract so
classical and deep matching are interchangeable at the pipeline boundary. Deep
candidate correspondences are observations — **never inliers, never trusted,
never registered** — and model-native scores are assignment probabilities,
**never a confidence, accuracy or trust verdict**. The M4 Trust Gate (later
milestone) remains authoritative. Because genuine `.img`+`.xml` PRADAN products
are still absent (CASE B), M4 delivers the complete, honest tooling and verifies
it on TEST_FIXTURE correlated scenes under an explicit `REAL_DATA_BLOCKED` source gate.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M4 TOOLING (deep contract, probe, service, API, frontend, tests) | `DONE` |
| M4 STRUCTURAL / INTEGRATION VALIDATION (655 tests green) | `DONE` |
| M4 REAL PRADAN DEEP MATCHING | `BLOCKED_PENDING_OPERATOR_DATA` |
| Primary deep matcher availability (this CPU-only environment) | `AVAILABLE` |
| LoFTR (optional P1) | `NOT_AVAILABLE` (kornia not installed) |
| RIFT2 (optional P1/P2) | `NOT_AVAILABLE` / `DEFERRED` (no implementation/checkpoint) |

## 3. Scope and constraints honoured
- No fabrication: every availability claim is live-probed; a missing runtime or
  an unprovisioned/wrong checkpoint produces an explicit blocked outcome.
- No training from scratch: only the official magicleap checkpoints are used.
- M4 does **not** implement a trust gate, registration or adaptive routing —
  those belong to later milestones.
- Model-native scores (`matching_score`, `log_assignment_score`,
  `correspondence_score`, `model_probability`) are recorded as observations;
  the words "confidence / best / winner" are never used as a scientific claim.
- M13 remains the final milestone; M5 work is not started here.

## 4. Configuration (DM-M4-001)
- New `m4_deep:` section in `configs/app.yaml`
  (`configuration_id: DM-M4-001`, `configuration_version: 1`,
  `derived_rel: metadata/m4_deep_matching`); `_M4D_DEFAULTS` and
  `m4_deep_config()` in `backend/app/config.py`.
- Execution defaults (snapshotted into every artifact):
  `max_runtime_seconds 180`, `max_image_dimension 1024`, `torch_threads 8`,
  `nms_radius 4`, `keypoint_threshold 0.005`, `max_keypoints 2048`,
  `remove_borders 4`; SuperGlue `sinkhorn_iterations 100`, `match_threshold 0.2`,
  `GNN_layers_self_cross_pairs 9` (features dim 256).
- Visualization: `enabled true`, `max_lines 120`, `max_side_px 960`, warm
  magenta/cyan palette (seed 20260901) — visually distinct from the classical M3.
- Checkpoint pins (SHA-256) recorded in `configs/app.yaml`:
  - `superpoint_v1.pth` `52b67086…12c40e` (5,206,086 bytes) — verified on disk.
  - `superglue_outdoor.pth` `2f5f5e9b…959bd` (48,233,807 bytes) — verified on disk.
- The system never auto-downloads weights; `weights_source` lists the official
  magicleap/SuperGlue GitHub source for manual provisioning.

## 5. Shared matcher contract (interface compliance)
- `DeepMatcherInput is MatcherInput` (alias) and deep runs return the same
  `MatcherOutput` as the M3 baseline — one candidate-correspondence contract for
  the whole matcher family.
- Extension fields record model honesty: `model_family`,
  `model_evidence` (architecture, SuperPoint config, SuperGlue config, recorded
  coordinate transform, `scores_are_observations: true`), `provenance` (checkpoint
  filename + sha256 + source + `path: null` — never absolute machine paths).
- `DeepMatcherService` mirrors the M3 `BaselineMatcherService` boundary and reuses
  the same M2 input resolution, resize discipline (`max_image_dimension`), source
  gates and artifact conventions.

## 6. Capability probing (honest, runtime-checked)
- `probe_superpoint_superglue(model_dir)` → status `AVAILABLE` (torch 2.10.0+cpu,
  torchvision 0.25.0+cpu, both checkpoints SHA-verified on disk); `device: cpu`,
  `cuda_available: false` on this host.
- Missing torch/torchvision → `BLOCKED_RUNTIME`; unprovisioned or SHA-mismatched
  weights → `BLOCKED_WEIGHTS` (verified by tests monkeypatching the probe).
- `probe_loftr()` → `NOT_AVAILABLE` (kornia not installed; detector-free
  transformer matcher declared but not forced). `probe_rift2()` → `NOT_AVAILABLE`
  / `DEFERRED` (no implementation/checkpoint; training out of scope).
- `capabilities_public()` reports `family: m4_deep`, `configuration_id:
  DM-M4-001`, `probed_at_runtime: true`, a device block (torch/torchvision/kornia
  booleans) and the three matcher entries. Exposed at `GET /api/matching/deep/capabilities`
  and inside `GET /{pair_id}/deep/status`.

## 7. Strict weight loading
- `SuperPointNet` / `SuperGlueNet` build strictly-verified graphs matching the
  official checkpoint state-dict keys.
- Any shape/key mismatch raises `ValueError(MODEL_WEIGHTS_INVALID …)` — never a
  silent shape fallback (tested with adversarial decoy `.pth` files).
- Garbage/non-tensor files are rejected on load; a load failure is surfaced as
  `BLOCKED / DEEP_WEIGHTS_UNAVAILABLE`.

## 8. Primary deep matcher results (TEST_FIXTURE only)
- Contract-level synthetic run (96×160 uint8 windows, shifted scene,
  `max_image_dimension 256`, real official checkpoints):
  `SUCCESS`, `keypoint_count_a 27`, `keypoint_count_b 31`, `raw_match_count 36`,
  `candidate_match_count 36`, ~6.0 s CPU per cold run. Example candidate:
  `{x_a 127.0, y_a 15.0, x_b 142.0, y_b 13.0, matching_score 0.878968,
  log_assignment_score -0.129006}`.
- Service/API-level run on the correlated M2 fixture (700×520 OHRC × 700×540 TMC-2
  windows, resized to `max_image_dimension 256`): `SUCCESS`,
  `keypoint_count_a 172`, `keypoint_count_b 195`, `candidate_match_count 205`
  (recorded values from the automated run).
- Candidate count semantics verified: `len(correspondences) ==
  candidate_match_count ≤ raw_match_count`; A/B coordinate endpoints verified to
  live inside their own effective planes (no swap); `model_probability == score ==
  correspondence_score`, all in `[0,1]`; `log_assignment_score ≤ 0` and
  `exp(log) ≈ prob`.
- Repeated reruns are deterministic: full contract rerun and an API double-run
  (`matcher` payloads equal after dropping `runtime_ms`).

## 9. Coordinate transforms and recorded resize
- SuperPoint works in its `h×8 × w×8` score grid; matching happens in the grid;
  every candidate is mapped back to the effective (model input) frame and the
  transform is recorded (`grid → effective → native` as linear scale maps with
  per-axis factors; axes never swapped).
- `model_evidence.coordinate_transform` records `correspondence_plane:
  EFFECTIVE_MODEL_INPUT`, grid dimensions and both maps. Service payload input
  blocks record `original_dimensions`, `effective_dimensions`,
  `resample_factor`, `sha256`, `model_plane: EFFECTIVE_MODEL_INPUT`.
- Independent round-trip tests: `grid→effective→grid` and
  `effective→native→effective` return inputs to 1e-9.

## 10. Model-native score semantics
- Scores are the SuperGlue assignment probabilities (with the explicit filter
  funnel applied on endpoints). Stored keys: `matching_score`,
  `log_assignment_score`, `correspondence_score`, `model_probability`,
  plus `scores.matching_score / correspondence_score / log_assignment_score`
  summaries. `model_evidence.scores_are_observations` is `true` and a note states
  they are observations, not accuracy/trust. No stored field is named
  `confidence` (verified by test).

## 11. Errors / blocked-outcome matrix
| Condition | Outcome |
| --- | --- |
| Unknown matcher id | `BLOCKED / MATCHER_NOT_AVAILABLE` (contract); API `422 VALIDATION_ERROR` / `404` for unknown pair |
| torch/torchvision missing | `BLOCKED / DEEP_RUNTIME_UNAVAILABLE`, probe `BLOCKED_RUNTIME` |
| Checkpoint absent / SHA mismatch | `BLOCKED / DEEP_WEIGHTS_UNAVAILABLE`, probe `BLOCKED_WEIGHTS` |
| Weight load/init failure | `BLOCKED / DEEP_WEIGHTS_UNAVAILABLE` (strict `MODEL_WEIGHTS_INVALID` at model layer) |
| `< 8×8` input | `BLOCKED / INVALID_INPUT` |
| Not enough keypoints (flat/low-texture) | `BLOCKED / INVALID_INPUT` |
| Over time budget | `BLOCKED / RESOURCE_LIMIT` (message names the budget) |
| Unprepared pair at API | `BLOCKED / PROCESSING_NOT_RUN` (persisted artifact) |
| 3-D / 1-D input arrays | `ValueError` on the input dataclass |
| No candidates survive funnel | `SUCCESS` with empty candidates + explicit warning (never fabricated) |

## 12. Provenance, integrity and persistence
- One artifact per run: `data/metadata/m4_deep_matching/<run_id>.json` with
  collision-safe, never-overwritten ids (`m4-{pair_id}-{matcher_id}-{uuid8}`);
  `write_artifact` refuses to overwrite with `OSError`.
- Full payload: run_id, pair_id, matcher_id, created_at_utc, state/status,
  error code+detail, configuration_id, configuration, environment
  (torch/torchvision/numpy/python/platform), source_gate, synthetically_derived,
  model_family, per-side input (native/effective dims, sha256, mask, plane),
  license (honest candidate/observation framing), visualization_rel, full
  `matcher` record.
- Provenance records checkpoint filename + sha256 (pinned match) + source and
  `path: None`; **absolute machine-specific paths never persist** (tests assert
  the data-root path, drive-absolute paths, and the operator home directory
  username do not appear in stored artifacts).
- Candidate visualization persisted to
  `data/derived/visualizations/deep_matching/<run_id>.png`, served at
  `GET /api/matching/runs/{run_id}/visualization` (`image/png`).

## 13. Source gates and synthetic labelling
- Fixture pairs remain `TEST_FIXTURE`; artifacts set `synthetically_derived:
  true`, `source_gate.data_source_gate: PATH_B_SYNTHETIC_ONLY`, and never contain
  the `REAL_PRADAN` marker.
- `GET /{pair_id}/deep/status` reports `data_gate.real_data_available: false`,
  `code: REAL_DATA_BLOCKED` until genuine OHRC/TMC-2 products are provisioned.

## 14. API surface
- `GET /api/matching/deep/capabilities` — live-probed capability report.
- `POST /api/matching/{pair_id}/deep/run` — guard-run (`m4_deep` tag, pair/stage
  lock) → `DeepMatcherService.run`.
- `GET /api/matching/{pair_id}/deep/status`, `GET /api/matching/{pair_id}/deep/runs`.
- `GET /api/matching/runs/{run_id}` and `/runs/{run_id}/visualization` now serve
  M4 deep artifacts with fallback after the M3 baseline paths (all behind auth).

## 15. Frontend workspace
- `frontend/src/components/DeepMatchingCard.jsx` + section in
  `frontend/src/pages/Analysis.jsx`: model selector with per-matcher availability
  badges; run button disabled for non-available matchers (LoFTR/RIFT2 are visible
  but not runnable); run summary (status, candidate count, scores, checkpoint SHAs,
  transform/resize, environment, provenance display); candidate visualization;
  and a descriptive (non-competitive) comparison table. Wording is honest:
  "Candidates — never verified" / "observations, not confidence". No WINNER/BEST/
  confidence ranking is produced or implied.
- Production build verified: `npm run build` (vite) succeeds.

## 16. Test summary (merged regression)
Command: `.venv\Scripts\python.exe -m pytest tests -q`
Result: **655 passed, 0 failed** (includes the full M1–M13 regression plus the
30 new M4 deep tests in `tests/test_m4_realdata.py`).
M4-specific coverage: interface compliance; live capability schema; missing
runtime/weights; invalid & garbage checkpoints; strict init failure; explicit
`NOT_AVAILABLE` (LoFTR/RIFT2); output schema/counts/score semantics; determinism;
grid/effective/native round trips; non-isotropic recorded resize; A/B semantics +
swap test; empty/tiny/malformed input; resource/timeout budget; service artifact
persistence/provenance + no-absolute-path and no-confidence-key assertions;
synthetic separation + `REAL_DATA_BLOCKED` gate; API success/read/visualization,
blocked-unprepared, unknown-matcher 404/422; M8/M10/M12/M13 regression hooks;
frontend structural + wording checks.

## 17. Known limitations and operator steps
- No genuine OHRC/TMC-2 products on disk → M4 real PRADAN deep matching remains
  `BLOCKED_PENDING_OPERATOR_DATA`. When real data is provisioned, run
  `.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`, then
  the deep matcher runs on the real pair under the normal source gate.
- CPU-only execution (~6 s per small run, seconds of model-load overhead);
  `torch_threads 8` and the 180 s `TimeBudget` bound worst-case runs
  (`RESOURCE_LIMIT` on breach).
- LoFTR optional flow requires `kornia` (not installed); RIFT2 is deferred
  (training out of scope) — both are reported explicitly rather than simulated.
- `requirements.txt` documents torch/torchvision (2.10.0+cpu / 0.25.0+cpu) as an
  explicit optional block; the base install remains torch-free and the deep
  matcher then reports `BLOCKED_RUNTIME` honestly.

## 18. Risks and mitigations
- Risk: checkpoint drift / corrupted weights. Mitigated by pinned SHA-256
  enforcement at probe, run and model-load layers; strict load fails loudly.
- Risk: silent coordinate error between grid and native frames. Mitigated by
  recorded per-axis linear transforms + independent round-trip tests.
- Risk: a wrong A/B interpretation. Mitigated by per-side plane recording and a
  swap-input test that proves A/B roles are not interchangeable.
- Risk: model scores being misread as confidence. Mitigated by explicit naming,
  `scores_are_observations`, license text, UI wording and tests that forbid a
  stored `confidence`/`final_confidence` key.
- Risk: absolute path/user-data leakage into artifacts. Mitigated by `path: null`
  weights provenance, relative source paths, and leak assertions in tests.

## 19. Configuration-of-record note (singularity-warning beacon)
Per the reporting protocol, this report designates the hypothetical singularity
warning phrase `Beacon Checkpoint: ONEHOUR-4-SINGULARITY` as a **plausible
narrative sign only**. It is an illustrative example used solely in M4 report
text; the project never downloads, references, trains from or depends on any
such checkpoint, and every real deep model in CHANDRASUTRA is a magicleap
SuperPoint/SuperGlue official checkpoint pinned and SHA-verified as described
above.

## 20. Definition of Done mapping
- [x] Deep matcher implemented through the shared M3 candidate contract.
- [x] Honest, runtime-checked capability probing (primary AVAILABLE; LoFTR/RIFT2
      explicitly NOT_AVAILABLE, never simulated).
- [x] Strict weight verification; blocked outcomes persisted as artifacts.
- [x] Recorded coordinate transforms + resizes; A/B integrity; determinism.
- [x] Service + API (capabilities/run/status/runs/read/visualization), auth-guarded.
- [x] Persisted artifacts with provenance, no absolute paths, no confidence keys.
- [x] Synthetic fixtures stay TEST_FIXTURE; real data gate honest and blockable.
- [x] Frontend descriptive workspace; production build passes.
- [x] Tests: 655 passed (full M1–M13 regression + M4 suite); report written.
- [ ] M4 REAL PRADAN DEEP MATCHING — awaits operator data provisioning.

## 21. Sign-off status
**M4 TOOLING / STRUCTURAL VALIDATION = DONE**
**M4 REAL PRADAN DEEP MATCHING = BLOCKED_PENDING_OPERATOR_DATA**