# M5 Report — Spatial Reliability & Reliability-Aware Selection (CHANDRASUTRA · SIH26166)

**Milestone:** M5 — overlap-normalised scene grid, per-cell verified evidence,
neighbourhood support, connected-component analysis, boundary/fragmentation
reporting and reliability-aware selection (`SUPPORTED_REGION`) that produces a
`selected_correspondences.npz` provenance artefact for the future registration
milestone.
**Product:** CHANDRASUTRA — "Trustworthy Lunar Image Intelligence"
**Date:** 2026-09-16
**Status:**
- **Engineering: DONE** — the full M5 spatial reliability pipeline is
  implemented, tested (200 backend tests total, 67 dedicated to M5 including a
  22-case bug hunt), smoke-tested end to end (49/49 checks), and exercised on
  correlated synthetic fixtures (8×8 grid, 3 connected regions, 19 selected
  correspondences, deterministic across two runs). Regression on the M0–M4
  suites is clean; frontend builds and SSR-smoke pass.
- **Real-data execution: BLOCKED** — the same PRADAN approval blocker as
  M1–M4. M5 truthfully reports **BLOCKED** via `/api/spatial/overview` and
  per-pair status rather than fabricating any spatial verdict. Synthetic
  fixtures exist only in automated tests and a controlled TEMP e2e script —
  never as benchmark pairs.

> **Honesty rule:** M5 produces **binary or categorical evidence signals, never
> confidence floats.** Each cell is `reliable` or it is not; each component is
> `selected` or it is not; `BLOCKED`, `INSUFFICIENT`, `FAILED` and `NOT_MAPPED`
> are first-class outcomes. No spatial manifest, summary or API response contains
> `confidence`, `accuracy`, a scientific threshold claim, or any fabricated
> alignment metric. The note "Engineering/policy defaults only; no scientifically
> tuned lunar thresholds exist yet" appears in the manifest and API responses.

---

## 1. What M5 delivers

### 1.1 Spatial reliability configuration (`configs/app.yaml` → `m5:`)

- `SR-M5-001` / v1 — the sole registered configuration exposed by
  `GET /api/spatial/configurations`.
- Grid: `8 × 8`, edge tolerance `0.5 px`.
- Reliability: `min_verified_inliers_per_cell 4`, `min_trusted_tiles_per_cell 1`.
- Neighbourhood: `support_radius_cells 1` (Moore 8-connected).
- Fragmentation: enabled; boundary: `edge_policy REPORT_ONLY`; connected
  components: 8-connectivity.
- Selection: `SUPPORTED_REGION` — `min_component_cells 4`,
  `min_component_correspondences 16`, `min_selected_region_cells 4`,
  `max_selected_correspondences 4000`, `largest_evidence_first` tie-breaking.
- Execution: `max_runtime_seconds 60`.
- Source: `engineering defaults` with `source_reference` and an explicit
  "no scientifically tuned thresholds" note — policy values, not science claims.

### 1.2 Scene mapping (`backend/app/spatial/mapping.py`)

- `load_scene_map()` resolves each M3 match-tile pair into a bi-directional
  sensor-pixel → normalised coordinate mapping by reading M2 tile origins
  (`crops/tiles.json`) and the scene overlap box (`diagnostics/overlap.json`).
  Only tiles whose sensor origin lives exactly at an overlap box corner are
  mapped; everything else returns `NOT_MAPPED` with a structured reason.
- `map_correspondences()` projects per-tile trust artefacts into
  `pair_overlap_normalized` coordinates, returning normalised positions,
  a `mapped` boolean mask and per-correspondence reason codes. Boundary points
  within `edge_tolerance_px` of the scene box are retained.
- Homogeneous coordinate validation (`valid_mask_2d`) ensures no `w≈0` points
  leak into the grid.

### 1.3 Scene grid + per-cell evidence (`backend/app/spatial/grid.py`, `reliability.py`)

- `Grid` partitions the normalised overlap box into `rows × cols` cells, each
  carrying an absolute pixel `box` for provenance and an `is_edge_cell` check.
- `compute_reliability()` iterates each mapped correspondence, recomputes inliers
  per trusted tile via `evaluate_tile()` with `TrustConfig.from_dict(m4_defaults)` (seed 42),
  and records: `verified_inlier_count`, `usable_correspondence_count`,
  `trusted_tile_count`, per-side verified/usable counts, `spatial_density`,
  `neighbor_support` (Moore neighbourhood minimum), and a boolean `reliable` /
  `supported` classification.
