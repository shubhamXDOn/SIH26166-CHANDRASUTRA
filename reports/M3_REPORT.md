# M3 Report — Adaptive Matcher Strategy Selection & Candidate Correspondences (CHANDRASUTRA · SIH26166)

**Milestone:** M3 — matcher adapters over preprocessed tiles, condition-aware
strategy selection, explicit and recorded candidate filtering, candidate
correspondences as observations, and a factual UI workspace for the matching
stage.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-16
**Status:**
- **Engineering: DONE** — the full M3 MATCH pipeline is implemented, tested
  (99 backend tests passed), smoke-tested end to end over live HTTP
  (39/39 checks), exercised on correlated synthetic fixtures (6 usable match
  tiles → 872 candidate correspondences), and wired into a functional
  Matching workspace in the Analysis UI.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as M1/M2.
  M3 truthfully reports **BLOCKED** via `/api/matching/overview` and per-pair
  status rather than simulating a run. Synthetic fixtures exist only in
  automated tests and a controlled TEMP e2e script — never as benchmark pairs.

> **Honesty rule:** M3 produces **observations, not verdicts**. Every candidate
> is a keypoint correspondence localised by the chosen matcher; routing scores
> are *what-to-try* weights derived from measured scene conditions, never an
> accuracy/trust signal; the independent Trust Gate is explicitly **NOT_RUN
> (M4)**. No artifact contains `final_confidence`, an accuracy figure, or any
> fabricated metric. `BLOCKED`, `TIMEOUT` and `INSUFFICIENT_CANDIDATES` are
> first-class outcomes.

---

## 1. What M3 delivers

### 1.1 Matcher configuration (`configs/app.yaml` → `m3:`)

- `MC-M3-001` / v1 — the runnable configuration exposed by
  `GET /api/matching/configurations` (default configuration).
- Candidate filters: `minimum_candidates: 8`, `border_margin_px: 4`.
- Execution: `max_features: 4000`, `max_tile_area_px: 400000`,
  `max_runtime_seconds: 45`, fallback enabled (max 2 attempts).
- Per-strategy matching ceilings (acceptance refs): sift `ratio 0.8` /
  `max_distance 350` (L2); orb `ratio 0.85` / `max_distance 60` (Hamming).
- Routing weights are **family-scoped** (`classical_local`, `robust_local`,
  `deep_optional`), each family weighted by base + measured texture, contrast,
  valid fraction and scale-gap indicators. These are policy defaults tracked in
  config, not scientific thresholds.

### 1.2 Matcher adapters (`backend/app/matching/adapters.py`)

- SIFT → strategy `sift`, family `classical_local` (scale-invariant, L2).
- ORB → strategy `orb`, family `robust_local` (binary, Hamming).
- `deep_optional` declared but truthfully UNAVAILABLE in this build (no model
  checked in) — the engine records it as constraint-failed instead of faking it.
- `matcher_score = 1 − distance/ref`, clamped to [0,1]: a normalized distance
  complement, never a confidence. Availability is a live capability probe.
- Detector/matcher failures map to explicit outcomes
  (`MATCHER_FAILED` / `NO_FEATURES`), never zero faked as "empty match".

### 1.3 Adaptive strategy engine (`engine.py`)

- Per tile pair: measure **scene conditions** from corregistered M2 condition
  records → classify texture, contrast, valid fraction, gsd/scale gap →
  compute family-scoped routing scores over the deterministic registry order
  → select highest-scoring **available** matcher (unavailable = constraint-failed
  and recorded).
- A recorded **decision** per tile: measured conditions, per-strategy score,
  selected strategy (or `UNAVAILABLE` when none satisfies). Routing is
  deterministic: repeated runs on identical inputs choose the same strategy.
- Strategy→family mapping is derived from the adapter registry (`all_matchers()`),
  which fixed an M1-era latent bug where scores were looked up by strategy id
  against family-keyed weights (see §4).

### 1.4 Candidate filtering (`candidates.py`) — explicit and recorded

```
raw candidates → [adapter ratio/distance/cross-check]
→ non-finite rejection (recorded)
→ valid-area (mask) rejection (recorded)
→ border rejection (recorded, skipped if tile dims unknown)
→ duplicate rejection (rounded identity, first occurrence kept)
→ candidate set (deterministic ordering by ascending descriptor distance)
```

Every tile's `threshold_counts` records exactly how many candidates fell at
each gate. On the correlated e2e fixture one tile recorded e.g.
`raw_candidates: 320 → mask_rejected: 0 → border_margin_rejected: 0 →
duplicates_rejected: 73 → candidate_set: 244 → candidate_set_threshold: 8`.

### 1.5 MATCH lifecycle (`service.py`, all under `/api/matching`)

