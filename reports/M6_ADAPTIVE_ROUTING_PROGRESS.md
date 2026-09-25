# M6 — Adaptive Matcher Router — Progress Report

**Milestone:** M6 — a deterministic, evidence-based MATCHER ROUTING layer that consumes
M2 processing readiness + the M5 condition profile and M8 capability probes, and produces
a routing **decision** (what to try), with explicit capability gating (`first-available`
primary/fallback), a fixed-baseline ablation arm, and honest `BLOCKED/ABSTAIN` outcomes.
Routing is NEVER a matcher selection verdict and NEVER an accuracy/confidence claim.
**Report date:** 2026-09-23
**Execution status:** `CASE B (structural validation on correlated fixtures)`
**M6 TOOLING / STRUCTURAL VALIDATION = DONE** (27 M6 routing tests + full M1–M13
regression green; no lint tooling exists in the repo)
**M6 GENUINE REAL-DATA ROUTING = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Add a router between M5 (condition estimation) and M3/M8 (matcher execution) that turns
validated inputs into one auditable, reproducible routing run. Every run records: the
configuration snapshot, the mode (`ADAPTIVE` / `FIXED_BASELINE`), strict input gates,
the full condition snapshot, the resolved capability snapshot, the matched rule (with its
priority, description and per-predicate results), the capability-resolved
`primary_matcher` / `fallback_matcher`, a decision hash over all of these, and a
`route_explanation`. Identity is by `matched_rule_id` + matcher route; evidence and policy
are recorded, never simulated. The layer routes through the SAME candidate observation
contract — results remain correspondences, not verified alignment.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M6 configuration + config loader (`AR-M6-001`) | `DONE` |
| `backend/app/routing` package (contract/config/views/predicates/engine/service) | `DONE` |
| M6 API routers (capabilities/status/runs/run/execute/detail) | `DONE` |
| Frontend `AdaptiveRoutingCard.jsx` wired into `Analysis.jsx` | `DONE` |
| Structural validation (27 M6 routing tests + M1–M13 regression, 723 tests green) | `DONE` |
| Genuine real-data routing | `BLOCKED_PENDING_OPERATOR_DATA` |
| Configuration of record | `AR-M6-001` (version 1, `scientifically_tuned: false`) |

## 3. Honesty rules honoured
- **Determinism:** routing is pure policy over recorded evidence; identical input +
  configuration produce an identical 64-hex `decision_hash` (verified run-to-run).
- **No fabrication:** missing gates are persisted `BLOCKED` artifacts with stable codes
  (`PROCESSING_NOT_RUN`, `CONDITION_NOT_AVAILABLE`), never simulated success. When no rule
  matches, the outcome is `ABSTAIN` — nothing is guessed.
- **Capability honesty:** `primary_matcher`/`fallback_matcher` are resolved to the FIRST
  AVAILABLE matcher in each rule's `match` list using live capability probes (classical =
  SIFT/AKAZE/ORB contract; deep = SuperPoint+SuperGlue only when torch runtimes and SHA-verified
  weights are provisioned). Nothing is declared available that is not.
- **Never a selection/confidence verdict:** artifact payloads are scan-rejected
  (case-insensitive) for `selected_matcher / recommended_matcher / best_matcher /
  routing_decision / confidence`.
- **Fallback is predeclared:** routers define `fallback` matchers; execution may trigger
  fallback only on declared bases (`PRIMARY_MATCHER_UNAVAILABLE`, `FAILED_RUN`,
  `EMPTY_CANDIDATE_OUTPUT`), at most once, with the reason recorded — never silent.
- **Ablation honesty:** `FIXED_BASELINE` mode routes to `R-FX-001` (sift primary, orb
  fallback) and ignores the condition profile — the registered A/B ablation arm.
- **Fixity:** artifacts are written once and never overwritten (`write_artifact` raises
  if the file already exists); all product references are relative, no absolute machine
  paths.

## 4. Configuration (AR-M6-001)
New `m6_routing:` section in `configs/app.yaml` (id AR-M6-001, version 1,
`derived_rel: metadata/m6_routing`); `_M6R_DEFAULTS` + `m6_routing_config()` in
`backend/app/config.py` (cached, YAML fallback, deep-merge). Rules are evaluated first
match by descending `priority`, each with explicit `error_code`, `match` operator
semantics (top-level `all`/`any`) and matcher lists:

| Priority | Rule | Mode | Semantics | Route |
| --- | --- | --- | --- | --- |
| 100 | `R-PRE-A` | both | block when not `processing_ready` | — |
| 90 | `R-PRE-B` | ADAPTIVE | block when no condition profile | — |
| 70 | `R-FX-001` | FIXED_BASELINE | empty `when` | sift → orb |
| 50 | `R-DEEP-001` | ADAPTIVE | any of texture_high / appearance_high / gsd_ratio_large | superpoint_superglue → sift |
| 40 | `R-CLASS-001` | ADAPTIVE | all of texture_low / appearance_low / NOT gsd_ratio_large | sift → orb |
| 10 | `R-DFT-001` | ADAPTIVE | default | sift → orb |

Policy thresholds (registered, never claimed scientific): appearance
`difference_low_lt 0.25` / `difference_high_ge 0.55`; scale `gsd_ratio_medium_ge 1.35` /
`gsd_ratio_large_ge 2.0`. `scientifically_tuned: false`.

## 5. Decision vocabulary (read-only contract)
Decision dict fields: `state` (`ROUTED/BLOCKED/ABSTAIN`), `decision_status`,
`matched_rule_id`, `rule_priority`, `requested_primary_matcher`,
`requested_fallback_matcher`, `primary_matcher`, `fallback_matcher`, `fallback_used`,
`fallback_reason`, `error_code`, `error_detail`, `route_explanation`,
`predicate_results`, `matched_rule`, `decision_hash`, `capabilities`. The vocabulary
guard in `contract.assert_artifact_vocabulary_safe` rejects the forbidden field names
anywhere in the artifact and requires `decision` (with nested `matched_rule`) to be
present — enforced by test on both real and leaked shapes.

## 6. Classification view (evidence extracted from M5)
`extract_condition_view` reads the M5 artifact (summary → run id → full payload):
`a.textural_complexity`, `b.textural_complexity`,
`pair.appearance_difference` (`histogram_distance_chi_square`),
`pair.gsd_ratio` (`gsd_ratio_relationship`),
`pair.absolute_pixel_ratio` (`native_scale_gap`), and the derived booleans
`pair.texture_complexity_high/low`, `pair.appearance_difference_low/high`,
`pair.gsd_ratio_medium/large`, `pair.worst_invalid_fraction`. All compared against the
`when` predicates in any-of / all-of semantics; every evaluated predicate result is
recorded for audit.

## 7. Capability gating
`capabilities_public()` reports `configuration_id`, the classical matchers
(SIFT/AKAZE/ORB availability from the baseline contract) and deep matchers
(SuperPoint+SuperGlue availability from the M8 runtime probe). The capability snapshot is
folded into the decision hash, so a toggled capability (e.g. deep weight availability)
correctly invalidates a previous route (verified by test).

## 8. Execution dispatch
`POST /api/pairs/{pair_id}/routing/execute {run_id}` resolves the routed run, dispatches
the primary through the artifact-matched service (`BaselineMatcherService` / M8 deep
runner), and records per-matcher `status`, `candidate_match_count`, keypoint counts,
`runtime_ms` and `run_id`. On a declared trigger the predeclared fallback is attempted at
most once; the artifact is atomically updated in place (status `EXECUTION_STARTED`) with
`executed_routes`, `final_route`, `fallback_used` and `fallback_reason`.

## 9. API surface (all auth-guarded)
- `GET /api/matching/routing/capabilities` — AR-M6-001 + classical/deep capability map.
- `GET /api/pairs/{pair_id}/routing/status` — latest run + condition/processing refs.
- `GET /api/pairs/{pair_id}/routing/runs` — list of routing runs (newest first).
- `POST /api/pairs/{pair_id}/routing/run` — `mode`, optional `configuration_id` /
  `rules_override`; writes one artifact via `guard_run` (derived_stage `routing`).
- `POST /api/pairs/{pair_id}/routing/execute` — `run_id`; optional dispatch.
- `GET /api/routing/runs/{run_id}` — full artifact read (404 for unknown).

