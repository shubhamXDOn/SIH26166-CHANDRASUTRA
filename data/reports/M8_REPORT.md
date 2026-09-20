# M8 Report — Deep Matcher Benchmarking, Adaptive Expansion & Trustworthy Matcher Selection (CHANDRASUTRA · SIH26166)

**Milestone:** M8 — a deep-matcher expansion layer on top of the M2 → M7
evidence chain: honest runtime capability probing, categorical adaptive routing,
unified candidate correspondences from classical + (declared-unavailable) deep
matchers, a per-matcher benchmark table that never declares a winner, a
SHA-256 provenance manifest, a deterministic experiment identity, and reset
isolation from the M3/M4 read paths — all served under `/api/matching/.../m8`
and a new **Deep matcher expansion & benchmark** workspace in the Analysis UI.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-17
**Status:**
- **Engineering: DONE** — the full M8 benchmark/expansion pipeline is
  implemented, tested on the complete M2 → M7 → M8 path (14 dedicated tests in
  `tests/test_m8.py`, all milestone suites + bug-hunt corpora re-run green),
  deterministically exercised end-to-end (COMPLETE EXPAND run with ~6252
  candidates over the correlated synthetic fixtures, deterministic routing rows,
  categorical benchmark rows), and SSR-smoke-green in the frontend. `npm run
  build` passes, `ssr-smoke.mjs` renders all 13 modules including
  `M8Workspace`, `smoke_test.py` is **65/65 PASS** (9 new `m8-*` probes), and
  the full backend suite is green at **343 passed**.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as
  M1–M7. M8 truthfully reports `BLOCKED / REAL_DATA_UNAVAILABLE` for real
  pairs and `REFERENCE_DATASET = NOT_AVAILABLE` for every benchmark, rather
  than fabricating any deep-model output or accuracy number. Deep matchers
  (`superpoint_superglue`, `loftr`) are *declared* in this build but report
  `RUNTIME_UNAVAILABLE` / `MODEL_WEIGHTS_NOT_CONFIGURED` until their runtime
  and weights are provisioned. Synthetic fixtures exist only in automated
  tests.

> **Honesty rule:** M8 routing is a **what-to-try decision**, never a
> confidence/quality verdict; candidate sets are **matcher observations, never
> verified truth** (Trust Gate remains M4). Benchmark rows are measurement
> comparisons with **no `winner`, no `accuracy`, no `ce90`** anywhere, and
> `REFERENCE_DATASET = NOT_AVAILABLE` is recorded so no scientific benchmark
> claim is ever made. Deep confidence is never truth; an absent weight file
> or runtime is reported as a first-class capability status, never silently
> faked. FAILED, BLOCKED, INSUFFICIENT, TIMEOUT, MATCHER_UNAVAILABLE,
> MODEL_WEIGHTS_NOT_CONFIGURED and RUNTIME_UNAVAILABLE are all normal honest
> outcomes.

---

## 1. What M8 delivers

### 1.1 Configuration (`configs/app.yaml` → `m8:`, `backend/app/matching/m8/config.py`)

- `DM-M8-001` / v1 — the sole registered configuration, exposed by
  `GET /api/matching/capabilities` and referenced in `/api/meta` as
  `m8_config`. Pydantic-backed `DeepMatcherConfig` with string→number/boolean
  coercion and loud rejection of unknown configuration IDs (never a silent
  fallback).
- Classical strategies `[sift, orb]`, deep strategies
  `[superpoint_superglue, loftr]`, `preferred_matcher auto`,
  `allow_classical true`, `allow_deep true`, `fallback_to_classical true`.
- Candidates: `max_correspondences 4000`, `require_finite true`,
  `require_mask_valid true`.
- Runtime: `device auto`, `max_runtime_seconds 120`, `max_image_dimension
  2048`, `max_tile_area 400000`, `batch_size 1`.
- Benchmark: `enabled true`, **`reference_dataset: NOT_AVAILABLE`**.
- `scientifically_tuned false` with explicit engineering-defaults source
  strings on every surface (`source_reference`, manifest snapshot).

### 1.2 Honest capability probing (`capabilities.py`, `device.py`)

