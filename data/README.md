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

## Derived-data policy

- `data/derived/` is reproducible: regenerate from raw + config, never edit
  by hand.
- Every derived artifact is named/labeled with the producing Pair ID and
  Configuration ID once those exist.
- Results are traceable: derived -> config -> raw product IDs.