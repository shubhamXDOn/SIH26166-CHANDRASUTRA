# M10 — Metrics & Benchmark / Ablation / Failure Analysis — Progress Report

**Milestone:** M10 metrics & benchmark — a descriptive, evidence-grounded
benchmark controller (Configuration ID **`MET-M10-001`**) that observes the
settled M3..M9 artefacts on disk and reports funnel evidence, a V1..V6 variant
matrix (fixed classical / alternate classical / deep / fully routed plus the
V5 trust-disabled and V6 spatial-disabled offline ablations), descriptive
aggregation (median-preferred with mean and p95), Vx−V1 deltas and the
FT-M10-001 failure taxonomy. The controller is a **reader**: it never
re-executes matcher/trust/spatial/registration logic, never mutates upstream
derived products, never emits `winner` / `best` / `superior` / `optimal` /
`accuracy` / `geolocation` / `confidence` vocabulary and never fabricates a
calibrated verdict while `reference_status: REFERENCE_UNAVAILABLE`.
**Report date:** 2026-09-23
**Execution status:** `CASE B (structural validation on synthetic fixtures)`
**M10 METRICS & BENCHMARK TOOLING = DONE** (34 M10 tests green; M1–M13
regression slices green — config/backend/security/M10/M6–M9/M11–M13 = 454
passing — and the frontend builds clean)
**M10 GENUINE REAL-DATA EXECUTION = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Add an M10-scale metrics & benchmark controller over the reliably-derived
M3..M9 layers: a read-only funnel over settled artifacts, a fixed variant
matrix (V1..V6) with honest availability gating and offline ablation
semantics, descriptive aggregation and delta tables with a strict no-claim
policy, an immutable append-only run registry, and the FT-M10-001 failure
taxonomy separating failed / abstain / blocked. Everything is engineering-only
(`scientifically_tuned: false`); no calibrated lunar thresholds exist.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M10 metrics config block + loader (`MET-M10-001`, distinct from `AU-M10-001`) | `DONE` |
| V1..V6 variant matrix (config + code) | `DONE` |
| Read-only funnel extraction over M3..M9 artifacts | `DONE` |
| Blocked / failed / abstain three-way policy | `DONE` |
| Immutable append-only benchmark registry | `DONE` |
| Descriptive aggregation + Vx−V1 deltas (no winner) | `DONE` |
| FT-M10-001 failure taxonomy classification | `DONE` |
| Forbidden-vocabulary enforcement at schema boundary | `DONE` |
| M10 metrics service facade + read APIs | `DONE` |
| Frontend benchmark card wired into Analysis page | `DONE` |
| M10 metrics test suite (34 tests) | `DONE` |
| M1–M9 / M11–M13 regression slices | `GREEN` |
| Genuine real-pair benchmark execution | `BLOCKED_PENDING_OPERATOR_DATA` |

## 3. Naming & file layout
```
configs/app.yaml                         m10_metrics: MET-M10-001 (+ V1..V6, funnel, aggregation, FT-M10-001)
backend/app/config.py                    m10_metrics_config() (lru_cached, section-only, distinct from m10_config/auth)
backend/app/metrics_m10/__init__.py      M10MetricsService export
backend/app/metrics_m10/config.py        (n/a — config lives in app/config.py; package keeps a thin facade)
backend/app/metrics_m10/states.py        run states + forbidden vocabulary
backend/app/metrics_m10/variants.py      V1..V6 variant matrix + config merge
backend/app/metrics_m10/taxonomy.py      FT-M10-001 failed/abstain classification
backend/app/metrics_m10/schema.py        MET-M10D-001 row schema + vocabulary guard
backend/app/metrics_m10/extraction.py    read-only funnel/evidence extraction
backend/app/metrics_m10/aggregation.py   median/mean/p90/p95/px, deltas
backend/app/metrics_m10/registry.py      immutable run registry (m10-<8hex>)
backend/app/metrics_m10/service.py       orchestration facade
backend/app/api/metrics_m10.py           /api/metrics-m10 router
backend/app/api/router.py                include_router(metrics_m10.router)
frontend/src/components/M10MetricsBenchmarkCard.jsx
tests/test_m10_metrics.py                34 passed
reports/M10_METRICS_BENCHMARK_PROGRESS.md
```

## 4. Configuration (`MET-M10-001`)
- Config id `m10_metrics_configuration_id: MET-M10-001` is a **distinct**
  section from the M10 authentication milestone (`m10_config` →
  `AU-M10-001`); the two never collide.
- `scientifically_tuned: false`; `metric_definition_version: MET-M10D-001`;
  `failure_taxonomy_version: FT-M10-001`; `reference_status: REFERENCE_UNAVAILABLE`.
- Variant records carry routing / trust_gate / spatial_selection so the
  matrix is configuration-driven, with code defaults as fallback.

