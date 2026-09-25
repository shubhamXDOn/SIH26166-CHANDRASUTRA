# M1 — Real PRADAN Data Intake & Pair Registry (Corrected Milestone)

**Milestone:** M1 — Real-data intake hardening
**Report date:** 2026-09-21
**Status:** **DONE** (tooling) / **BLOCKED** (real products not yet placed — operator action required)

---

## 1. Objective

Activate the real-data (PATH A) intake inside the existing CHANDRASUTRA repo:
given genuine ISRO/ISSDC PRADAN Chandrayaan-2 OHRC + TMC-2 products placed
under `data/raw`, the system must detect them, classify their source
honestly, derive overlap from structural footprint evidence, and register a
traceable pair — while preserving all existing M0–M13 behaviour and the
frozen synthetic evidence `EXP-EE0EBE7187E5`.

## 2. What was built

### 2.1 PDS4 metadata depth (`backend/app/loader.py`)
- Structured footprint extraction: `Geographic_Extent` bounding box
  (west/east/north/south coordinates) + `Footprint_Geometry` vertices →
  `footprint_struct` (bbox + polygon) with a readable `footprint_summary`.
- Illumination/viewing/geometry angles collected numerically only when real
  values exist (`solar_zenith_angle`, `incidence_angle`, `phase_angle`,
  `sensor_azimuth`, `emission_angle`); anything absent stays `UNKNOWN`.
- Orbit number extraction.
- **Source classification** `classify_product_source()` →
  `REAL_PRADAN` / `TEST_FIXTURE` / `UNKNOWN`, using the official
  `urn:isro:ch2` logical-identifier namespace, the official naming convention
  with a PDS4 label, and explicit fixture markers (`urn:fixture`,
  `test fixture`, `synthetic`). Never guesses.
- `ProductInfo.source_class` surfaced in `to_dict()` and load_product.

### 2.2 Pair schema + governance (`backend/app/pairs.py`)
- New `PairRecord` fields: `source_class_a`, `source_class_b`,
  `data_source_gate` (`PATH_A_REAL_DATA` | `PATH_B_SYNTHETIC_ONLY` |
  `PATH_UNKNOWN`), persisted to `pairs.json` + appended into `pairs.csv`.
- `data_gate()` gate resolver.
- `overlap_from_footprints()` — derives overlap from real footprint box
  interiors; missing/incomplete/disjoint evidence is reported honestly as
  `OVERLAP_UNCONFIRMED` with a machine-readable reason, never invented.
- `scan_raw_products()` read-only inventory with classification.
- `select_real_pair()` prefers genuine OHRC and TMC-2 (C > D > R level).
- `register_real_pair()` — registers ONE genuine pair; raises an honest
  ValueError for anything not `REAL_PRADAN`; idempotent (same raw files →
  same pair ID, no duplicates).
- `validate_record()` gains a `data_source_gate` check.

### 2.3 API + CLI
- `POST /api/pairs/auto-register` — scans, classifies, selects, registers and
  validates the first real OHRC × TMC-2 pair; returns a structured **BLOCKED**
  error (400) when genuine products are missing (never promotes fixtures).
- `GET /api/pairs/real-data/scan` — public read-only inventory + source
  breakdown + selected candidates.
- `/api/data/status` → `data_source` block: source breakdown, real pair ids,
  `requirements_met`, `pairs_by_gate`.
- `scripts/activate_real_data.py` — operator CLI; exit 0/1/2 (0 = real pair
  registered, 2 = BLOCKED). Writes `data/metadata/real_data_activation.json`.

### 2.4 Frontend (`frontend/src/pages/Data.jsx`)
- New `SourceBadge` (`REAL PRADAN DATA` / `SYNTHETIC TEST FIXTURE`) in the
  Registered Pairs table (new Source column) and in pair inspection.
- Frontend production build verified (`npm run build`, vite 7).

## 3. Verification
- `pytest tests/test_m1_realdata.py` — **14 passed**: classification for
  REAL-Shaped/Standard/Fixture-less labels; CONFIRMED / disjoint / missing
  overlap; gate rules; scan+select preferring real over fixtures;
  gated + idempotent registration; fixture rejection; validation
  (`VALID`, `raw_integrity=VERIFIED`, `benchmark_ready`); API auto-register +
  real-data scan + data status; honest BLOCKED; honest zero-count empty root.
- `pytest tests/test_m1.py` — **42 passed** (regression).
- `pytest tests/test_m12.py -k "pair or gate or reproducibility or ingest"` —
  **5 passed** (existing real-data gate machinery unaffected).
- Script blocked path: exit 2 with honest BLOCKED summary (no real data yet).
- Frontend `npm run build` clean.

## 4. Honesty notes
- The **synthetic fixtures** used by tests are REAL-SHAPED *structure* labels
  (`urn:isro:ch2` identity + footprint geometry) generated on the fly inside
  pytest tmp dirs; they are never committed, never placed in `data/raw`, and
  are clearly documented as structure validation in `tests/fixturegen.py`.
- The original fixtures (`urn:fixture`/`TEST FIXTURE`) keep classifying as
  `TEST_FIXTURE`; frozen evidence `EXP-EE0EBE7187E5` is untouched.
- No overlap value is ever assumed; `OVERLAP_UNCONFIRMED` carries the reason.

## 5. Artifacts
- `backend/app/loader.py`, `backend/app/pairs.py` (modified)
- `backend/app/api/pairs.py`, `backend/app/api/data.py` (modified)
- `scripts/activate_real_data.py` (new)
- `tests/test_m1_realdata.py` (new, 14 tests), `tests/fixturegen.py` (real-shaped labels)
- `frontend/src/pages/Data.jsx` (SourceBadge), `data/raw/README.md` (PATH A docs)
- `reports/M0_REAL_DATA_AUDIT.md` (new)

## 6. Blocked item (operator)
Real `.img` + `.xml` products are **not yet present** in `data/raw/ohrc` and
`data/raw/tmc2`. The tooling is ready; once the operator copies the genuine
PRADAN files in, run:

```
.\.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data
```

and proceed to M2 (real-data validation / preprocessing).

## 7. Final state
**DONE (intake tooling), BLOCKED (real files).**

---

**Milestone:** M1
**STATUS:** TOOLING COMPLETE — REAL PAIR REGISTRATION PENDING OPERATOR FILE COPY
**VERIFIED-ON:** 2026-09-21
**NEXT:** copy real files → run `scripts/activate_real_data.py` → M2.