States: `NOT_STARTED → BLOCKED → RUNNING → COMPLETE` (and `FAILED`).
Per-tile outcomes: `SUCCESS`, `NO_FEATURES`, `NO_CANDIDATES`,
`INSUFFICIENT_CANDIDATES`, `MATCHER_FAILED`, `MATCHER_UNAVAILABLE`, `TIMEOUT`.

1. **Prerequisites** — registered + validated pair, M2 PREPARE to the matcher
   boundary with a non-empty usable tile set; otherwise a stable block code
   (`PROCESSING_NOT_RUN`, `MATCHER_READINESS_BLOCKED`, `BUILD_MATCH_TILES_EMPTY`, …).
2. **Match-tile build** — sensor-native windows bounded to the confirmed
   overlap; tiles without a documented ground box pair by IoU fallback while
   staying inside the pair directory (containment enforced).
3. **Strategy routing + matcher run** — engine decisions per tile; available
   adapters run with the config's detector/matching params; per-run timeout is
   honoured per attempt (a TIMEOUT records the attempt trail, then the
   outcome chain derives the tile verdict — never a faked empty set).
4. **Candidate write** — per-tile `.npz` (x/y on A and B, score, distance,
   feature scale, orientation) + `.json` summary carrying the decision and the
   "not a verdict" license; a combined `candidates.json` index.
5. **Provenance** — `matching_manifest.json` (configuration, processing
   inputs, candidate artifact rel-paths + SHA-256, no absolute paths),
   `summary.json`, `strategy/decisions.json`, `matching_status.json`
   (run log, progress, per-tile attempts).

### 1.6 M2 quirk handling

- Tile ids are duplicated across sensors (`CS-P001-T###`); M3 derives unique
  match ids `<pair>-M###`.
- M2 tiles.json numeric fields arrive serialized as strings — `_norm_tile`
  parses them before use; missing `width`/`height` disable the border filter
  instead of emptying the set.

### 1.7 M3 API surface (all under `/api/matching`)

| Endpoint | Purpose |
| --- | --- |
| `GET /configurations` | available matcher configurations (`MC-M3-001` default) |
| `GET /overview` | honest aggregate — **BLOCKED** with reason when no real validated pair exists |
| `GET /{pair_id}/status` | run state, progress, summary, blocked code, run dir |
| `POST /{pair_id}/run` | run MATCH (optional `configuration_id`; 422 on unknown config) |
| `POST /{pair_id}/reset` | wipe `derived/matches/<pair>` (raw + M2 artifacts untouched) |
| `GET /{pair_id}/manifest` | provenance hash manifest (relative-only paths) |
| `GET /{pair_id}/summary` | run summary |
| `GET /{pair_id}/decisions` | per-tile routing decisions |
| `GET /{pair_id}/candidates` | candidate index across tiles |
| `GET /{pair_id}/tiles` | match-tile list (outcome, strategy, conditions signature) |
| `GET /{pair_id}/tiles/{id}` | single match tile |
| `GET /{pair_id}/tiles/{id}/candidates` | tile candidates (points + distance + score) — traversal-guarded |

### 1.8 M3 frontend

- **MatchingPanel.jsx** (Analysis workspace): run/reset/manifest controls,
  match-stage pipeline (Align → Strategy → Matchers → Candidates → Run),
  state badge + progress, blocked/failed banners, summary block, per-tile
  decision cards (texture/contrast/gap/vf signature + strategy score/status),
  candidate explorer with threshold chips, dual A/B scatter planes (≤600 pts)
  and a Matching readout, attempt trail, and a fixed Trust Gate
  **NOT_RUN (M4)** lock banner.
- **Overview**: milestone M3 hero, `match` pipeline stage reflects real state,
  integration-status list gained "Correspondence search (M3)", match-locked
  modal copy updated.
- **Data**: per-pair M3 status chip (state + candidate count) with honest
  NOT_RUN wording.
- **Results**: factual workspace — candidate sets as observations, Trust Gate
  closed / outcome model, empty-state honesty note (no fabricated metrics).
- Pill badges updated to "M3 · Adaptive Matcher Intelligence".

## 2. Verification performed

| Check | Result |
| --- | --- |
| `pytest -q` | **99 passed** — 25 M3 tests in `tests/test_m3.py` (config + rejection, configurations endpoint incl. `deep_optional` unavailable, adapter matrix, SIFT/ORB shifted-window correspondences, mask steering, engine selection vs condition/scale-gap, unavailable+constraint recording, determinism + `final_confidence` absence, scale-gap classification, filter counts/ordering, mask+border rejection, INSUFFICIENT_CANDIDATES, MATCHER_FAILED vs NO_FEATURES, artifact roundtrip + license wording, overview honest zero, full lifecycle + derived layout, manifest relative-only + SHA-256 + honesty, pair-not-prepared BLOCK, 404/422, reset scoping, tiny-budget TIMEOUT, plus bug-hunt regressions: non-finite rejection, path-traversal guard, zero-dims border skip) |
| `smoke_test.py` | **39/39 PASS** — incl. `m3-configurations`, `m3-overview-honest-zero` (BLOCKED), unknown pair status/run → 404, M2/M1 checks, frontend render + vite proxy |
| `npm run build` (vite) | PASS (246.35 kB JS) |
| `node frontend/ssr-smoke.mjs` | PASS — all pages including the Matching workspace render headless |
| e2e correlated run (TEMP script) | run **COMPLETE**, 6 match tiles, 872 candidate correspondences, 6× SUCCESS, strategy sift; per-tile threshold counts recorded; manifest/config `MC-M3-001`; tile payload keys stable |

