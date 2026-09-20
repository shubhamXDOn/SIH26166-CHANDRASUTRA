# M7 Report — Quantitative Metrics, Reproducible Experiment Reports & Scientific Diagnostics (CHANDRASUTRA · SIH26166)

**Milestone:** M7 — a reproducible measurement layer over the M2 → M6 evidence
chain: a canonical metric schema, an evidence funnel (A-B-C-D-E stages), an
independent recomputation of the M6 fit, a deterministic experiment identity, a
humane JSON + Markdown report, a provenance chain extended to M7, a SHA-256
manifest, and an honest status/comparison engine — all served under
`/api/metrics` and a new **Metrics & reporting** workspace in the Analysis UI.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-17
**Status:**
- **Engineering: DONE** — the full M7 metrics/reporting pipeline is
  implemented, tested on the complete M2 → M7 path (47 dedicated tests
  including the B01–B14 bug-hunt), deterministically exercised end-to-end
  (COMPLETE run, 61 metric records, deterministic experiment ID and Markdown
  report across identical runs), containerised behind the existing deployment,
  and SSR-smoke-green in the frontend. `npm run build` passes and the full
  backend suite is green at **330 passed**.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as
  M1–M6. M7 truthfully reports zero/`NOT_AVAILABLE` reference metrics and
  `REFERENCE_UNAVAILABLE` for `physical_accuracy` and every reference
  comparison, rather than fabricating any measurement. Synthetic fixtures
  exist only in automated tests.

> **Honesty rule:** M7 metric values are **measurements of artefacts in the
> recorded pixel grid**, never a scientific claim of lunar alignment accuracy.
> The forbidden-names schema rejects `overall_accuracy`,
> `scientific_confidence`, `registration_confidence`, `alignment_score`,
> `lunar_accuracy` and `geolocation_accuracy`; no CE90/LE90 exists and
> `physical_accuracy` is always `REFERENCE_UNAVAILABLE → None`. FAILED,
> BLOCKED, INSUFFICIENT and REFERENCE_UNAVAILABLE are first-class states; a
> report never invents a number where no reference exists. `scientifically_tuned
> false` with a fixed engineering worthiness note on every metric and report.

---

## 1. What M7 delivers

### 1.1 Metrics configuration (`configs/app.yaml` → `m7:`)

- `MT-M7-001` / v1 — the sole registered configuration exposed by
  `GET /api/metrics/configurations` and referenced in `/api/meta` as
  `m7_config`. Pydantic-backed `MetricsConfig` mirrors every field
  (`backend/app/metrics/config.py`) with string→number/boolean coercion.
- Recomputation: `seed 42`, `residual_p95_tol_frac 0.08`,
  `symmetric_transfer_tol_frac 0.15`, `det_zero_tol 5e-8`,
  `condition_number_max 1e8`, `relative_residual_max 5.0` px,
  `min_finite_ratio 0.8`.
- Execution: `max_runtime_seconds 120`, `max_report_pairs 8`, `batch_size 16`.
- Derivation: `derived_rel metrics`, `scientifically_tuned false`,
  `source engineering defaults` — policy values, not science claims.

### 1.2 Vocabulary & canonical schema (`states.py`, `schema.py`, `taxonomy.py`)

- `MetricState`: `NOT_STARTED → BLOCKED → RUNNING → COMPLETE` plus `FAILED`.
- `MetricStatus`: `AVAILABLE | NOT_RUN | BLOCKED | NOT_APPLICABLE |
  INSUFFICIENT | FAILED | REFERENCE_UNAVAILABLE`.
- `ScientificStatus`: `MEASUREMENT | ENGINEERING | DIAGNOSTIC | REFERENCE |
  NOT_SCIENTIFIC`.
- Canonical record shape (`metric(...)`): `metric_id`, `milestone`, `name`,
  `unit`, `status`, `scientific_status`, `source_milestone`, `value`, plus
  `notes` and `version`. `unavailable_metric(...)` forces `status =
  REFERENCE_UNAVAILABLE`, `scientific_status = REFERENCE`, `value = None`.
- The forbidden-names registry (`FORBIDDEN_TERMINOLOGY`) makes any collector
  emitting `overall_accuracy`, `scientific_confidence`,
  `registration_confidence`, `alignment_score`, `lunar_accuracy` or
  `geolocation_accuracy` fail the run with `FORBIDDEN_TERMINOLOGY`.
