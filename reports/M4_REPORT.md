# M4 Report — Trust Gate & Independent Geometric Verification (CHANDRASUTRA · SIH26166)

**Milestone:** M4 — the independent Trust Gate over M3 candidate
correspondences: deterministic RANSAC homography/affine verification, condition
number (degeneracy) detection, residual policy, spatial reliability, symmetric
transfer cross-check, and a binary per-tile gate (TRUSTED / not TRUSTED) that
aggregates to a per-pair gate verdict (COMPLETE / FAILED).
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-16
**Status:**
- **Engineering: DONE** — the full M4 TRUST pipeline is implemented, tested
  (131 backend tests, 34 dedicated to M4), smoke-tested end to end over live
  HTTP (44/44 checks), and exercised on correlated synthetic fixtures (6 usable
  match tiles → gate COMPLETE, 6/6 tiles TRUSTED). Regression on the M0–M3
  suites is clean.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as
  M1/M2/M3. M4 truthfully reports **BLOCKED** via `/api/trust/overview` and
  per-pair status rather than fabricating a gate verdict. Synthetic fixtures
  exist only in automated tests and a controlled TEMP e2e script — never as
  benchmark pairs.

> **Honesty rule:** M4 produces **binary verdicts, never confidence floats.**
> A tile is TRUSTED only when every independent check passes; otherwise its
> reason codes (`TG_PASS_*` / `TG_BLOCK_*` / `TG_FAIL_*`) explain exactly which
> gate refused it. No artifact contains `final_confidence`, an accuracy
> percentage, a probabilistic score, or any fabricated metric. `BLOCKED`,
> `FAILED`, `INSUFFICIENT` and `TIMEOUT` are first-class outcomes.

---

## 1. What M4 delivers

### 1.1 Trust configuration (`configs/app.yaml` → `m4:`)

- `TG-M4-001` / v1 — the runnable configuration exposed by
  `GET /api/trust/configurations` (default configuration).
- Geometry: seeded RNG (seed 42), max 2000 RANSAC iterations, 3.0 px threshold,
  homography preferred, affine fallback.
- Acceptance refs: `min_usable 8`, `min_inliers 8`, `inlier_ratio 0.3`,
  residual policy `mean 10.0 / median 6.0 / p95 15.0 px`, spatial grid 4×4,
  `min_grid_occupied 4`, `max_concentration 0.6`,
  `max_condition_number 1000000`, symmetric cross-check `8.0 px`.
- These are engineering defaults with a `source_reference` and a documented
  "no scientifically tuned thresholds" note — policy values, not science claims.

### 1.2 Geometry engine (`backend/app/trust/geometry.py`) — deterministic

- `estimate_homography` / `estimate_affine` implement deterministic RANSAC on a
  seeded `np.random.RandomState` (no cv2 RNG), minimal-set (4/3) direct linear
  transform fitting, symmetric transfer residual scoring, bounded iterations,
  and bisection-free maximum-inlier consensus. Both return a `ModelResult`
  (matrix, inlier mask/count/ratio, residual stats, iterations used, seed used).
- `compute_symmetric_transfer` measures forward + inverse transfer error per
  candidate (inverse via `np.linalg.inv`, guarded against singular matrices);
  `validate_model_matrix` rejects ill-conditioned 2×2 linear parts before any
  acceptance.
- Included in the pipeline by design: **M6-style registration internals run at
  M4 inside the Trust Gate**, so geometry verification and registration share
  one deterministic code path — M6 later surfaces the model as a product.

### 1.3 Degeneracy + spatial reliability (`degeneracy.py`, `spatial.py`)

- **Degeneracy** — input-condition warnings (exact scale / near-scale /
  repeated-column constraints, unknown GSD handling, collinear/duplicate point
  sets from the condition number of the design matrix) plus model-condition
  hardening. If the condition number exceeds `max_condition_number`, verdicts
  carry `TG_BLOCK_DEGENERATE_SETUP` / `TG_BLOCK_ILL_CONDITIONED_MODEL`.
