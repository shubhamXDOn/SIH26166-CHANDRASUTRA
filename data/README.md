# SIH26166 — Data

## Official source

- ISRO / ISSDC PRADAN (Planetary Data Archive for Chandrayaan-2):
  - Portal: https://pradan.issdc.gov.in/
  - Chandrayaan-2 data: https://pradan.issdc.gov.in/ch2/
  - FAQ: https://pradan.issdc.gov.in/ch2/faq.xhtml

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

## Metadata requirements

- Every ingested product must carry provenance: sensor, product ID, source
  URL/collection, acquisition time (or UNKNOWN), coordinate/spatial extent
  (or UNKNOWN), and a checksum when obtainable.
- Unknown metadata stays **UNKNOWN**. Never fabricated.

## Overlap confirmation requirement

- A pair is only used for matching after its spatial overlap has been
  **confirmed** via metadata (and, in later milestones, verified geometrically).
- No confirmed overlap -> no matching is attempted.

## Derived-data policy

- `data/derived/` is reproducible: regenerate from raw + config, never edit
  by hand.
- Every derived artifact is named/labeled with the producing Pair ID and
  Configuration ID once those exist.
- Results are traceable: derived -> config -> raw product IDs.