# SIH26166 — Data

## Official source

- ISRO / ISSDC PRADAN (Planetary Data Archive for Chandrayaan-2):
  - Portal: https://pradan.issdc.gov.in/
  - Chandrayaan-2 data: https://pradan.issdc.gov.in/ch2/
  - FAQ: https://pradan.issdc.gov.in/ch2/faq.xhtml

> **Access note (M1):** PRADAN downloads require user registration **and**
> administrator approval. There is no anonymous download path, so a fully
> automated pipeline cannot fetch products in this environment. Product
> placement under `data/raw` is a manual, one-time step per approved download.

## Primary Phase-A sensors (Chandrayaan-2)

| Id     | Sensor                                   | Role in prototype                           |
| ------ | ---------------------------------------- | ------------------------------------------- |
| OHRC   | Orbiter High Resolution Camera           | high-resolution detail layer  (~0.25 m/px)  |
| TMC-2  | Terrain Mapping Camera 2                 | regional context / stereo layer (~5 m/px)   |

Reference/validation layer for later milestones:
- NASA LROC (Lunar Reconnaissance Orbiter Camera) — independent check data.

## Dataset strategy

- **Phase A (initial prototype):** at least one real, documented
  OHRC–TMC-2 pair, later a second challenging pair. Small, controlled,
  verifiable — not an archive.
- **Phase B (future):** additional Chandrayaan-2 scenes and optional
  cross-mission reference layers (LROC), still small and documented.
- We do **not** substitute random Google images, arbitrary Kaggle sets,
  generated lunar imagery, or demo images as scientific evidence.
- We do **not** download the entire mission archive.

## Raw data immutability (hard rule)

- Everything under `data/raw/` is **read-only by policy and by design**.
- No preprocessing, cropping, normalization, or conversion may ever write
  back into `data/raw/`.
- Any transformation writes to `data/derived/<stage>/` only.
- The backend's data service refuses to create directories under `raw/`.

## M1 metadata registry (M1)

Every registered pair writes a **canonical metadata record** to
`data/metadata/` — this is where traceability lives:

| File                          | Purpose                                              |
| ----------------------------- | ---------------------------------------------------- |
| `data/metadata/pairs.json`    | full versioned `PairRecord` for each pair (canonical) |
| `data/metadata/pairs.csv`     | flattened columns of the same records                |
| `data/metadata/pair_validation.json` | most recent validation result (checks, hashes, status) |
| `data/derived/visualizations/previews/` | derived 8-bit PNG previews (never the raw product) |

A `PairRecord` captures provenance (sensor, product ID, source, acquisition),
geometry (dimensions, dtype, nominal GSD), integrity (SHA-256 of each raw
file), overlap evidence, lifecycle timestamps, and placeholders for future
scientific results — which stay `null`/`NOT_RUN` until actually measured.

Pair IDs are deterministic (`CS-P001`, `CS-P002`, …). Validation re-verifies
file existence, PDS4 labels, readability, dimension/dtype correspondence,
SHA-256 hashes and the recorded overlap evidence, and marks a pair
**VALID / INVALID** independently of overlap status. `benchmark_ready`
requires a CONFIRMED overlap **with documented evidence**.

## Metadata requirements

- Every ingested product must carry provenance: sensor, product ID, source
  URL/collection, acquisition time (or UNKNOWN), coordinate/spatial extent
  (or UNKNOWN), and a checksum when obtainable.
- Unknown metadata stays **UNKNOWN**. Never fabricated.

## Overlap confirmation requirement

- A pair is only used for matching after its spatial overlap has been
  **confirmed** via metadata (and, in later milestones, verified geometrically).
- In M2 the overlap is recomputed from the documented per-sensor ground
  footprint at PREPARE time (`footprint_intersection`) and the evidence
  (`diagnostics/overlap.json`) is written for inspection; absence of geometry
  blocks the run (`NO_GEOMETRY`).
- No confirmed overlap -> no matching is attempted.

## M2 derived processing outputs (M2)

Running `POST /api/processing/{pair_id}/prepare` with configuration
`PC-M2-001` writes everything under
`data/derived/processing/<pair_id>/PC-M2-001/`:

| Artifact | Contents |
| --- | --- |
| `processing_status.json` | run state, stage log + per-stage status, blocked reason, matcher readiness, tile counts |
| `processing_manifest.json` | step → relative path + SHA-256 provenance (no absolute paths) |
| `<sensor>/preprocessed_display_u16.npy` | display-normalized 16-bit array (raw never touched) |
| `<sensor>/invalid_mask_u8.npy` | validity mask (bitflags 1 NaN/Inf, 2 saturated, 4 negative, 8 unknown) |
| `<sensor>/stats.json` | per-sensor statistics + normalization parameters |
| `crops/tiles.json` | tile registry (`CS-PNNN-T###`, origin, size, clipped/too_small, valid fraction indicators) |
| `crops/*.npy` | sensor-native tile arrays |
| `diagnostics/overlap.json` | computed footprint intersection evidence |
| `diagnostics/conditions.json` | per-tile per-sensor condition classification + thresholds applied |
| `<tile_id>_preview.png` | derived (lazy) tile preview PNG |

`POST /api/processing/{pair_id}/reset` deletes the pair's derived processing
directory; raw data and the registry records are left untouched.

## M3 derived matching outputs (M3)

Running `POST /api/matching/{pair_id}/run` with configuration `MC-M3-001`
against a PREPARE-ready pair writes everything under
`data/derived/matches/<pair_id>/<processing_config>/MC-M3-001/`:

| Artifact | Contents |
| --- | --- |
| `matching_status.json` | run state, run log + per-stage status, blocked code, progress, per-tile attempts |
| `matching_manifest.json` | configuration + processing inputs + candidate artifacts (relative paths, SHA-256) |
| `summary.json` | tiles matched, total candidates, strategy counts, outcome counts |
| `strategy/decisions.json` | per-tile routing decision: measured conditions, per-strategy scores, selected strategy |
| `candidates/candidates.json` | candidate index across match tiles (outcome, strategy, counts, diagnostics) |
| `candidates/<mid>.npz` | candidate points on both windows + matcher score + descriptor distance + feature scale/orientation |
| `candidates/<mid>.json` | per-tile summary + decision + "not a verdict" note |
| `events/<mid>.json` | per-attempt runtime events (per m3 event stream) |

Candidate sets are **observations**, never verdicts: independent geometric
verification and the resulting trust state are **NOT_RUN (M4 Trust Gate)**, and
no accuracy/confidence value is produced or stored. Filter counts
(`mask / border / non-finite / duplicate / candidate set`) are recorded per
tile so the reduction from raw matches to the candidate set is fully auditable.

`POST /api/matching/{pair_id}/reset` deletes the pair's derived matches
directory; `derived/processing` and the raw data are untouched.

## M4 derived trust outputs (M4)

Running `POST /api/trust/{pair_id}/run` with configuration `TG-M4-001` against
MATCH outputs writes everything under
`data/derived/trust/<pair_id>/<processing_config>/<matcher_config>/TG-M4-001/`:

| Artifact | Contents |
| --- | --- |
| `trust_status.json` | gate state (NOT_STARTED/BLOCKED/RUNNING/COMPLETE/FAILED), block code, gate verdict, run dir |
| `trust_manifest.json` | trust configuration + match run inputs + verdict artifacts (relative paths, SHA-256) |
| `summary.json` | trusted / rejected / failed / processed tile counts + reasons aggregated |
| `tile_trust.json` | per-tile verdicts: model (type, inlier/outlier counts, residual stats, iterations, seed), spatial diagnostics, symmetric cross-check, reasons |
| `policies/applied.json` | geometry model-selection + degeneracy + residual + spatial threshold trace |

Trust verdicts are **binary and honest**: a tile is `TRUSTED` only when every
independent check passes (candidate integrity, geometry model + inliers,
residual policy, spatial support, zero-degeneracy, symmetric cross-check under
the threshold). Otherwise it is `REJECTED` / `INSUFFICIENT` / `FAILED` with
recorded reason codes (`TG_PASS_*` / `TG_BLOCK_*` / `TG_FAIL_*`). The gate is
`COMPLETE` only if at least one tile is TRUSTED; otherwise `FAILED`. No
confidence register, accuracy percentage, or probabilistic score is ever
produced — trust is a verdict, not a float.

`POST /api/trust/{pair_id}/reset` deletes the pair's derived trust directory;
`derived/matches`, `derived/processing` and the raw data are untouched.

## M5 derived spatial reliability outputs (M5)

Running `POST /api/spatial/{pair_id}/run` with configuration `SR-M5-001` against
the M4 trust outputs creates:

`data/derived/spatial/<pair_id>/<processing_config>/<matcher_config>/<trust_config>/SR-M5-001/`:

| File | Content |
| ---- | ------- |
| `status.json` | gate state (NOT_STARTED/BLOCKED/RUNNING/COMPLETE/FAILED/INSUFFICIENT), block code, spatial configuration |
| `summary.json` | grid dimensions, trusted/processed tiles, scene mapping counts, reliability counts, selection outcome |
| `reliability_map.json` | per-cell evidence (verified inliers, usable correspondences, neighbour support, reliable/supported booleans), fragmentation and boundary, `visualization.grid` (row-major token array + legend) |
| `components.json` | connected reliable-region components (cell count, correspondence count, bounding box, centroid, edge-touching, selected flag) |
| `cells.json` | full per-cell evidence table (same fields as reliability_map cells, without visualization) |
| `selection.json` | selection policy mode, outcome, decision_reason, selected cell/component IDs, reason_counts, capped_at_limit |
| `mapping.json` | scene mapping (tile origins, normalised box, mapped status) |
| `policies/applied.json` | all applied spatial policies + source trust/match config IDs |
| `selected_correspondences.npz` | binary provenance arrays: `x_a, y_a, x_b, y_b, scene_x, scene_y, scene_side, source_tile_id, source_candidate_index, side_a_cell_id, side_b_cell_id, component_id, selection_reason` |
| `spatial_manifest.json` | spatial configuration + match/trust inputs + artifact paths (POSIX relative-only, SHA-256) |

The spatial run produces **measured spatial evidence positions**, not a
registration model. A cell is `reliable` or it is not; a component is `selected`
or it is not; `BLOCKED`, `INSUFFICIENT`, `FAILED` and `NOT_MAPPED` are
first-class outcomes. No accuracy percentage or confidence score is ever
produced.

`POST /api/spatial/{pair_id}/reset` deletes the pair's derived spatial directory;
`derived/trust`, `derived/matches`, `derived/processing` and the raw data are
untouched.

## Derived-data policy

- `data/derived/` is reproducible: regenerate from raw + config, never edit
  by hand.
- Every derived artifact is named/labeled with the producing Pair ID and
  Configuration ID once those exist.
- Results are traceable: derived -> config -> raw product IDs.