- A cached `registry` (rebuildable via `reset_registry()`) is built per
  `(model_dir, device)`; `capabilities_public()` returns a deterministic,
  ordered capability list (`sift`, `orb`, `superpoint_superglue`, `loftr`).
- Every entry records `matcher_id`, `family`, `available`, `device`,
  `requires_weights`, `weights_available`, `runtime_available`, `supports_cpu`,
  `supports_gpu`, `max_recommended_dimension` and a stable
  `reason_if_unavailable()` code — `RUNTIME_UNAVAILABLE` / `MODEL_WEIGHTS_NOT_CONFIGURED`
  / empty-when-ready.
- `device_public()` (in `/api/matching/capabilities`) reports CPU/CUDA
  availability and the `deep_runtime` dependency matrix
  (`torch`/`torchvision`/`kornia`) with the honest note that "availability is
  probe-checked at request time; deep matchers are only available when their
  weights are provisioned".

### 1.3 Unified correspondence contract (`contract.py`)

- `validate_and_normalize(...)` maps every matcher output to one
  `ValidatedCandidates` shape with an explicit funnel:
  `raw → nonfinite_rejected → bounds_rejected → mask_rejected →
  duplicates_rejected → max_correspondences → usable`, and a deterministic
  ordering (`np.lexsort` on descriptor distance; primary ordering index
  guarantees the path-level determinism the M3 engine already provides).
- Absent `matcher_confidence` **never** triggers non-finite rejection — the
  contract is robust to adapters that do not emit confidence.
- `write_candidates_artifact(...)` produces per-tile-per-matcher candidate
  JSON (`candidates/<tile>__<matcher>.json`) plus per-run `events/<tile>__<matcher>.json`
  recording runtime, funnel, outcome, and the
  "candidate correspondences are matcher observations" note.

### 1.4 Categorical adaptive routing (`routing.py`)

- `route_tile(...)` extends the M3 routing decision with M2 condition evidence
  (valid fraction, texture) and the honest capability probe. Outcomes are
  categorical constants — `FEATURE_SCARCITY`, `DEEP_MATCHER_AVAILABLE`,
  `PREFERRED_DEEP`, `CLASSICAL_ONLY`, `DEEP_ONLY`, `CLASSICAL_MANDATED`,
  `DEEP_MANDATED`, `CLASSICAL_ADAPTIVE`, `NO_ELIGIBLE_MATCHER` — never a
  numerical confidence/quality score.
- Every order records a deterministic `strategy_order`
  (primary-then-alternates, deduplicated), the requested mode, available
  classical/deep matchers, and the M3-proposed strategy used as the
  classical primary. The runtime layer records `fallback_used` /
  `fallback_reason` truthfully (`PRIMARY_UNAVAILABLE_OR_FAILED`).
- `DEEP_ONLY` mode appends the classical fallback to `strategy_order` whenever
  `fallback_to_classical=True` (e.g. `["superpoint_superglue","sift","orb"]`).

### 1.5 Adapters: classical + deep (`adapters.py`, `deep/`)

- `BaseMatcherAdapter` — uniform interface (`capability()`, `is_available()`,
  `prepare()`, `run()`, `normalize_result()`, `cleanup()`), `M8AdapterOutput`
  with explicit failure codes and a `runtime_name` used by the benchmark.
- Classical adapters wrap the existing M3 SIFT/ORB adapters and always report
  honest availability on CPU.
- Deep adapters (`superpoint.py`, `superglue.py`, `loftr.py`, `nms.py`) are
  fully implemented with real inference graphs, but build-time
  `RUNTIME_UNAVAILABLE` and `MODEL_WEIGHTS_NOT_CONFIGURED` are first-class
  conditions in this build (torch/torchvision/kornia absent from the venv,
  weights not provisioned). The runtime never fakes an unavailable deep
  matcher; it records the reason honestly.

### 1.6 Benchmark engine (`benchmark.py`)

- Benchmark mode runs **every eligible matcher per tile** (mode-filtered:
  `AUTO` → all available, `CLASSICAL_ONLY` → classical, `DEEP_ONLY` → deep)
  and emits a per-matcher `BenchmarkRow`:
  `tile_id`, `matcher_id`, `matcher_family`, `runtime`, `runtime_ms`,
  `candidate_count`, `finite_count`, `mask_valid_count`, `duplicate_count`,
  `usable_count`, `outcome`, and categorical downstream columns
  `m4_trusted` / `m5_supported` / `m6_registration_reachable` (default
  `NOT_RUN`).