- **Spatial support** — inlier spread is measured over a `grid`-by-`grid`
  occupancy histogram normalized inside the inlier bounding box (so a tight
  cluster cannot fill the grid): `grid_cells_occupied ≥ min_grid_occupied`
  and `concentration_ratio ≤ max_concentration` must both hold, else
  `TG_BLOCK_INSUFFICIENT_SPATIAL_SUPPORT` / `TG_FAIL_LOW_SPATIAL_SUPPORT`.
  Zero/one-inlier scenes degrade safely (no index errors, no division by zero).

### 1.4 Trust engine (`backend/app/trust/engine.py`) — per-tile verdict

Ordered, independently attributable checks (each maps to pass/block/fail
reason codes):

```
1. candidate integrity    → non-finite/insufficient usable count   (INSUFFICIENT / TG_BLOCK_CANDIDATE_INTEGRITY)
2. geometry verification  → degeneracy scan → RANSAC (homography/affine) → condition check
3. inlier policy          → min_inliers · inlier_ratio            → TG_FAIL_INSUFFICIENT_INLIERS
4. residual policy        → mean / median / p95 all within refs    → TG_FAIL_EXCESSIVE_RESIDUAL
5. spatial support        → occupancy + concentration over grid    → TG_BLOCK/TG_FAIL*
6. model validity         → condition number, finite matrix        → TG_BLOCK_*
7. symmetric cross-check  → max symmetric transfer ≤ threshold px  → TG_FAIL_CROSS_CHECK
8. TRUSTED ⟺ 1–7 all pass                                          (trust_state TRUSTED, reasons TG_PASS_*)
```

Determinism is a hard requirement (identical inputs → identical verdicts) and is
tested at unit, engine and full-run level.

### 1.5 TRUST lifecycle (`backend/app/trust/service.py`, all under `/api/trust`)

States: `NOT_STARTED → BLOCKED → RUNNING → COMPLETE` (and `FAILED`).
Per-tile states: `NOT_RUN / RUNNING / TRUSTED / REJECTED / INSUFFICIENT / FAILED`.

1. **Prerequisites** — the pair must carry a real M3 match run (deepest
   `derived/matches/<pair>/<proc>/<matcher>/summary.json`) whose per-tile
   `outcome == SUCCESS` with candidates > 0; otherwise a stable block code
   (`PAIR_NOT_REGISTERED`, `MATCHING_NOT_AVAILABLE`, `MATCH_OUTPUTS_MISSING`).
   This closed the M1-era latent seam where the service assumed a
   `match_summary.json` layout that M3 never produces.
2. **Gate run** — iterate the match summary's tiles (each has a candidate
   artifact), run the trust engine with the resolved config, write per-tile
   verdicts and `runtime_seconds`; an execution timeout marks all remaining
   tiles `FAILED` (`TG_FAIL_RUNTIME_TIMEOUT`) and flips the gate to `FAILED`.
3. **Gate verdict** — `COMPLETE` iff `trusted_tiles ≥ 1`, else `FAILED`.
   Verdict and reasons are persisted; the run is re-runnable and deterministic.
4. **Provenance** — `trust_manifest.json` (configuration + match run inputs +
   verdict rel-paths + SHA-256, relative-only paths), `summary.json`,
   `tile_trust.json`, `policies/applied.json`.
5. **Service-level safety** — unknown trust configuration IDs return
   `BLOCKED` / `TRUST_UNKNOWN_CONFIG` (never silently run with wrong defaults);
   tile ids are validated against `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` and
   resolved inside the tile directory (path-traversal hardened).

### 1.6 M4 API surface (all under `/api/trust`)

| Endpoint | Purpose |
| --- | --- |
| `GET /configurations` | available trust configurations (`TG-M4-001` default) |
| `GET /overview` | honest aggregate — **BLOCKED** with reason when no real validated pair exists |
| `GET /{pair_id}/status` | gate state, block code, run dir, summary |
| `POST /{pair_id}/run` | run Trust Gate (optional `trust_configuration_id`; unknown config → 404) |
| `POST /{pair_id}/reset` | wipe `derived/trust/<pair>` (raw + M2 + M3 artifacts untouched) |
| `GET /{pair_id}/manifest` | provenance hash manifest (relative-only paths) |
| `GET /{pair_id}/summary` | run summary (trusted / rejected / failed / processed counts) |
| `GET /{pair_id}/tiles` | per-tile verdict cards |
| `GET /{pair_id}/tiles/{tile}` | single tile verdict (model, spatial, cross-check evidence) — traversal-guarded |