- Mapping side ambiguity is resolved by preferring `nx_a/ny_a` (sensor A = `side_a`)
  and falling back to `nx_b/ny_b` (sensor B) — never a hybrid per-cell.

### 1.4 Connected components + fragmentation + boundary (`reliability.py`, `selection.py`)

- Connected components use an 8-connectivity flood-fill over reliable cells.
  Each component records `cell_count`, `correspondence_count`, `trusted_tile_count`,
  bounding box, centroid (normalised and cell indices), edge-touching status, and
  a boolean `selected` flag.
- Fragmentation and boundary dictionaries are passed through to the reliability
  map summary for downstream diagnostics (composition, edge exposure, diagnostic
  labels).
- Selection: the `SUPPORTED_REGION` policy picks the largest reliable component
  that satisfies all size thresholds, verifies it still holds after limit
  capping, and writes `selected_correspondences.npz` with provenance fields
  (`x_a,y_a,x_b,y_b,scene_x,scene_y,scene_side,source_tile_id,source_candidate_index,
  side_a_cell_id,side_b_cell_id,component_id,selection_reason`).

### 1.5 M5 lifecycle (`backend/app/spatial/service.py`, all under `/api/spatial`)

States: `NOT_STARTED → BLOCKED → RUNNING → COMPLETE` (and `FAILED` / `INSUFFICIENT`).

1. **Prerequisites** — M4 trust run must exist and contain at least one
   `TRUSTED` tile (otherwise `NO_TRUSTED_EVIDENCE`). Scene mapping must
   succeed for at least one pair of tiles (otherwise `SPATIAL_MAPPING_UNAVAILABLE`).
2. **Run** — recompute inliers per trusted tile, map correspondences, build
   reliability grid, flood-fill components, select supported region, write all
   derived artefacts (`status.json`, `summary.json`, `reliability_map.json`,
   `components.json`, `cells.json`, `selection.json`, `mapping.json`,
   `policies/applied.json`, `selected_correspondences.npz`,
   `spatial_manifest.json`).
3. **Gate verdict** — `COMPLETE` if run completed (even with 0 selected);
   `INSUFFICIENT` only as a synthesis label; `FAILED` on unrecoverable error.
   Re-runnable and deterministic.
4. **Provenance** — manifest artefacts use POSIX relative paths (cross-platform),
   SHA-256 hashes, and no absolute or home-directory references.

### 1.6 M5 API surface (all under `/api/spatial`)

| Endpoint | Purpose |
| --- | --- |
| `GET /configurations` | available spatial reliability configurations (`SR-M5-001` default) |
| `GET /overview` | honest aggregate — **BLOCKED** with reason when no real validated pair exists |
| `GET /{pair_id}/status` | gate state, block code, spatial configuration, summary |
| `POST /{pair_id}/run` | run spatial reliability (optional `spatial_reliability_configuration_id`; unknown config → 404) |
| `POST /{pair_id}/reset` | wipe `derived/spatial/<pair>` (M4/M3/M2/raw untouched) |
| `GET /{pair_id}/manifest` | provenance hash manifest (POSIX relative-only paths) |
| `GET /{pair_id}/summary` | run summary (grid, tiles, scene, reliability, selection) |
| `GET /{pair_id}/map` | reliability map: per-cell evidence, `visualization.grid` (row-major 2-D token array), legend |
| `GET /{pair_id}/components` | connected component explorer |
| `GET /{pair_id}/cells` | full per-cell evidence table |
| `GET /{pair_id}/selection` | selection policy outcome, reason, selected cell/component IDs |
| `GET /{pair_id}/mapping` | scene mapping (tile → normalised box) |
| `GET /{pair_id}/selected-correspondences` | npz field list + per-field counts (binary artefact) |

`/api/meta` exposes `m5_config` (with `spatial_reliability_configuration_id: SR-M5-001`);
`/api/health` reports milestone M5.

### 1.7 M5 frontend

- **SpatialReliabilityPanel.jsx** (Analysis workspace, downstream of Trust): run/reset/
  manifest controls, gate-state badge, `BLOCKED` / `INSUFFICIENT` / `FAILED`
  message cards, and a `SCENE LOCKED` M6 honesty note.
  - **Summary badge row** — reliable cells, components, selected correspondences,
    selection_outcome, selected_correspondences.npz field names.
  - **Scene reliability grid** — CSS grid driven by `map.visualization.grid`
    states (`TYPE_SELECTED`, `TYPE_CONFIRMED`, `TYPE_NEEDS_TILES`,
    `TYPE_NOT_APPLICABLE`), legend, selected-cell count badges, fragmentation and
    boundary diagnostic strings.
  - **Component explorer** — component cards with cell count, correspondence
    count, trusted tiles, area proxy, bounding box, centroid, edge-touching and
    selected/not-selected badges; `selected_component_ids` region summary.
  - **Cell explorer** — scrollable table: cell_id, state (selected/reliable/
    observed/outer), inlier count, usable count, neighbour support, component ID.