- `REFERENCE_DATASET = NOT_AVAILABLE`; the payload's note is "Benchmark table
  is a measurement comparison — no winner, no accuracy claim." The forbidden
  tokens (`"winner"`, `"accuracy"`, `"ce90"`) are asserted *absent* from the
  generated JSON keys by the M8 tests, while the honest disclaimers keep the
  words in the prose.

### 1.7 EXPAND lifecycle (`service.py`, `states.py`)

- Public states: `NOT_STARTED → (BLOCKED) → RUNNING → COMPLETE` (+
  `INSUFFICIENT`, `FAILED`); benchmark mode labels record the active expansion
  ("Benchmark/expansion in progress"). Explicit block codes:
  `M3_NOT_AVAILABLE`, `M3_NOT_COMPLETE`, `NO_ELIGIBLE_MATCHER`,
  `DEEP_MATCHER_UNAVAILABLE`, `MODEL_WEIGHTS_NOT_CONFIGURED`,
  `MODEL_WEIGHTS_INVALID`, `RUNTIME_UNAVAILABLE`, `INPUT_INVALID`, `TIMEOUT`,
  `MATCHER_FAILED`, `NO_CANDIDATES`, `FORBIDDEN_TERMINOLOGY`, `MATCHING_FAILED`,
  `REAL_DATA_UNAVAILABLE`, `REFERENCE_DATASET_NOT_AVAILABLE`.
- M8 artifacts live **only** under
  `derived/matches/<pair>/<proc_cfg>/m8/<cfg>/` (`m8_status.json`,
  `routing/routing.json`, `candidates/candidates.json` + per-tile files,
  `summary.json`, `benchmark.json`, `m8_manifest.json`, `provenance.json`,
  `experiment.json`, `events/`). `MatchingService.find_run_for_pair` and the
  M4 `_match_run_dir` skip `m8` directories, so M3/M4 read paths can never
  consume M8 artifacts (asserted by a dedicated isolation test).
- `run()` re-verifies M2/M3 prerequisites via `build_match_tiles`, records
  capabilities + device into status, routes per tile, runs matchers under a
  per-tile runtime budget, aggregates `candidates.json` +
  `summary.json` (+ `benchmark.json` when requested), writes the manifest /
  provenance / experiment, and ends `COMPLETE` (candidates > 0) or
  `INSUFFICIENT` (zero surviving candidates).
- Normal (non-benchmark) expansion stops at the first candidate-bearing
  matcher; benchmark mode executes all eligible matchers and records every row.

### 1.8 Provenance + manifest + experiment (`provenance.py`, `manifest.py`, `experiment.py`)

- `build_m8_provenance(...)` chains the M2/M3 (and optional M8-adjacent) run
  directories into a provenance graph; `m8_manifest.json` records the M8
  configuration snapshot, matcher model identity, consumed M2/M3 artifacts and
  produced M8 artifacts as **relative paths + SHA-256 only** — never absolute
  or home-relative paths.