`/api/meta` exposes `m4_config` (with `trust_configuration_id: TG-M4-001`);
`/api/health` reports milestone M4 / version 0.3.0.

### 1.7 M4 frontend

- **TrustPanel.jsx** (Analysis workspace, downstream of Matching): run/reset/
  manifest controls, gate state badge (NOT_STARTED/BLOCKED/RUNNING/COMPLETE/
  FAILED) with block-code banners, summary block (trusted/rejected/failed), and
  per-tile verdict cards showing trust state, reason codes, model type +
  inlier/outlier counts + residual stats, spatial diagnostics and the symmetric
  cross-check readout.
- **Overview**: milestone M4 hero, `trust` pipeline stage reflects real state,
  integration-status list gained "Trust Gate (M4)", pill badges "M4 · Trust
  Gate".
- **MatchingPanel** lock banner text updated (Trust Gate now executes at M4).
- **Data / Results**: per-pair M4 status chip (gate state) and a factual
  verdict workspace (verdict cards, no confidence floats, empty-state honesty).

## 2. Verification performed

| Check | Result |
| --- | --- |
| `pytest -q` (full suite) | **131 passed** — 34 M4 tests in `tests/test_m4.py` (config registration/load/endpoint; RANSAC + affine translation recovery, noise rejection, collinear degeneracy rejection, symmetric transfer smallness, affine scale recovery, determinism; spatial occupancy/cluster-fail/zero-inlier safety; engine verdicts TRUSTED / INSUFFICIENT / collinear-reject / cluster-reject / residual-policy reject / cross-check / determinism; full lifecycle through a real M3 run → COMPLETE + FAILED gates; honest BLOCKED; overview aggregates; unknown pair + unknown config → 404 and service `TRUST_UNKNOWN_CONFIG` block; manifest relative-only + no fake claims; reset scoping; tile path-traversal safety; runtime TIMEOUT → FAILED gate; re-run determinism) plus the M0–M3 regressions |
| `smoke_test.py` | **44/44 PASS** — incl. `m4-meta-config`, `m4-configurations` (`TG-M4-001`), `m4-overview-honest-zero`, unknown-pair trust status/run → 404, M3/M2/M1 checks, frontend render + vite proxy |
| `npm run build` (vite) | PASS (257.94 kB JS) |
| `node frontend/ssr-smoke.mjs` | PASS — all pages including the Trust workspace render headless |
| e2e correlated run (TEMP script) | M3: 6 match tiles, 6253 candidates → M4 run: gate **COMPLETE**, 6/6 tiles TRUSTED. Sample tile: homography, 1954 inliers / 1954 usable (ratio 1.00), residual mean ≈6.5e-13 px, max symmetric transfer 0.0 px, spatial occupancy 16/16 cells, concentration 0.233, runtime ≈1.5 s; verdict reasons are exactly the seven `TG_PASS_*` codes |

The full TRUST path is exercised in tests with correlated synthetic fixtures
(`tests/fixturegen.py`, `geometry.source: TEST_FIXTURE` only) — the only route
to full readiness until real products arrive.

## 3. Bugs found & fixed (spec §32/§38 bug hunt + test-driven discovery)