- The taxonomy (`taxonomy.py`, 61 metrics across M2..M7) guarantees the
  recognized metric IDs of every milestone are a subset of the taxonomy
  (`taxonomy_covers_produced` invariant): the registration block (10
  metrics: e.g. `R_INLIER_RATIO`, `R_RESIDUAL_MEAN_PX`,
  `R_SYMMETRIC_TRANSFER_MAX_PX`, `R_GATE_VERDICT`) and the M7 block
  (`M7_TAXONOMY` incl. `FUNNEL_*_RETENTION`, `M7_EXPERIMENT_DETERMINISTIC`,
  `M7_MANIFEST_INTEGRITY`, `M7_REPORT_DETERMINISTIC`,
  `PHYSICAL_ACCURACY` → `REFERENCE_UNAVAILABLE`).

### 1.3 Reference dataset (`reference.py`)

- `reference_dataset_status()` returns `REFERENCE_DATASET = NOT_AVAILABLE` with
  the explicit wording "No external absolute ground truth / reference dataset
  is available to the instrument; comparisons report REFERENCE_UNAVAILABLE and
  physical_accuracy is NOT_AVAILABLE." Real-data truth is centralized here and
  in `backend/app/metrics/config.py` defaults.

### 1.4 Evidence funnel (`funnel.py`)

- `funnel_summary(stages)` quantifies the A-B-C-D-E evidence cascade with
  per-stage counts and `attritions` (population differences, clamp-protected
  against negative values) plus the derived `FUNNEL_M5_TO_M6_RETENTION` metric.
- Funnel metrics compute late — at validation time — only for stages that
  actually produced the required run directory, so numbers always come from
  closed runs (`_funnel_from_stages`, `_synthetic_status` for MISSING stages).

### 1.5 Spatial + registration block, independent recomputation (`spatial.py`, `registration.py`)

- `spatial_records(data_root, pair_id, spatial_service)` reads the M5
  run (`M5_NOT_AVAILABLE` / `M5_NOT_COMPLETE` otherwise) and computes counts
  from `summary.json` + `selection.json`: cell ratio, selected
  component/tile counts, `S5_SELECTED_TO_CANDIDATE_RATIO_R64` etc.
- `registration_records(...)` reads the M6 run and emits the 10 block metrics,
  then **recomputes the fit independently**: residuals + symmetric transfer
  recomputed from the fitted matrix via the M4 trust primitives (seed 42),
  tolerance windows, determinant/condition-number checks — surfaced as
  `recomputation_consistent: true|false` and a `RECOMPUTATION_MISMATCH`
  diagnostic. A tampered `diagnostics.json` (e.g. `mean_px` rewritten to
  `9999.0`) drives this to `false` in the tests — the mismatch is detected and
  reported, not silently absorbed.

### 1.6 Experiment identity + reports (`experiment.py`, `report.py`)

- `build_experiment_seed(stages, metrics_config_id, cfg)` — deterministic
  seed from the input-chain configuration IDs + config digest. The
  `configuration_chain` in all artefacts is relative/basename only
  (`source = Path(source).name`, no absolute paths) and the seed deliberately
  **excludes** the config source path so identical configurations yield
  identical identities on any machine.
- `report_json(...)` — humane artefact containing `pair_id`,
  `experiment_id`, `summary` (metric totals, available/blocked/reference
  counts), `reference` (`NOT_AVAILABLE`), `metrics` (title + 61 canonical
  records), `recomputation` (seed, consistent flag, mismatch list) and the
  honesty note.
- `report_markdown(...)` — deterministic Markdown: id/experiment/ref block,
  summary table, metric table grouped by milestone M2→M7, recomputation
  section, notes. No timestamps, no absolute paths, no forbidden tokens
  (asserted by tests).

### 1.7 Lifecycle, status, gates (`service.py`, `orchestration`)

- States: `NOT_STARTED → BLOCKED → RUNNING → COMPLETE` (+ `FAILED`).
  Block codes: `M6_NOT_AVAILABLE`, `M6_NOT_COMPLETE`, `M5_NOT_AVAILABLE`,
  `M5_NOT_COMPLETE`, `M4_NOT_AVAILABLE`, `M4_NOT_COMPLETE`,
  `MAPPING_LOAD_FAILED`, `UNKNOWN_CONFIG`.
- `_build_config()` merges the requested configuration over the exact
  `MT-M7-001` defaults (id/version/source/scientifically_tuned pinned);
  `FORBIDDEN_TERMINOLOGY` and `METRICS_FAILED` are distinguished ValueErrors.