The full MATCH path is exercised in tests with correlated synthetic fixtures
(`tests/fixturegen.py`, `geometry.source: TEST_FIXTURE` only) — the only route
to full readiness until real products arrive.

## 3. Bugs found & fixed (spec §38 bug hunt + test-driven discovery)

| # | Bug | Impact if unfixed | Fix |
| --- | --- | --- | --- |
| B1 | Engine looked up routing scores by **strategy id** against **family-keyed** config weights → all scores 0, "sift" won by tie-break | silent systematic mis-routing | map strategy→family via `all_matchers()`; rows carry `family`; tests assert selection vs conditions |
| B2 | `configuration_id` swap check quoted before assignment in full-runs logging | — | ordering fixed in `run()` |
| B3 | `TileOutcome.TIMEOUT` attempt replayed/mis-derived as `NO_CANDIDATES` (`last_matcher_ok` only) | genuine timeout hidden as empty result | outcome chain: best candidate → any TIMEOUT → TIMEOUT → all UNAVAILABLE → MATCHER_UNAVAILABLE → last-matcher-ok+attempts → NO_CANDIDATES → NO_FEATURES → MATCHER_FAILED |
| B4 | `configurations_public()` listed only *available* matchers, hiding the declared-but-unavailable `deep_optional` boundary | UI/API divergence from adapter registry | list `all_matchers()` incl. available:false entries |
| B5 | Candidate filter computed border interior against tile `width` strings / None (NaN-safe ordering, string comparisons) | masked `border_margin_rejected` accounting; keypoint `width` fix from e2e | normalize tiles; use `float`/round; verify candidates on 6/6 tiles |
| B6 | No non-finite guard on adapter output | NaN/Inf could reach diagnostics, ordering and JSON (invalid NaN literals) | explicit non-finite rejection recorded in `threshold_counts`; regression test |
| B7 | `tile_candidates` joined user-controlled `match_tile_id` into the candidate path | path traversal out of the run dir if the route ever widened | resolved-path containment guard returning None + regression test |
| B8 | Border rejection with unknown tile dims (0×0) rejected every candidate | hidden `NO_CANDIDATES` on malformed tiles.json | skip border filter when dims unknown; regression test |

## 4. Real-data blocker (unchanged from M1/M2, in M3 terms)

- Official OHRC/TMC-2 archives (ISSDC PRADAN, https://pradan.issdc.gov.in/ch2/)
  require an account **and administrator approval**; no anonymous download exists.
- `/api/matching/overview` therefore returns `blocked: true` with reason
  "No real validated lunar pair is available, so real-data matching is BLOCKED."
- Unblocking steps are identical to `reports/M1_REPORT.md` / `reports/M2_REPORT.md`.

## 5. Next (M4 and later, not started)

The **Trust Gate** is explicitly declared (every artifact and the UI state "Trust
Gate = M4, NOT_RUN") but intentionally not implemented: candidate sets are
observations until independent geometric verification executes. M4 (independent
verification → trust), M5 (spatial reliability), M6 (registration) and beyond
remain pending.

## 6. Artifacts

- `backend/app/matching/` — `config.py` (MatcherConfig, MC-M3-001), `states.py`
  (run states, tile outcomes, block codes), `adapters.py` (SIFT/ORB/deep boundary
  + registry), `engine.py` (routing + decisions), `candidates.py` (filters,
  diagnostics, per-tile artifacts), `events.py`, `service.py` (lifecycle,
  prerequisites, per-tile execution, overview), `manifest.py`.
- `backend/app/api/matching.py`, `backend/app/api/router.py` (wired),
  `backend/app/config.py` (`m3_config`), `backend/app/data.py`
  (`derived/matches/<pair>/<proc>/<matcher>/` tree), `backend/app/api/health.py`
  (`/meta` `m3_config`).
- `tests/test_m3.py` (25 tests), `tests/fixturegen.py` (correlated fixtures),
  `smoke_test.py` (M3 checks, 39 total).
- `frontend/src/components/MatchingPanel.jsx` (new), `frontend/src/pages/`
  `Overview.jsx`, `Analysis.jsx`, `Data.jsx`, `Results.jsx`,
  `frontend/src/App.jsx`.
- `configs/app.yaml` (new `m3:` section), `data/README.md` (M3 outputs),
  this report.