- **Analysis.jsx** — MODULE_PLAN marks M5 `implemented: true`; M5 section added
  after Trust Gate with config badge `SR-M5-001`.
- **Pipeline.jsx** — PIPELINE now carries a `Reliability` stage between Trust
  and Register; grid layout adjusted to `xl:grid-cols-8`.
- **Overview.jsx** — hero badge shows `Milestone M5`, `useSpatialOverview`
  hook drives the pipeline reliability/register stages and integration-status
  rows (`Spatial selection (M5)`, `Registration (M6) LOCKED`).
- **Data.jsx** — pair inspection shows `Spatial {state}` badge alongside
  Trust, plus `M6 Registration LOCKED`; footer copy references M5.
- **Results.jsx** — new `M5 · Spatial reliability (open)` evidence card;
  outcome grid updated to `xl:grid-cols-4`.

---

## 2. Bug hunt (22 cases)

The M5 bug-hunt cases (B1–B22) exercise:

| ID | Title | Key check |
|----|-------|-----------|
| B1 | No scientific confidence in outputs | manifest + API note contain "engineering" / "no scientifically tuned" |
| B2 | Manifest has no absolute paths | `str(tmp)` never appears; all paths start with `derived/` |
| B3 | Manifest has no home-directory leak | CWD prefix never appears in manifest text |
| B4 | JSON outputs are UTF-8 | written files reopen as UTF-8 |
| B5 | Selected npz has no NaN scene coords | `scene_x` and `scene_y` arrays carry no NaN |
| B6 | Determinism across runs | identical pair + config → identical status, reliability, selection, npz |
| B7 | Empty cells.json after reset | reset clears derived spatial directory |
| B8 | OVERLAP_UNCONFIRMED blocks honestly | scene status `BLOCKED / SPATIAL_MAPPING_UNAVAILABLE` |
| B9 | Coverage-selected cells exist | `TYPE_SELECTED` cells present in visualization |
| B10 | Trusted-but-rejected correspondence excluded | re-selected npz excludes low-density cells |
| B11 | One-tile edge policy boundary | boundary-diagnostic entries emitted, not silently dropped |
| B12 | Tile with 0 inliers | cell remains `TYPE_NEEDS_TILES` |
| B13 | Unknown config returns 404 | `POST /run` with bogus config → HTTP 404 |
| B14 | Run not re-entrant | second run overwrites artefacts, no double-status |
| B15 | Status BEFORE run is NOT_STARTED | fresh pair → honest zero |
| B16 | Sum of component cell counts equals reliable cell count | no lost or duplicate cells |
| B17 | selected_cell_ids subset of reliable_cells | provenance constraint |
| B18 | npz selection_reason dtype is str | string-encoded reasons, no bytes |
| B19 | Scene grid orientation | row 0 maps to min y of scene box |
| B20 | Boundary tolerance point within tolerance maps | (x=0.0, col_start=0, tol=0.5) → mapped=True |
| B21 | Homogeneous w=0 point excluded | zero-w record → `mapped=False` |
| B22 | Max correspondences cap enforced | `capped_at_limit == true` when cap hit |

All 22 cases pass.

---

## 3. Regression summary

| Suite | Result |
|-------|--------|
| `pytest tests/ -q` | **200 passed** in 254 s |
| `smoke_test.py` (venv) | **49/49 PASS** |
| `npm run build` (frontend) | **built in 3.46 s** |
| `node frontend/ssr-smoke.mjs` | **7/7 PASS** |

No regressions. M4 trust tests and M3 matching tests remain green.

---

## 4. Known limitations

1. **No scientifically tuned thresholds** — grid dimensions, cell-count limits
   and support-radius values are engineering defaults. A future scientific
   milestone may adjust them; the current configuration carries explicit
   `source_reference` provenance.
2. **Binary `scene_side` mapping** — each cell adopts sensor A's normalised
   coordinates by preference. When both sides contribute inliers to the same
   cell, side-A dominates; this is documented, not a quality judgement.
3. **Real-data execution** — blocked on PRADAN approval. M5 truthful BLOCKED
   is the only honest state; synthetic fixtures exercise the full code path.
4. **Registration (M6)** — locked. M5 selects a reliability region but does not
   fit any geometric model.

---

*CHANDRASUTRA · SIH26166 — Milestone M5*
