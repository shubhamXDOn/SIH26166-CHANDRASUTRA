# M2 — Real Data Validation, Preprocessing, Overlap & Crop (Progress Report)

**Milestone:** M2 — Real-data validation, logical preprocessing, overlap and crop
**Report date:** 2026-09-21
**Execution status:** `CASE D (no real products on disk)`
**M2 TOOLING / STRUCTURAL VALIDATION = DONE**
**REAL-DATA EXECUTION = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Validate genuine OHRC × TMC-2 pairs **after** M1 intake and drive them into
read/preprocess/overlap/crop without corrupting the immutable raw archive or
inventing any scientific fact. With real PRADAN `.img`+`.xml` still absent
(CASE D), M2 delivers the complete, honest tooling and verifies it on
REAL-SHAPED structural fixtures; genuine-data execution stays BLOCKED until
the operator copies the files. No M14 introduced; M0–M13 preserved; frozen
synthetic evidence `EXP-EE0EBE7187E5` untouched.

## 2. What was built

### 2.1 Structural overlap engine (`backend/app/pairs.py`)
- `structural_overlap()` + thin wrapper `overlap_from_footprints()` (keeps the
  historical `(status, evidence)` contract).
- Method priority: `polygon_intersection` (only when trustworthy) →
  `bbox_intersection` (longitude-wrap aware) → `OVERLAP_UNCONFIRMED`.
  Every verdict carries `method`, `reason`, `evidence` and `intersection`.
- `_lon_window_intersection` resolves 0↔360 deg wraparound; `_clip_polygon`
  (Sutherland–Hodgman) normalizes polygon orientation so a clockwise clip
  polygon cannot silently empty the intersection.
- Polygon trust gates: ≥3 unique vertices, size cap, and the polygon bounding
  box must be consistent with the label bounding box (a stray degenerate
  vertex like `(0,0)` forces an honest bbox fallback, never a wrong result).

### 2.2 M2 validation object (`backend/app/processing/validation.py`, new)
- Per-product: PDS4 label identity (logical id, product class, instrument,
  array geometry, data type, time), numeric sanity, sensor consistency
  (filename vs recorded), and IMG/XML **binary-size consistency**
  (PASS exact / FAIL truncated / WARNING oversized).
- Pair-level: `raw_integrity` (hash re-verify), `metadata_validity`,
  `footprint_status`, `overlap_status`, `overlap_method`, `overlap_reason`,
  `validation_status` (`VALID` | `INVALID` | `OVERLAP_UNCONFIRMED`),
  `validation_errors`, `warnings`, and a `crop.status = NOT_COMPUTED` block
  that explicitly refuses to fabricate crops.
- Persisted per pair under `data/metadata/m2_validation/<pair_id>.json`
  (atomic replace). `m2_status()` aggregates gates + validation counts.

### 2.3 Deterministic, logged preprocessing (`backend/app/processing/service.py`)
- `prepare(..., stop_after="preprocessing")` ends the run truthfully in state
  `PREPROCESSING` (`mode="preprocess_only"`, `stopped_after` recorded); overlap
  and crop stages are never silently skipped or faked.
- Every run writes `preprocessing_ops.json` (per-product `read`,
  `invalid_mask`, `display_normalize` ops with parameters + input/output
  shape & dtype) and records a `preprocessing` provenance block in the
  manifest. `matcher_readiness` stays `None` for preprocess-only runs.

### 2.4 API
- `POST /api/data/validate` — run + persist M2 pair validation.
- `GET /api/data/m2-status` — aggregate validation/gate/preprocess status.
- `POST /api/pairs/{pair_id}/overlap` — structural recompute + persist.
- `POST /api/pairs/{pair_id}/preprocess` — preprocess-only PREPARE run.
- Thin handlers reuse `api/router.py` (data + pairs namespaces).

### 2.5 Frontend (`frontend/src/pages/Data.jsx`)
- M2 column + badges in the Registered Pairs table; header counts from
  `/api/data/m2-status`.