## 10. Persistence & provenance
One artifact per run under `data/metadata/m6_routing/<run_id>.json` (ids
`r6-<pair>-<8hex>`), never overwritten. Each run records `experiment_id`
(`EXP-M6-<MODE>-AR-M6-001`), provenance chain `raw -> M2 -> M5 -> M6`, M2/M5/M6
configuration ids, environment snapshot and the `disposition_note` spelling out that the
decision is a what-to-try action, not a verdict.

## 11. Blocked-outcome matrix
| Condition | Outcome |
| --- | --- |
| Processing not run / not ready | `BLOCKED / PROCESSING_NOT_RUN` (R-PRE-A) |
| ADAPTIVE without condition profile | `BLOCKED / CONDITION_NOT_AVAILABLE` (R-PRE-B) |
| No rule matches (ADAPTIVE) | `ABSTAIN` (persisted disposition) |
| Capability missing at execution | fallback attempt, `PRIMARY_MATCHER_UNAVAILABLE` |
| Execution failure / empty output | fallback attempt, `FAILED_RUN` / `EMPTY_CANDIDATE_OUTPUT` |
| Unknown run id | `404` |

## 12. Frontend
`frontend/src/components/AdaptiveRoutingCard.jsx` wired into `Analysis.jsx` as the
"Adaptive matcher router · M6" workspace: mode selector (ADAPTIVE / FIXED_BASELINE),
Run routing, Execute routed matcher, capability badges, decision summary (state, rule +
priority, primary → fallback, fallback-used reason, final route, decision hash), evidence
inputs, execution dispatch table and run list. Honest wording throughout; `npm run build`
passes (51 modules).

## 13. Test summary
`tests/test_m6_routing.py` — **27 passed**. Coverage: config load + validation (loud on
bad rule/operator/matcher/mode/error-code); rule evaluation logic;
`PROCESSING_NOT_RUN` / `CONDITION_NOT_AVAILABLE` blocking; deterministic hashing
(same input ⇒ same hash; capability change ⇒ different hash); condition-to-route mapping
(high texture/appearance/gsd ⇒ deep+classical; easy pair ⇒ classical; FIXED_BASELINE ⇒
R-FX-001); capability fallback resolution; abstain; view extraction (known fields +
derived booleans); vocabulary guard (real artifact shape + forbidden leaks); artifact
persistence + no-overwrite; end-to-end run/execute over correlated fixtures (baseline
match runs, candidate counts, fallback reason); status/runs/read endpoints; auth 401;
unknown pair 404.

Regression (batched `.venv\Scripts\python.exe -m pytest`, all green):
config/dirs/backend/security/M6-routing/M5-condition 96; M1+M2+M3+M7+M8+M9 199;
M4+M5+M6 184; M10+M11+M12+M13 150; real-data orchestration (M1–M4) 94 → **723 passed,
0 failed**. No lint tooling is configured in the repository.

## 14. Known limitation / operator step
Genuine OHRC/TMC-2 adaptive routing remains `BLOCKED_PENDING_OPERATOR_DATA` — routing
consumes the M5 condition profile, which is itself gated on real products. Once real
`.img`+`.xml` products are provisioned, run
`.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`; M5 then runs on
the real pair and M6 routing follows under the normal source gate.

## 15. Definition of Done mapping
- [x] M6 routing package/service/API/frontend (AR-M6-001).
- [x] Deterministic policy; decision-hash determinism verified (incl. capability change).
- [x] Explicit capability gating; primary/fallback resolved to first available.
- [x] Fixed-baseline ablation arm (`R-FX-001`, condition-free).
- [x] Predeclared fallback with recorded reason; no silent failures.
- [x] Forbidden vocabulary scan-enforced on artifacts.
- [x] Persisted artifacts, no overwrite, no absolute paths.
- [x] Execution dispatch through the existing matcher contracts.
- [x] 27 M6 tests + full required regression green (723 tests); report written.
- [ ] Real-data routing — awaits operator data provisioning.

## 16. Sign-off status
**M6 TOOLING / STRUCTURAL VALIDATION = DONE**
**M6 GENUINE REAL-DATA ROUTING = BLOCKED_PENDING_OPERATOR_DATA**