## 5. Variant matrix (V1..V6)
| Variant | Routing | Trust | Spatial | Semantics |
| --- | --- | --- | --- | --- |
| V1 | FIXED_CLASSICAL | ENABLED | ENABLED | classical baseline (SIFT) |
| V2 | FIXED_ALTERNATE_CLASSICAL | ENABLED | ENABLED | availability-gated (NOT_AVAILABLE) |
| V3 | FIXED_DEEP | ENABLED | ENABLED | availability-gated (NOT_AVAILABLE) |
| V4 | ROUTED | ENABLED | ENABLED | full adaptive reliability chain |
| V5 | ROUTED | DISABLED_FOR_ABLATION | ENABLED | offline ablation |
| V6 | ROUTED | ENABLED | DISABLED_FOR_ABLATION | offline ablation |

V2/V3 report `BLOCKED` with an availability guard and `None` downstream values
when their family is not provisioned — never fabricated numbers. V5/V6 are
offline analyses described as NOT_RUN/BLOCKED by design at registration.

## 6. Configuration loader guarantees
`m10_metrics_config()` parses the `m10_metrics:` YAML section, merges over
documented defaults, tolerates list- or dict-shaped variant records, is
`lru_cache`d per process, and never raises on parse failures (falls back to
defaults). Verified by tests against both a live `configs/app.yaml` and the
fallback path.

## 7. Funnel stages & evidence model
Six stages: `input_gate → processing → matching → trust_gate →
spatial_selection → registration`. Each read returns `stage_observed` plus
numeric evidence (`candidate_count`, `verified_count`, `inlier_count`,
`selected_count`, `registered_count`, `registration_rmse_px`,
`registration_p95_px`). An absent artifact yields explicit `None` for that
stage — never a zero, so `0 candidates` (a real empty result) stays distinct
from `no run yet` (None).

## 8. Extraction is read-only
`extraction.read_funnel` calls only the existing read surfaces
(`find_run_for_pair`/`summary`, `latest_for_pair`, `read`). No matcher, trust,
spatial or registration `run()` is invoked and no derived product is written;
the benchmark persists only its own registry files under
`data/metadata/m10_metrics/benchmarks/`.

## 9. Three-way outcome policy (blocked / failed / abstain)
| State | Meaning | Recorded as outcome? |
| --- | --- | --- |
| BLOCKED | gate not passed (no artifact / availability / reference) | never |
| FAILED | attempted downstream work and could not complete | yes |
| ABSTAIN | insufficient settled evidence to attempt downstream | yes |

Tests verify: failed-registration → FAILED (never ABSTAIN); sparse → ABSTAIN
(never FAILED); no matching artifact → BLOCKED (never an outcome).

## 10. State normalisation from real upstream states
`_normalise` maps genuine M6..M9 statuses onto the M10 vocabulary:
`SUCCESS/SELECTED/ACCEPT → COMPLETE`, `TRANSFORM_FIT_ERROR/WARP_FAILED → FAILED`,
`ABSTAIN/SPARSE_EVIDENCE/INSUFFICIENT_* → ABSTAIN`, and `NOT_STARTED`
(a registered pair with nothing run) is treated as unobserved so no-artifact
pairs report BLOCKED rather than a bogus ABSTAIN.

## 11. Failure taxonomy (FT-M10-001)
Single root `REGISTRATION_FAILURE` with disjoint `failed` and `abstain`
branches. `classify()` returns a branch + code, never both; generic
`FAILED`/`ABSTAIN` states are classified explicitly so the registry and the
failure-analysis API stay consistent.

## 12. Schema & forbidden vocabulary
`schema.build_row` fixes the exported key set, stamps `state` and explicit
`None` for unobserved measurements, and raises `ForbiddenVocabularyError` if
`winner`/`best`/`superior`/`optimal`/`accuracy`/`success_rate`/`geolocation`/
`CE90`/`LE90`/`confidence` appear in `state` or notes.

## 13. Descriptive aggregation
`summarize` reports per-metric `n`, `min`, `max`, `mean`, `median`, `p90`,
`p95` over the *observed* sample only (never zero-filled), with comment
`median-preferred descriptive statistic; no accuracy claim`. `delta` computes
variants vs V1 and always states `no_claim: true` and
`reference_status: REFERENCE_UNAVAILABLE`.

## 14. Immutable registry
Run ids are `m10-<8-hex>`; `write` refuses existing ids (append-only) and
persists via temp-file + `os.replace`. Unsafe ids are rejected. A missing or
partial registry reads as `[]`/`None` without raising.

## 15. Service facade
`M10MetricsService` exposes `variant_matrix/variants/overview/prerequisites/
run/list/read/latest/analyze/deltas/failure_analysis`; `_default_services`
defensively imports M3..M9 services, treating any failure to import as an
unavailable stage.

