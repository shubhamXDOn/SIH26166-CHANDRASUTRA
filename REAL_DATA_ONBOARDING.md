# CHANDRASUTRA — Real-Data Onboarding (PATH A)

How official Chandrayaan-2 imagery (OHRC × TMC-2 from ISSDC PRADAN) moves the
system from the frozen **PATH B · SYNTHETIC_DATA_ONLY** engineering proof to a
real-data (**PATH A**) scientific validation. This document is the operational
playbook for opening the real-data gate — it is not a shortcut: every stage in
the pipeline reports its real state, and `BLOCKED` on missing data is an honest,
first-class outcome.

---

## 1. The gate

At evidence-freeze time the system decides between:

- **PATH A — REAL_DATA** : certified official products are registered and every
  later stage runs on them.
- **PATH B — SYNTHETIC_DATA_ONLY** : only TEST_FIXTURE (synthetic correlated)
  pairs are available; all real-data stages honestly report BLOCKED/empty and
  the freeze carries `SYNTHETIC_DATA_ONLY`.

Current release state: **PATH B**. No result in PATH B is labelled as real
lunar validation, and none is.

## 2. Prerequisites

1. An approved official account on ISSDC **PRADAN** (Chandrayaan-2).
2. Credentialed access to download OHRC and TMC-2 products for a common scene
   (near-coincident acquisition geometry).
3. A certified reference dataset if you intend to claim physical registration
   accuracy — without one, the system reports `reference_dataset_status:
   NOT_AVAILABLE` and metrics will never claim physical accuracy.

## 3. Steps

### 3.1 Obtain and stage products

```
data/raw/
  <product_a_ohrc>/      # ISRO product id, e.g. urn:isro:ch2:ohrc:...
    *.img
    *.xml                # PRODUCT metadata (filename identifiers stay intact)
  <product_b_tmc2>/
    *.img
    *.xml
```

- Keep product IDs and filenames verbatim; the pipeline relies on them for
  identity and later determinism.
- Never modify, re-encode or relabel the `.img`/`.xml` files. Raw files are
  immutable by policy and their SHA-256 is recorded at registration.

### 3.2 Register the pair

In the **Data** workspace (or via `/api/data`), register the pair that pairs
the OHRC product with the TMC-2 product. Registration:

1. Records product metadata (sensor, date, footprint, GSD).
2. Records the raw `sha256` of every file (this is what the independent audit
   re-computes at evidence time).
3. Validates metadata completeness and consistency.

### 3.3 Admin flow

Real-data registration requires authenticated admin flow. The system never
simulates this step; if no real pair is registered the tree reports 0 products
for real-data stages.

### 3.4 Run the real pipeline

From the **Analysis** workspace, in order (each stage is gated by the previous):

| Stage | Milestone | Gate on | Honest output |
| --- | --- | --- | --- |
| PREPARE + condition analysis | M2 | valid pair + overlap | sensor-native tiles, no resampling |
| Candidate correspondences | M3 | M2 tiles | candidate list as observations |
| Trust Gate | M4 | M3 candidates | per-tile GEOMETRIC verification decisions |
| Spatial reliability + selection | M5 | TRUSTED evidence | reliability grid + selected evidence |
| Verified registration | M6 | M5 selection | transform + validation + diagnostics |
| Metrics + report | M7 | M6 transform | reproducible experiment report |

### 3.5 Establish the reproducibility + evidence freeze

1. Run the pipeline a second and third time on the same pair to perform the
   reproducibility run (RUN A/B/C must produce identical signatures — same
   funnel, same transform matrix hash, same report hash).
2. Provide a certified reference dataset, then set `reference_dataset_status`
   to `AVAILABLE`; only then may physical-accuracy statements be attached.
3. Freeze the experiment (M12 evidence workflow) to produce a PATH A package:
   real gate, real audit recomputation over the real hashes, real provenance
   chain, new `FINAL_EVIDENCE_SHA256`, new configuration fingerprint chain.
4. Re-seed the app with the new package and re-run the release regression.

## 4. What must NOT be done

- ❌ Label PATH B outputs as mission results.
- ❌ Fabricate hashes for artifacts that do not exist (provenance stays
  PARTIAL/HOLD until real artifacts exist).
- ❌ Claim physical accuracy without a certified reference dataset.
- ❌ Reuse the PATH B `FINAL_EVIDENCE_SHA256` or configuration fingerprint for
  a PATH A package — the digest and fingerprint are identities of the frozen
  artifact set and must be recomputed honestly.

## 5. Expected status after successful PATH A onboarding

```
REAL_DATA            AVAILABLE (n real pair(s))
REFERENCE             AVAILABLE          (only for the certified reference)
GATE                 PATH A · REAL_DATA
REPRODUCIBILITY      REPRODUCIBLE (if RUN A/B/C agree on the real pair)
PROVENANCE           COMPLETE (real M8/M9 runs available)
VERIFY               VERIFIED on the new digest
```

If any of these cannot be achieved honestly (e.g. reference unavailable), the
release continues but with the corresponding status reported truthfully — the
system was built so that a truthful abstention is always an acceptable result.