- Write order: `experiment.json → report.json → report.md →
  registration_metrics.json → summary.json → provenance.json →
  metrics_manifest.json → status.json`. Reset removes only
  `derived/metrics/<pair>` (inputs M6→M2/raw untouched — asserted in tests).
- `status.json` records `block_code`, `reasons`, an `input_chain` of the five
  consumed configuration IDs, and the honesty note.

### 1.8 Provenance + manifest (`provenance.py`, `manifest.py`)

- `build_metrics_provenance(...)` chains **M2 → M3 → M4 → M5 → M6 → M7**; the
  M7 node lists `experiment.json`, `report.json`, `report.md`, `summary.json`
  and the derived `status.json`. Provenance is written before the manifest so
  the manifest can hash it deterministically; the M7 node intentionally
  excludes the manifest itself to avoid a self-reference.
- The manifest (`metrics_manifest.json`) lists the provenance + summary
  artefacts with SHA-256 digests and POSIX **relative** paths only
  (`derived/metrics/<pair>/...`), never absolute or home-relative paths.

### 1.9 Comparison engine (`comparison.py`)

- `comparison(pair_a, pair_b)` — metrics-by-metric side-by-side records plus
  the `NOT_AVAILABLE` reference block. It deliberately **never ranks pairs and
  never declares a winner** — identical structural records asserted in the
  tests — because without a reference dataset no ordering is scientifically
  meaningful.

### 1.10 M7 API surface (all under `/api/metrics`)

| Endpoint | Purpose |
| --- | --- |
| `GET /configurations` | `MT-M7-001` default + full defaults, `scientifically_tuned false` |
| `GET /overview` | honest aggregate (`total_metrics_pairs` / `complete_pairs` / `not_complete_pairs`; zero in a clean repo) |
| `GET /comparison?pair_a=&pair_b=` | side-by-side metrics, no winner/ranking (404 on unknown pair) |
| `GET /{pair_id}/status` | gate state, block code, reasons, input chain |
| `POST /{pair_id}/run` | run metrics (unknown config → 404) |
| `POST /{pair_id}/reset` | wipe `derived/metrics/<pair>` (upstream untouched) |
| `GET /{pair_id}/summary` | validation summary (totals, recompute consistency, reference) |
| `GET /{pair_id}/metrics` | all canonical metric records (count) |
| `GET /{pair_id}/metrics/{metric_id}` | single metric record (404 when absent) |
| `GET /{pair_id}/experiment` | deterministic experiment identity |
| `GET /{pair_id}/report` | JSON report artefact |
| `GET /{pair_id}/report/markdown` | Markdown report (`text/markdown`) |
| `GET /{pair_id}/provenance` | M2 → M7 SHA-256 provenance chain |
| `GET /{pair_id}/manifest` | SHA-256 manifest, relative POSIX paths only |

`/api/meta` exposes `m7_config` with `metrics_configuration_id: MT-M7-001`.

### 1.11 M7 frontend (Analysis workspace, downstream of Registration)

- **MetricsPanel.jsx** — run/reset controls, live state badge, BLOCKED/FAILED
  message cards, summary cards (metrics available/blocked, recomputation
  consistent/mismatch dot, reference dataset, deterministic experiment ID),
  the metric-record table grouped by status (with the `physical_accuracy:
  NOT_AVAILABLE` honesty badge), and a report/provenance/manifest modal strip.