## 16. API surface
| Endpoint | Method | Guard |
| --- | --- | --- |
| `/api/metrics-m10/overview` | GET | authenticated |
| `/api/metrics-m10/variants` | GET | authenticated |
| `/api/metrics-m10/pairs/{id}/prerequisites` | GET | authenticated |
| `/api/metrics-m10/runs` | POST | analyst |
| `/api/metrics-m10/runs` | GET | authenticated |
| `/api/metrics-m10/runs/{run_id}` | GET | authenticated |
| `/api/metrics-m10/pairs/{id}/latest` | GET | authenticated |
| `/api/metrics-m10/analyze` | GET | authenticated |
| `/api/metrics-m10/deltas` | GET | authenticated |
| `/api/metrics-m10/failure-analysis` | GET | authenticated |

Mounted under `api/router.py`; every response carries
`reference_status` + `no_claim`.

## 17. Frontend
`M10MetricsBenchmarkCard.jsx` renders reference status, the variant matrix,
an observational-run form (pair id + variant), the registry list, failure
taxonomy counts and a median/mean/p95 descriptive summary. Wired into
`Analysis.jsx` after M9. `npm run build` passes.

## 18. Test evidence
Run command: `python -m pytest tests/test_m10_metrics.py -q` → **34 passed**.
Live-HTTP smoke (`smoke_test.py` `record_m10m_backend`) adds **12 new
`m10m-*` probes** (login, overview, variant matrix, anonymous 401 reads and
mutations, prerequisites, no-artifact BLOCKED run, unknown-variant rejection,
no-winner vocabulary, analyze, deltas, failure-analysis) — **12/12 PASS** over
a real uvicorn socket with real auth; the remaining smoke failures are
pre-existing M8/M9/M11 environment-drift probes (deep-matcher weight surface,
Gemini provider now configured, readiness) untouched by this milestone.
Regression slices run green:
- `test_config.py test_backend.py test_security.py test_m10.py` → 55 passed
- `test_m6_routing.py test_m7_trust_gate.py test_m8_spatial.py
  test_m9_registration.py` → 212 passed
- `test_m11.py test_m12.py test_m13.py` → 153 passed
Consolidated M10 + regression = **454 passed**, 0 failed.

## 19. End-to-end validation
Live HTTP over an authenticated TestClient: all read endpoints 200; analyst
POST records a run; unknown variant → 422; unknown run → 404; and a pair with
no artifacts reports `state: BLOCKED` (never a fabricated outcome).

## 20. Honesty rules enforced
- The benchmark never re-runs or mutates M3..M9.
- No winner/best/superior/optimal/accuracy/geolocation/confidence output.
- `scientifically_tuned: false`; no calibrated lunar thresholds.
- Unobserved measurements are `None`, not zero.
- V5/V6 ablations are NOT_RUN by design and labelled as offline.
- `reference_status: REFERENCE_UNAVAILABLE` on every response.

## 21. Bug-hunt findings & fixes during this slice
- Colliding `m10_metrics:` spelling/magic strings vs `m10` (auth): resolved by
  distinct section + loader names (`MET-M10-001` vs `AU-M10-001`).
- Loader-format mismatch (list vs `{version, ids}` variant records): loader
  now tolerates both.
- Taxonomy losing generic `FAILED`/`ABSTAIN` states: classify() now handles
  them explicitly.
- Real upstream states (SUCCESS/SELECTED/ACCEPT/TRANSFORM_FIT_ERROR) not
  recognized: `_normalise` added and covered by tests.
- `NOT_STARTED` pair record misreported as ABSTAIN: now treated as unobserved
  → BLOCKED.
- Frontend icon reference that did not exist in `ui.jsx` (`Icon.Shield`):
  replaced with `Icon.Chart`.

## 22. Known limitations / not-yet-done
- V2/V3 (deep/alternate classical) are availability-gated and honestly report
  NOT_AVAILABLE until those families are provisioned.
- No real OHRC/TMC-2 PRADAN pair has been acquired, so no genuine
  benchmark row exists on disk; everything is synthetic-fixture validated.
- No runtime-with-weight visualizations beyond the card's summary numbers.

## 23. What would unlock real-data execution
Same gate as M1..M9: provisioning the first real, gate-passing
OHRC/TMC-2 PRADAN pair. Once a real M3..M9 artifact chain settles, the
existing controller produces registry rows, aggregation and failure taxonomy
with no code changes (`REFERENCE_UNAVAILABLE` remains until a calibrated
reference dataset is explicitly provided and `scientifically_tuned` is
flipped by an operator).

## 24. Conclusion
The M10 metrics & benchmark controller is implemented, wired, and verified
end-to-end (34 dedicated tests + 454-total regression). It observes the
settled M3..M9 artefacts only, never fabricates evidence, strictly separates
blocked/failed/abstain, enforces no-winner/no-accuracy vocabulary, and keeps
all claims descriptive (`MET-M10-001`, FT-M10-001,
`reference_status: REFERENCE_UNAVAILABLE`). Like M1..M9, genuine real-pair
benchmark execution remains honestly BLOCKED pending operator data.