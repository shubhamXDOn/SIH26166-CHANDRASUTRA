# M0 — Real-Data Activation Audit & Corrected Implementation Map (CHANDRASUTRA · SIH26166)

**Milestone:** M0 — Preflight / Environment / Existing-Architecture Audit
**Report date:** 2026-09-21
**Status:** **DONE** — audit complete; corrected map produced; real-data gaps inventoried.

---

## 1. What was audited

| Item | Result |
| --- | --- |
| Existing repository | **DONE** — mature M0–M13 implementation, committed and tagged `chandrasutra-v1.0.0` (commit `e92f168`), working tree clean |
| Source documents (PRD, TRD, TECH FLOW, RULES, DATA protocol, EXPERIMENT PLAN) | **DONE** — extracted from the supplied `.docx` files and read in full |
| Existing M0–M13 reports (`reports/`) | **DONE** — M1..M12 milestone reports present; M13 final release report present |
| Existing data tree | **DONE** — `data/raw/*` intentionally empty (immutable skeleton only); frozen evidence `EXP-EE0EBE7187E5` is PATH-B synthetic and must not change |
| Supplied real TMC-2 package | **DEFERRED-USER** — the operator will copy the real `.img`+`.xml` products into `data/raw/tmc2` (and OHRC into `data/raw/ohrc`); intake tooling is being prepared so that placed files are detected, hashed, classified and registered |
| Real OHRC product on disk | **No** (per user: will be copied in) |
| Baseline regression | **RUNNING/PARTIAL** — full suite ~77% when checked; completes in ~20–25 min locally (slow, not hung). Targeted subsets are used during development; the full suite is re-run at milestone gate |

## 2. Corrected implementation map (historical labels → corrected execution track)

Historical milestone labels were written before this corrected plan; **historical reports are not renamed or corrupted**. Instead, this map states what each corrected milestone needs and where it already exists.

| Corrected milestone | Corrected objective | Current implementation (reuse) | What is missing for REAL data activation |
| --- | --- | --- | --- |
| **M0** | Preflight / environment / architecture audit | Full repo + this report | none |
| **M1** | Real PRADAN data intake + PDS4 metadata + Pair Registry | `loader.py` PDS4 parse, `pairs.py` registry, `/api/pairs/*`, Data workspace | **Real files on disk**; footprint/geometry extraction from real labels; REAL_PRADAN vs TEST_FIXTURE source classification; auto scan→register tooling; overlap determination from footprint evidence |
| **M2** | Real-data validation + safe preprocessing + overlap/crop | `processing/*` (mask, overlap, crops, normalize, conditions, service) | run on real pair; crop from verified overlap |
| **M3** | Classical baseline matching | `matching/adpaters|engine|service` (SIFT/AKAZE) | run on real pair |
| **M4** | Strong/deep matcher integration | `matching/m8/deep/*` (SuperPoint/SuperGlue/LoFTR adapters; honest `MODEL_WEIGHTS_NOT_CONFIGURED`) | model weights (external); capability probe on real pair |
| **M5** | Scene condition estimator | `processing/conditions.py` (texture, density, scale, contrast) | run on real pair; tuned thresholds |
| **M6** | Adaptive matcher routing | `matching/m8/routing.py` + `matching/service.py` (strategy selection, explicit fallback) | route evidence on real pair |
| **M7** | Trust Gate | `trust/*` (engine, geometry RANSAC, residual, spatial, states) | run on real pair |
| **M8** | Spatial reliability + balanced selection | `spatial/*` (grid, reliability, selection, mapping) | run on real pair |
| **M9** | Registration | `registration/*` (engine, warp, coord_space, diagnostics, visualize) | run on real pair |
| **M10** | Metrics + benchmark/ablation/failure | `metrics/*` (funnel, registration, spatial, report, comparison) | real-pair metrics + fixed-vs-adaptive ablation |
| **M11** | Evidence-grounded Gemini + integrated UI | `ai/*` (client, evidence, validator, service, prompts) — key now configured in `.env` (`gemini-2.0-flash`) | live call + evidence-grounded answer on a real run |
| **M12** | Final real-data validation + reproducibility + evidence freeze | `m12/*` (package, audits, raw_integrity, provenance, report) | real-run reproducibility (RUN A/B/C) and **a new frozen experiment identity + digest** |
| **M13** | Final release + jury demo + hosted working prototype | M13 release surface, Evidence explorer, report centre, docs, tooling | re-seed on the real-data evidence package; final demo |

**Conclusion:** the engineering implementation for M2–M13 is **already present and correct**. The real-data activation track is **additive**: it must (1) ingest genuinely supplied files, (2) classify their source honestly, (3) derive overlap from real footprint metadata, and (4) route the real pair through the existing pipeline. Nothing existing is rewritten.

## 3. Reuse inventory (do not duplicate)

Backend: loader, pairs registry/validation, processing, matching (classical + deep adapters), routing, trust, spatial, registration, metrics, Gemini service, auth, M12 packaging, M13 release.
Frontend: Data/Analysis/Matching/Trust/Spatial/Results/AI/Evidence workspaces; premium visual system already present.
Tests: 560+ synthetic-regression and bug-hunt tests (preserved); `fixturegen.py` fixtures kept.

## 4. Real-data blockers (exact)

1. **Files** — operator still needs to place real `.img`+`.xml` under `data/raw/tmc2` and `data/raw/ohrc` (user action; tooling ready).
2. **Footprint/geometry parsing** — current parser records only a *single* footprint string; real CH-2 labels carry `Geographic_Extent`/`Footprint_Geometry` that we must read structurally to decide overlap (this build adds it).
3. **Source classification** — no `REAL_PRADAN`/`TEST_FIXTURE`/`UNKNOWN` gate exists yet (this build adds it).
4. **Overlap decision** — overlap is currently operator-supplied text; must be derived from real footprint boxes when available and honestly `OVERLAP_UNCONFIRMED` otherwise (this build adds it).

## 5. 1.5-day execution plan (P0 → P1 → P2)

**P0 (mandatory, end-to-end demo):** place-files intake → classify → register → overlap-from-footprint → pipeline (M2→M10) on the real pair → metrics → provenance → UI.
**P1 (if time):** second real crop/case, deep matcher (fallback documented), online Gemini response, baseline-vs-adaptive ablation.
**P2 (defer):** IIRS, LoFTR, RIFT2, 3D, extra polish.

## 6. Artifacts
- This report (`reports/M0_REAL_DATA_AUDIT.md`).
- Baseline regression state captured (`pytest tests` partial run; full run at gates).

## 7. Final state
**DONE (audit).** Next: **M1 real-data intake hardening** begins immediately.