- Pair inspection gains an **M2 validation card** (raw integrity, metadata
  validity, footprint/binary/preprocessing/op-log cells, overlap method +
  reason, warnings) with "Run M2 validation", "Recompute overlap" and
  "Preprocess only" actions.
- Fixed a latent runtime bug: `PairInspection` used `canMutate` without
  binding it (adds `useAuth()`).

## 3. Verification (software/structural)
- `pytest tests/test_m2_realdata.py` — **22 passed**.
- `pytest tests/test_m1.py tests/test_m1_realdata.py tests/test_m2.py tests/test_m2_realdata.py tests/test_m12.py` — **119 passed**.
- Coverage groups: PDS4 identity, binary consistency (PASS/FAIL/WARNING),
  metadata extraction, malformed XML, sensor honesty when label missing,
  bbox intersection, disjoint, missing-footprint, first-class
  OVERLAP_UNCONFIRMED, polygon positive-area path + degenerate fallback,
  crop-not-fabricated, deterministic logged preprocessing, raw immutability,
  gate classification + aggregate status, API success/error/blocked, M1
  regression smoke, empty-root honesty.
- Frontend `npm run build` clean (vite 7).

## 4. Bugs found & fixed during the hunt
1. `_clip_polygon` assumed a counter-clockwise clip polygon; a clockwise
   footprint polygon emptied the intersection (silently disabling the polygon
   method). Fixed by normalizing clip orientation; regression test added.
2. My first-party drafting error: a stray `clip.close` line in `_clip_polygon`
   (would have raised `AttributeError` on a list) — removed before delivery.
3. Frontend `canMutate` unbound inside `PairInspection` (latent ReferenceError
   on opening a pair) — fixed with `useAuth()`.
4. Test-arena errors corrected: truncated-file registration refusal reflected
   in the test flow, dtype string (`>u2`), `/api` prefix on validate posts.

Remaining honest limits (not bugs): no real ground geometry ⇒ no crop;
`OVERLAP_UNCONFIRMED` for disjoint boxes (preserves M1 semantics); label-less
or malformed-label products report WARN/INVALID rather than being repaired.

## 5. Artifacts
- `backend/app/processing/validation.py` (new)
- `backend/app/pairs.py`, `backend/app/processing/service.py` (modified)
- `backend/app/api/data.py`, `backend/app/api/pairs.py` (modified)
- `tests/test_m2_realdata.py` (new, 22 tests)
- `frontend/src/pages/Data.jsx` (M2 UI)
- `reports/M2_REAL_DATA_PROGRESS.md` (this file)

## 6. Blocked item (operator)
Genuine `.img`+`.xml` under `data/raw/ohrc` and `data/raw/tmc2` are still
absent. On copy:
```
.\.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data
```
then re-run `POST /api/data/validate`, overlap/preprocess, and the real-data
report chain (REAL-DATA EXECUTION flips from BLOCKED to DONE only with real
files; fixture-derived results are structure-validation only).

## 7. Scientific limitations
- No crop was generated for real pairs (no trustworthy ground geometry) and
  none was invented; disjoint boxes stay UNCONFIRMED.
- `preprocessing_ops` are logical (mask + display normalization flagged
  `radiometric_status=NOT_APPLICABLE`); never presented as radiometric truth.
- All structural numbers (areas, windows) are geometric bookkeeping in
  degrees² — not meters, not calibration.

## 8. Final state
**DONE** (M2 tooling + structural validation), **BLOCKED** (real PRADAN execution).

---

**Milestone:** M2
**STATUS:** TOOLING/STRUCTURAL VALIDATION DONE — REAL-DATA EXECUTION BLOCKED_PENDING_OPERATOR_DATA
**VERIFIED-ON:** 2026-09-21
**NEXT:** operator copies real files → activate → run real-data validation/preprocess → report.