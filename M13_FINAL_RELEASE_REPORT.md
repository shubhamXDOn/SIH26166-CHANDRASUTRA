# CHANDRASUTRA — M13 Final Release Report

**Project:** SIH26166 · Trustworthy Lunar Image Intelligence
**Release candidate:** CHANDRASUTRA **v1.0.0** (engineering build `0.11.0`)
**Report date:** 2026-09-20
**Suggested tag:** `chandrasutra-v1.0.0` (pending the maintainer's go-ahead for the commit/tag)

> **What this release is and is not.** It is a completed, deterministic,
> evidence-frozen engineering proof, packaged for jury presentation. It is
> **not** claim-of-validated real lunar-mission analysis: real OHRC×TMC-2 data
> remains BLOCKED on official PRADAN access, and nothing in this release is
> fabricated or presented as such.

---

## 1. Executive summary

All M0–M12 engineering milestones are complete and frozen. M13 delivers the
jury-facing release surface: an aggregate release-status API, an evidence
explorer, a report centre, honest measurements, a non-destructive demo reset,
the documentation set, release tooling and a 40-case bug-hunt corpus. The full
regression is green:

| Gate | Result |
| --- | --- |
| Full backend test suite (`pytest tests`) | **561 passed / 0 failed / 0 errored** (17 files) |
| M13 bug-hunt corpus (`tests/test_m13.py`) | **40 / 40 passed** (B01–B40) |
| M12 evidence suite | 37 / 37 passed |
| Environment smoke (`python smoke_test.py`) | **101 checks / 101 passed** |
| Frontend build | PASS (356.89 kB JS / 94.23 kB gzip) |
| Frontend SSR smoke | PASS (18 pages, incl. Overview + Evidence) |
| Docker Compose config | VALID |

## 2. Frozen evidence record (must not change)

| Field | Value |
| --- | --- |
| Frozen experiment | `EXP-EE0EBE7187E5` (pair `CS-P001`, 29 artifacts) |
| `FINAL_EVIDENCE_SHA256` | `c8fbab19dee75ce92870755bdf5202ad1402ee97166a8bdbfc3db8dfd7557e37` |
| Configuration freeze fingerprint | `9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce` |
| Fingerprint recomputed == recorded | **True** (no drift) |
| Evidence verify status | `VERIFIED` (re-verified: seeded, per-request, on every demo reset, and in tests B08/B16/B27/B40) |
| Gate decision | **PATH B · `SYNTHETIC_DATA_ONLY`** (TEST_FIXTURE pair) |
| Independent audit | `VERIFIED` (raw-integrity recomputation) |
| AI cross-check | `CLEAR` · 0 violations |
| Security scan | `CLEAN` |
| Provenance chain | M1–M7 `COMPLETE` with recorded configuration ids + hashes; **M8/M9 `NOT_RUN`** (honest, no fabricated artifacts) → overall `INCOMPLETE` (presented as **PARTIAL · HOLD**) |

## 3. Reproducibility testimony

Same pair + fixed configuration ids rerun three independent times:

| Run | Funnel M3→M6 | Transform matrix hash | Report hash | Fingerprint |
| --- | --- | --- | --- | --- |
| A | 100 → 84 → 19 → 19 | `2d84fa01…c2bc1b` | `21e9be44…64034a` | `9b2a2f7c…` |
| B | 100 → 84 → 19 → 19 | `2d84fa01…c2bc1b` | `21e9be44…64034a` | `9b2a2f7c…` |
| C | 100 → 84 → 19 → 19 | `2d84fa01…c2bc1b` | `21e9be44…64034a` | `9b2a2f7c…` |

Result: **REPRODUCIBLE** — 0 drifted subjects, 0 recompute mismatches.

## 4. Honest status matrix (present this, not better numbers)

| Question | Answer |
| --- | --- |
| Are results fabricated? | **No.** `RELEASE_NOTES.md` · banned-phrase scan enforced by M12 cross-check. |
| Is this validated on real lunar imagery? | **No — PATH B synthetic**; acquisition blocked (see §5). |
| Is physical registration accuracy claimed? | **No** — reference dataset `NOT_AVAILABLE`, accuracy `NOT_CLAIMED`. |
| Is provenance fully complete? | **PARTIAL · HOLD** — M1–M7 complete; M8 deep-matcher run and M9 AI evidence packet honestly `NOT_RUN`/`NOT_AVAILABLE`. |
| Is hosted latency measured? | **No — `NOT_MEASURED`** (no public deployment provisioned here; not estimated). |
| Does demo mode fanfare override honesty? | No — the Overview shows an explicit “synthetic demonstration — not a real observation” marker. |

## 5. Real-data gate (PATH A) — still blocked, and why

| Item | Status |
| --- | --- |
| Official account | awaiting ISSDC **PRADAN** (Chandrayaan-2) approval |
| Real pair registration | BLOCKED (no credentialed products in this environment) |
| Reference dataset | NOT_AVAILABLE |
| Consequence | system reports `real_data: BLOCKED`, gate PATH B, physical accuracy NOT_CLAIMED — consistently, in the API, the UI and the reports |

The onboarding playbook is `REAL_DATA_ONBOARDING.md`; the moment a certified
pair + reference exist, the gate is re-run and a new package frozen (new digest
and fingerprint, never hand-me-downs from PATH B).

## 6. Performance measurements (honest, local)

Measured locally, authenticated TestClient, one warm-up call per route then 4
samples (`perf/m13_performance.json`, `measured_at_utc
2026-09-20T12:38:15+00:00`):

| Route | Median | Min | Max |
| --- | --- | --- | --- |
| GET /api/health | 15.6 ms | 13.8 | 16.8 |
| GET /api/m13/status | 157.2 ms | 146.5 | 261.7 |
| GET /api/m13/evidence | 108.1 ms | 69.9 | 147.8 |
| GET /api/m13/evidence/{exp} | 177.2 ms | 83.5 | 246.3 |
| GET /api/m13/reports | 42.4 ms | 41.1 | 45.1 |
| GET /api/m13/report/{name} | 37.7 ms | 32.8 | 40.7 |
| GET /api/m13/record/reproducibility | 40.9 ms | 39.6 | 158.3 |
| GET /api/m13/provenance | 56.6 ms | 34.6 | 131.0 |
| POST /api/m13/demo/reset | 86.6 ms | 78.1 | 98.2 |

Hosted latency: **NOT_MEASURED** — never estimated.

## 7. Regression record

`perf/m13_regression.json` holds the honest per-file breakdown captured at run
time (pytest JUnit output). Highlights: test_m1 28, test_m2 18, test_m3 25,
test_m4 34, test_m5 67, test_m6 83, test_m7 47, test_m8 13, test_m9 68,
test_m10 31, test_m11 42, test_m12 37, test_m13 40, plus config/backend/
dirs/security suites — **561 total, 0 failures, 0 errors, 0 skipped**.

## 8. M13 bug-hunt findings (B01–B40)

The 40-case corpus validated the release surface and caught **two genuine
defects**, both fixed:

1. `/api/m13/status` read reproducibility status from the record's top level
   instead of unwrapping `evidence.status` → status was `null`. Fixed and
   covered by B12.
2. `/api/m13/status` raised `AttributeError` on a data root without a
   reproducibility record (fresh deploy) → 500. Fixed (graceful
   `None`/`NOT_AVAILABLE`) and covered by B37.

Corpus coverage: auth 401s (B01–B04), status aggregation incl. fingerprint
stability under release-flag overrides (B05–B14), evidence explorer with
tamper detection + no absolute paths (B15–B20), report-centre traversal
protection (B21–B25), provenance honesty + non-destructive reset +
measurements (B26–B30), robustness: deterministic JSON, structured errors,
secret hygiene, multi-client consistency, empty-root grace, namespace
convention (B31–B40).

## 9. Reproduce this report

```bash
python scripts/m13_release_prep.py --data-root data   # seed frozen evidence + re-verify
python scripts/m13_perf.py --data-root data           # local timings (hosted NOT_MEASURED)
python scripts/m13_ppt_assets.py --data-root data     # real-number SVG assets
python scripts/m13_manifest.py --data-root data       # release_manifest.json
pytest tests -q                                       # 561/561
python smoke_test.py                                  # 101/101
npm run build && node frontend/ssr-smoke.mjs          # frontend + SSR
docker compose config -q                              # compose validity
```

## 10. Release artefacts delivered by M13

- Backend: `backend/app/api/m13.py` (+ registration in `backend/app/api/router.py`);
  Settings gained presentation-only `release_version="1.0.0"` / `release_milestone="M13"`
  (never part of the frozen fingerprint — verified by B07/B39).
- Frontend: `frontend/src/pages/Evidence.jsx`; release landing band on
  `Overview.jsx`; nav + `Icon.File` in `ui.jsx`; SSR smoke extended.
- Tooling: `scripts/m13_release_prep.py`, `scripts/m13_perf.py`,
  `scripts/m13_manifest.py`, `scripts/m13_ppt_assets.py`.
- Docs: `DEPLOYMENT.md`, `REAL_DATA_ONBOARDING.md`, `RELEASE_NOTES.md`.
- Records: `release_manifest.json`, `perf/m13_performance.json`,
  `perf/m13_regression.json`, `reports/assets/*.svg`, `tests/test_m13.py`.

## 11. Verdict

**RELEASE CANDIDATE v1.0.0 IS READY.** All automated gates are green and the
scientific honesty contract holds: every real-data-relevant stage reports its
true BLOCKED/NOT_AVAILABLE/NOT_RUN state, and the frozen evidence digests are
re-verified clean at every layer the release exposes.

Next step (maintainer decision): commit the release snapshot and tag
**`chandrasutra-v1.0.0`**; then optionally build/run the Docker stack with a
true `.env` and present via the Evidence page.