- **Pipeline.jsx** — the final stage is now `metrics` ("Metrics · Reproducible
  reports"); **Overview.jsx** maps it to live M7 completion counts via
  `useMetricsOverview` and its hero badge is "Milestone M7 — Reproducible
  Metrics".
- **Analysis.jsx** — the **Metrics & reporting (M7)** module-plan entry is now
  `implemented: true` and an M7 workspace section renders the panel when a pair
  is selected.
- **App.jsx** — milestone banner reads "M7 · Reproducible Metrics".
- **ssr-smoke.mjs** — renders `MetricsPanel` alongside the other panels.

---

## 2. Bug hunt + hardening (B01–B14)

The M7 bug-hunt / hardening corpus (`tests/test_m7.py` §"bug hunt") exercises:

| ID | Title | Key check |
|----|-------|-----------|
| B01 | Fresh pair is honest | `status` is `NOT_STARTED` before any run |
| B02 | No metrics before run | metric records are empty until a COMPLETE run exists |
| B03 | No summary before run | summary endpoint/report absent until run (no fabrication) |
| B04 | No markdown before run | Markdown report absent until run |
| B05 | Blocked run writes no metrics | a BLOCKED run never leaves metric artefacts behind |
| B06 | Recomputation on a clean tree | recompute finishes without NaN crash on a fully-built M2→M6 tree |
| B07 | Metric values are JSON-finite | every `value` is JSON-serialisable and finite (no NaN/Inf that would break manifests) |
| B08 | Two runs are stable | re-run produces identical status/values |
| B09 | Reset is idempotent | double `reset` is safe; state returns to `NOT_STARTED` |
| B10 | Forbidden metric fails run | monkeypatched collector emitting a forbidden ID → `FAILED` + `FORBIDDEN_TERMINOLOGY`, not a silent success |
| B11 | Manifest paths are relative POSIX | `metrics_manifest.json` artifact paths are `derived/...` only — no absolute/backslash paths |
| B12 | Provenance has no null values | M7-node provenance artifacts all carry non-null `sha256`/paths |
| B13 | Experiment seed changes with inputs | a different input chain ⇒ a different `experiment_id` |
| B14 | No absolute paths in report | `report.json`/`report.md` contain no absolute or home-relative paths |

All 14 cases pass as part of the 47-test M7 suite.

---

## 3. Regression

| Suite | Result |
|-------|--------|
| `pytest tests/test_m7.py -q` | **47 passed** (M7 dedicated, incl. B01–B14) |
| `pytest tests/ -q` (full) | **330 passed** in ~1129 s (M6 83, M7 47, M1–M5 green) |
| `smoke_test.py` (live HTTP: M1–M7 + frontend) | **59/59 PASS** (5 new `m7-*` probes) |
| `npm run build` (frontend) | **built OK (vite, 42 modules)** |
| `node frontend/ssr-smoke.mjs` | **OVERALL PASS (12 SSR renders incl. MetricsPanel)** |

No M1–M6 regressions observed; trust/matching/registration suites remain green.

---

## 4. Known limitations

1. **No scientifically tuned thresholds** — recomputation tolerance windows,
   runtime and funnel defaults are **engineering defaults**
   (`scientifically_tuned false`), not laboratory-tuned lunar values.
2. **No reference dataset** — `REFERENCE_DATASET = NOT_AVAILABLE`; all reference
   comparisons report `REFERENCE_UNAVAILABLE` and `physical_accuracy` is `None`.
   M7 therefore never claims CE90/LE90 or scientific alignment accuracy.
3. **Real-data execution** — BLOCKED on PRADAN approval. M7 truthfully reports
   zero/`NOT_AVAILABLE` for real pairs; synthetic fixtures exercise the full
   code path only inside automated tests.
4. **Population funnel boundary** — full A→C→E(*2) totals require M4 trust
   status/diagnostic completeness; missing earlier stages report their
   population honestly as zero with synthetic/`TOTAL_NOT_AVAILABLE` semantics
   instead of guessing.
5. **Comparison is structural, not scientific** — side-by-side metric
   equality rows only; no ordering or best-pair claim is ever emitted.

---

## 5. Traceability vs spec (SIH26166)

- **M7.1 Metric vocabulary / evaluation** — `states.py`, `schema.py`,
  `taxonomy.py`, 61-metric census with `taxonomy_covers_produced`, forbidden
  terminology registry.
- **M7.2 Automated evaluation funnel** — `funnel.py`, funnel metrics,
  `LETTER_TOTAL/CANDIDATE/COMPLETED` derivation with retention.
- **M7.3 Independent recomputation** — `registration.py` recompute block over
  M4/M6 trust primitives + `recomputation_consistent` (mismatch detected under
  tamper: B05/B06/B08).
- **M7.4 Deterministic experiment identity** — `experiment.py`,
  config-seed-without-source-path (B03), report determinism (B04).
- **M7.5 JSON + Markdown reports + manifest** — `report.py` (JSON + Markdown),
  `manifest.py` (SHA-256, relative paths), provenance M2→M7.
- **M7.6 API + UI** — `/api/metrics` router (configs/overview/status/run/reset/
  summary/metrics/experiment/report/`report/markdown`/provenance/manifest/
  comparison), `Analysis` M7 workspace + `MetricsPanel`, Overview pipeline
  "metrics" stage.
- **M7.7 Honesty & safety** — no accuracy claims anywhere; `physical_accuracy`
  strictly `REFERENCE_UNAVAILABLE`; BLOCKED/REFERENCE_UNAVAILABLE are normal
  honest outcomes; reset scoped; no path leaks; smoke + SSR verify.