| # | Bug | Impact if unfixed | Fix |
| --- | --- | --- | --- |
| B1 | TrustService read a `match_summary.json` schema M3 never writes (M3 writes `matches/<pair>/<proc>/<matcher>/summary.json` with `per_tile[{match_tile_id, outcome, candidates, …}]` and artifact `candidates/<mid>.npz`) | every real M3→M4 hand-off would silently block or fail | `_match_run_dir()` locates the deepest run dir by `summary.json` presence; prerequisites and run read the real layout; tile ids from `match_tile_id`; `TrustBlockCode` imported |
| B2 | PyYAML parses `1e6` / `1.0e6` as **strings**, not floats → `cond > max_cond` would raise on Python 3 | latent `TypeError` in degeneracy check | `configs/app.yaml` uses `max_condition_number: 1000000`; `TrustConfig.from_dict` coerces every numeric field via `_f()` |
| B3 | Gate could stay `RUNNING`/odd when no tile trusted | gate verdict not a true binary | `gate_state = COMPLETE if trusted_tiles > 0 else FAILED` |
| B4 | `tile_trust` resolved user tile ids straight into `tiles/<id>.json` | `../..` traversal could read `trust_status.json` outside the tile dir | `_SAFE_ID` regex + resolved-path containment; returns `INVALID_TILE_ID` instead |
| B5 | Engine enforced mean residual only; median/p95 configured but unused | residual policy under-enforced | `TG_FAIL_EXCESSIVE_RESIDUAL` on any of mean/median/p95 exceeding refs (+ regression test) |
| B6 | Service silently ran with default config for unknown trust config ids | wrong-config runs not blocked | `_VALID_TRUST_CONFIG_IDS` guard → `BLOCKED` / `TRUST_UNKNOWN_CONFIG` (+ test) |
| B7 | Test fixtures: linspace points were quasi-collinear (DLT unstable); outliers ≥ n-1 on n=3 tiles; collinear/cluster generators didn't actually trigger their checks | unreliable unit fixtures | uniform scatter, `min(outliers, n-1)`, genuine collinear pts_a (a*x+b), 70/30 cluster+spread pattern for concentration > 0.6 |

## 4. Real-data blocker (unchanged from M1/M2/M3, in M4 terms)

- Official OHRC/TMC-2 archives (ISSDC PRADAN, https://pradan.issdc.gov.in/ch2/)
  require an account **and administrator approval**; no anonymous download exists.
- `/api/trust/overview` therefore returns `blocked: true` with reason
  "No validated real pair has completed matching, so the Trust Gate is BLOCKED."
- Unblocking steps are identical to `reports/M1_REPORT.md` / `reports/M2_REPORT.md`.

## 5. Next (M5–M12)

- **M5 (spatial reliability)** — surface per-tile spatial evidence into
  spatial-selection consumers; **M6 (registration)** — expose the verification
  models (homography/affine + diagnostics) as a first-class registration
  product (the engine already produces them).
- Metrics/benchmarks (M7), deep adapters (M8), AI explanation (M9), auth (M10),
  hardening (M11), final reproducibility (M12).

## 6. Artifacts

- `backend/app/trust/` — `config.py` (TrustConfig, TG-M4-001, float coercion),
  `states.py` (gate states, tile states, block/reason codes), `geometry.py`
  (deterministic RANSAC homography/affine, symmetric transfer, model validation),
  `degeneracy.py`, `spatial.py`, `engine.py` (per-tile verdict pipeline),
  `service.py` (lifecycle, prerequisites, gate verdict, timeout, safety),
  `manifest.py`.
- `backend/app/api/trust.py`, `backend/app/api/router.py` (wired),
  `backend/app/config.py` (`m4_config`), `backend/app/data.py`
  (`derived/trust/<pair>/<proc>/<matcher>/TG-M4-001/` tree),
  `backend/app/api/health.py` (`/meta` `m4_config`, milestone M4, version 0.3.0).
- `tests/test_m4.py` (34 tests), `tests/fixturegen.py` (correlated fixtures),
  `smoke_test.py` (M4 checks, 44 total).
- `frontend/src/components/TrustPanel.jsx` (new), `frontend/src/pages/`
  `Overview.jsx`, `Analysis.jsx`, `Data.jsx`, `Results.jsx`,
  `frontend/src/App.jsx`, `frontend/src/components/MatchingPanel.jsx`.
- `configs/app.yaml` (new `m4:` section), `data/README.md` (M4 outputs),
  this report.