- `build_m8_experiment_json(...)` gives a deterministic experiment identity
  from the input-chain configuration IDs + config digest, mirroring the M7
  reproducibility contract ("Pair ID + M2..M8 Configuration IDs + matcher
  identity + input artifact hashes").

### 1.9 M8 API surface (under `/api/matching`)

| Endpoint | Purpose |
| --- | --- |
| `GET /capabilities` | honest capability list + device + `DM-M8-001` config + note |
| `POST /{pair_id}/m8/run` | run EXPAND (payload: `mode` AUTO/CLASSICAL_ONLY/DEEP_ONLY, `benchmark` bool) |
| `GET /{pair_id}/m8/status` | live run state, progress, blocked, capabilities, device, summary |
| `GET /{pair_id}/m8/runs` | M8 run directories (never picked up by M3/M4) |
| `POST /{pair_id}/m8/reset` | wipe only derived M8 artifacts (M3/M4 untouched) |
| `GET /{pair_id}/m8/routing` | categorical routing rows per tile |
| `GET /{pair_id}/m8/candidates` | unified candidate index + totals |
| `GET /{pair_id}/m8/tiles/{match_tile_id}/candidates` | per-tile, per-matcher candidate artifacts |
| `GET /{pair_id}/m8/benchmark` | per-matcher measurement table (`NOT_AVAILABLE` reference) |
| `GET /{pair_id}/m8/manifest` | SHA-256 manifest, relative paths only |
| `GET /{pair_id}/m8/provenance` | M2/M3 → M8 provenance chain |
| `GET /{pair_id}/m8/experiment` | deterministic experiment identity |
| `GET /{pair_id}/m8/summary` | EXPAND summary (outcomes, matchers used, downstream matrix) |

`/api/meta` exposes `m8_config` with `configuration_id: DM-M8-001`. All
endpoints 404 on unknown pairs via `PairRegistry` guard.

### 1.10 M8 frontend (Analysis workspace, downstream of Metrics)

- **M8Workspace.jsx** — mode select (AUTO / CLASSICAL_ONLY / DEEP_ONLY),
  benchmark toggle, Run EXPAND / Reset controls, live state badge + progress
  bar, stage trail (`Gates → Capabilities → Routing → Matchers → Candidates →
  Benchmark`), BLOCKED/FAILED message cards, the **Capability matrix**
  (per-matcher availability with runtime/weights ticks and the device /
  `deep_runtime` badge), the **routing table** (categorical per-tile
  strategy orders), a candidate **summary row** (totals, matchers used,
  outcomes, downstream categorical matrix), the **benchmark table** (rows with
  runtime, funnel counts and `NOT_RUN` downstream columns; "measurements — no
  winner/accuracy" badge), and Manifest / Provenance / Experiment JSON modals.
- **Analysis.jsx** — the module-plan entry **Deep matcher expansion (M8)** is
  `implemented: true` and an **M8 workspace** section renders next to the M3
  MatchingPanel when a pair is selected.
- **ssr-smoke.mjs** — renders `M8Workspace` (pair `CS-P001`) alongside all
  other panels.

---

## 2. Bug hunt + hardening (M8 suite)

`tests/test_m8.py` exercises the M8 hardening corpus (14 tests):

| # | Title | Key check |
|----|-------|-----------|
| 1 | Configuration registered | `DM-M8-001` inspectable at `/api/meta` + `capabilities.configurations` |
| 2 | Meta exposes M8 config | milestone `M8`, `m8_config.configuration_id == "DM-M8-001"`, `scientifically_tuned false` |
| 3 | Capabilities endpoint honest | `superpoint_superglue`/`loftr` report `available: false` + reason codes |
| 4 | Capabilities API deep-unavailable | `weights_available false` / `runtime_available false` via API, `REAL_DATA_UNAVAILABLE` honest |
| 5 | Contract rejects bad input | non-finite / out-of-bounds / mask-invalid / duplicate candidates all filtered, funnel recorded |
| 6 | Contract bounds + cap, no confidence needed | absent `matcher_confidence` never rejects; `max_correspondences` capped |
| 7 | Routing modes categorical | AUTO/CLASSICAL_ONLY/DEEP_ONLY produce deterministic categorical reasons; `DEEP_ONLY` appends classical fallback; `final_confidence` never present |
| 8 | Full EXPAND lifecycle (API) | COMPLETE run → candidates (~6252 over correlated fixtures), manifest/provenance/experiment, relative paths only, honesty disclaimers |
| 9 | M8 does not perturb M3/M4 read paths | M3/M4 artifacts never read M8 dirs; M8 reset leaves M3/M4 intact |
| 10 | Blocked for unprocessed pair | an unprepared pair → `BLOCKED` with M3 prerequisite code, nothing fabricated |
| 11 | Benchmark rows categorical | no `winner`/`accuracy`/`ce90` tokens in JSON keys, `NOT_RUN` downstream columns |
| 12 | CLASSICAL_ONLY skips deep | benchmark over classical-only mode never executes deep matchers |
| 13 | Reset scoped | reset removes only `derived/matches/.../m8/` + paired M8 copies |
| 14 | Honest unavailable recording | unavailable matchers produce explicit attempts rows (`UNAVAILABLE` + code), never silent skips |

All 14 pass. The M6/M7 bug-hunt corpora (B-series) and the M3 regression
hardening were also re-run green in the combined run below.

---

## 3. Regression

| Suite | Result |
|-------|--------|
| `pytest tests/test_m3.py tests/test_m6.py tests/test_m7.py tests/test_m8.py -q` | **168 passed** in ~244 s (incl. all M6/M7 bug-hunt cases + M8 suite) |
| `pytest tests/ -q` (full) | **343 passed**, 2 warnings (~11 min) |
| `smoke_test.py` (live HTTP: M1–M8 + frontend) | **65/65 PASS** (9 new `m8-*` probes: meta config, honest capabilities, device surface, m8 404s) |
| `npm run build` (frontend) | **built OK (vite 7.3.6, 43 modules)** |
| `node frontend/ssr-smoke.mjs` | **OVERALL PASS (13 SSR renders incl. M8Workspace)** |
| `docker compose config` | **valid** (backend`8000` + frontend`80`; full daemon build pending Docker availability) |

No M1–M7 regressions observed; matching/trust/registration/metrics suites
remain green after the M8 additions (`find_run_for_pair` skip, M8 routes,
restored M3 `GET /{pair_id}/status` route).

---

## 4. Known limitations

1. **Deep matchers are declared, not executed** — `superpoint_superglue` and
   `loftr` are fully implemented with real graphs but report
   `RUNTIME_UNAVAILABLE` / `MODEL_WEIGHTS_NOT_CONFIGURED` in this build
   (runtime deps absent; weights not provisioned). No deep inference ever
   runs, and none is faked.
2. **No reference dataset** — `REFERENCE_DATASET = NOT_AVAILABLE`; every
   benchmark is a measurement comparison with no winner and no accuracy/CE90
   claim. Routing is a what-to-try decision, not a confidence/quality verdict.
3. **Real-data execution** — BLOCKED on PRADAN approval. M8 truthfully reports
   `REAL_DATA_UNAVAILABLE` for real pairs; synthetic fixtures exercise the full
   EXPAND path only inside automated tests.
4. **Candidate confidence** — matcher confidence is never treated as trust; the
   Trust Gate (M4) remains the independent verification layer, and M8 exposes
   `downstream.m4_trust`/`m5_spatial_reliability`/`m6_registration` as
   categorical `NOT_RUN` columns until those runs exist.
5. **Containerisation** — `docker compose config` validates; a live
   `docker compose up` needs the Docker daemon (not running in this
   environment).

---

## 5. Traceability vs spec (SIH26166)

- **M8.1 Matcher capability registry** — `capabilities.py`, `device.py`,
  `adapters.py`, `deep/`; live probe every request; stable reason codes;
  deterministic ordered list for `/api/matching/capabilities`.
- **M8.2 Adaptive expansion routing** — `routing.py`; categorical,
  explainable, keep-what-to-try; mode-aware (`AUTO`/`CLASSICAL_ONLY`/
  `DEEP_ONLY`); records `strategy_order`, `fallback_used`, `fallback_reason`.
- **M8.3 Unified correspondence contract** — `contract.py`; explicit funnel,
  deterministic ordering, `matcher_confidence`-optional, JSON artifacts.
- **M8.4 Benchmark engine** — `benchmark.py`, `states.py`; per-matcher rows,
  categorical downstream columns, `NOT_AVAILABLE` reference, no
  winner/accuracy/CE90.
- **M8.5 Lifecycle, isolation, honest blocking** — `service.py`,
  `states.py`; `NOT_STARTED → BLOCKED → RUNNING → COMPLETE | INSUFFICIENT |
  FAILED`; M3/M4 read-path isolation; scoped reset; explicit block/failure codes.
- **M8.6 Provenance + determinism** — `provenance.py`, `manifest.py`,
  `experiment.py`; relative paths + SHA-256; deterministic experiment identity
  from config chain.
- **M8.7 API + UI** — `/api/matching` M8 router, `Analysis` M8 workspace +
  `M8Workspace`, Overview pipeline, SSR smoke, live-`smoke_test.py` probes.
- **M8.8 Honesty & safety** — no fabricated deep output, no winner/accuracy
  claims, `REFERENCE_DATASET = NOT_AVAILABLE`, unavailable-deep as first-class
  status, reset scoped, no path/token leaks, full suite green.