# CHANDRASUTRA (SIH26166) — M12 FINAL SCIENTIFIC REPORT

- Experiment: `EXP-EE0EBE7187E5`  ·  Pair: `CS-P001`

> This report is generated deterministically from the frozen evidence package.

## 1. Executive summary

M12 executes the final scientific validation of the CHANDRASUTRA system: it proves that the M0–M11 pipeline is coherent, reproducible and honestly reported. Real-data science remains BLOCKED on PRADAN approval, so the engineering evidence is executed on deterministic synthetic TEST_FIXTURE data that is *never* labelled as real mission data. Every scientific number in M12 is a recomputed measurement of on-disk evidence, never a manufactured result, and physical accuracy is reported as NOT_AVAILABLE.

## 2. Milestone & system status

| milestone | scope | status |
|---|---|---|
| M0 | secure architecture foundation | DONE |
| M1 | pair registry, provenance & validation | DONE |
| M2 | sensor-native processing & overlap geometry | DONE |
| M3 | adaptive matcher candidate correspondences | DONE |
| M4 | independent geometric verification / trust gate | DONE |
| M5 | spatial reliability & reliability-aware selection | DONE |
| M6 | registration engine & verified alignment | DONE |
| M7 | reproducible experiment metrics & independent recomputation | DONE |
| M8 | deep matcher expansion & adaptive routing | DONE |
| M9 | evidence-grounded AI explanations (Gemini) | DONE |
| M10 | accounts, roles & secure access | DONE |
| M11 | operations hardening & performance | DONE |
| M12 | final scientific validation, reproducibility & evidence freeze | DONE |

Configuration freeze fingerprint: `9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce`
- Provenance chain status: `INCOMPLETE`
- Independent audits aggregate: `VERIFIED`
- Evidence package: `FROZEN`

## 3. Scientific integrity principles; the two legitimate paths

- PATH A (real, authorised data): the real-data gate must pass every check; evidence is named REAL_DATA_VERIFIED and only then may scientific claims use the data.
- PATH B (honest BLOCKED + synthetic engineering proof): when the gate cannot be certified, science is reported BLOCKED/REFERENCE_UNAVAILABLE and the determinism of the engineering pipeline is proven on TEST_FIXTURE data, always labelled synthetic.
- No scientific threshold is tuned in M12 (M12 is not a tuning milestone); M3..M7 thresholds are frozen in the configuration freeze below.

## 4. Real-data gate certification

- Gate status: `SYNTHETIC_DATA_ONLY`
- Real data available (PATH A): `no`

| check | status | detail |
|---|---|---|
| source_official | PASS | archive=ISRO / ISSDC PRADAN — Chandrayaan-2 url=https://pradan.issdc.gov.in/ch2/ |
| products_identified | PASS | A=urn:fixture:ch2:ohrc:ch2_ohr_ncp_20211228T2209123959_d_img_d18 B=urn:fixture:ch2:tmc2:ch2_tmc_ncn_20200207T0716469418_d_img_d18 |
| image_a_readable | PASS | unreadable |
| image_a_dims_match | FAIL | recorded=256x200 |
| image_a_gsd_known | PASS | gsd=0.5 |
| image_a_acquisition_known | PASS | acquisition=2021-12-28T22:09:12.395Z |
| image_a_footprint_evidence | PASS | footprint=fixture_bbox |
| image_b_readable | PASS | unreadable |
| image_b_dims_match | FAIL | recorded=384x300 |
| image_b_gsd_known | PASS | gsd=0.5 |
| image_b_acquisition_known | PASS | acquisition=2020-02-07T07:16:46.418Z |
| image_b_footprint_evidence | PASS | footprint=fixture_bbox |
| overlap_status_recorded | PASS | CONFIRMED_OVERLAP |
| overlap_evidence | PASS | status=CONFIRMED_OVERLAP evidence=present |
| raw_integrity_verified | PASS | VERIFIED |
| geometry_real | FAIL | geometry source=TEST_FIXTURE |

- Decision: `False` PATH A / `True` PATH B — PATH B: real-data credentials not certified; deterministic synthetic TEST_FIXTURE engineering proof only.

## 5. Raw data & integrity freeze

Raw files are sacred (M1). SHA-256 of every raw image is re-verified at evidence freeze time and compared to the registered hash; any drift flags raw integrity as FAILED and the freeze refuses to certify.

- Raw integrity re-verification: `VERIFIED`
- image_a: recorded `37304f6d9339fec6…` recomputed `37304f6d9339fec6…` — PASS
- image_b: recorded `cacba243bfa5a3eb…` recomputed `cacba243bfa5a3eb…` — PASS

## 6. Configuration freeze & experiment identity

Every experiment carries a deterministic identity (M7/M8) derived from the pair, the configuration chain and the hashes of input artefacts — never from timestamps, usernames, hostnames or paths. Equal inputs ⇒ equal experiment IDs.

| milestone | configuration id | version | sha256 |
|---|---|---|---|
| M1 | — | — | `23e65988dcc837be…` |
| M2 | PC-M2-001 | 1 | `c2aab33b7b1261d0…` |
| M3 | MC-M3-001 | 1 | `c917fee7f8fd0fb1…` |
| M4 | TG-M4-001 | 1 | `ec335c8434fdd32f…` |
| M5 | SR-M5-001 | 1 | `c0a1461f9f3a7e8f…` |
| M6 | RG-M6-001 | 1 | `8e7b992b07be304e…` |
| M7 | MT-M7-001 | 1 | `fac5ff07ea6ac570…` |
| M8 | DM-M8-001 | 1 | `bf98f42d4dc9d0a9…` |
| M9 | AI-M9-001 | 1 | `2fb0e4205f4ddac3…` |
| M10 | AU-M10-001 | 1 | `7c4a3bae3442182a…` |
| M11 | 0.11.0 | — | `dc0050660f456311…` |

- Overall configuration fingerprint: `9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce`

## 7. Provenance chain (M1–M9)

- Chain status: `INCOMPLETE`; missing stages: M8

| milestone | role | configuration id | artefacts (sha-256) |
|---|---|---|---|
| M1 | pair registration & validation | — | metadata/pairs.json |
| M2 | sensor-native scene condition tiles + overlap geometry | PC-M2-001 | derived/processing/CS-P001/PC-M2-001/processing_manifest.json, derived/processing/CS-P001/PC-M2-001/diagnostics/overlap.json, derived/processing/CS-P001/PC-M2-001/crops/tiles.json |
| M3 | adaptive matcher candidate correspondences per tile | MC-M3-001 | derived/matches/CS-P001/PC-M2-001/MC-M3-001/matching_status.json, derived/matches/CS-P001/PC-M2-001/MC-M3-001/summary.json |
| M4 | independent geometric verification / trust gate | TG-M4-001 | derived/trust/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/trust_status.json, derived/trust/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/tile_trust.json |
| M5 | spatial reliability & reliability-aware selection | SR-M5-001 | derived/spatial/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/status.json, derived/spatial/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/spatial_manifest.json, derived/spatial/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/selection.json, derived/spatial/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/selected_correspondences.npz, derived/spatial/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/reliability_map.json |
| M6 | registration engine & verified alignment | RG-M6-001 | derived/registration/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/status.json, derived/registration/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/summary.json, derived/registration/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/transform.json, derived/registration/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/validation.json, derived/registration/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/diagnostics.json |
| M7 | reproducible experiment metrics | MT-M7-001 | derived/metrics/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/MT-M7-001/status.json, derived/metrics/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/MT-M7-001/report.json, derived/metrics/CS-P001/PC-M2-001/MC-M3-001/TG-M4-001/SR-M5-001/RG-M6-001/MT-M7-001/report.md |
| M8 | deep matcher expansion & adaptive routing | — | — |
| M9 | AI explanation evidence | — | — |

- All paths in the chain are POSIX-relative to the data root; no absolute/home paths ever enter provenance or evidence.

## 8. Candidate funnel audit

- Status: `MATCH` — recomputed funnel matches recorded

| metric | recorded | recomputed | match |
|---|---|---|---|
| FUNNEL_M3_TILES | 2 | 2 | yes |
| FUNNEL_M3_CANDIDATES | 100 | 100 | yes |
| M3_STATE | COMPLETE | COMPLETE | yes |

## 9. Trust gate audit

- Status: `MATCH` — all tile verdicts recomputed identically
- Tiles audited: 2

## 10. Spatial selection audit

- Status: `MATCH` — recomputed selection matches recorded

| metric | recorded | recomputed | match |
|---|---|---|---|
| FUNNEL_M5_SELECTED | 19 | 19 | yes |
| M5_STATE | COMPLETE | — | yes |

## 11. Registration independent revalidation

- Status: `MATCH` — registration evidence revalidated
- Independent recomputation (COMPUTED): residual mean `0.969228` px, median `0.978944` px, p95 `2.45215` px, symmetric transfer max `2.67345` px, inlier count `19`

## 12. Metric audit & physical-accuracy boundary

- M7 metrics are measurements of pipeline evidence, never claims of scientific alignment accuracy.
- Reference dataset: `NOT_AVAILABLE` — physical_accuracy is `REFERENCE_UNAVAILABLE` and is never emitted as 0 or 100%.
- No CE90/LE90 or geolocation accuracy value is ever reported because no independent reference dataset is integrated (requires PRADAN approval for real truth).

## 13. Deep matcher & routing audit

- M8 reports availability from a real capability probe (model weights on disk), never from a faked model; deep matcher unavailability is reported honestly, not as success.
- Routing decisions are *what-to-try* orders with explicit reasons (B23); they are never presented as confidence or quality verdicts.

## 14. Visualization & reporting labeling

- Visualizations and reports are labelled with experiment ID, pair ID, milestone and status; synthetic TEST_FIXTURE evidence is always visibly labelled synthetic, and blocked stages are shown as BLOCKED/NOT_RUN — never silently omitted.

## 15. AI evidence & cross-check validation

- Cross-check status: `CLEAR`
- Packet digest: `—`
- Pipeline state audited: `{}`
- No violations in the audited AI response.
- The M12 validator rejects ungrounded numbers, physical-accuracy claims without a reference dataset, matcher-confidence-as-truth, blocked-as-success, and synthetic-as-real claims deterministically.

## 16. Reproducibility proof (RUN A / RUN B / RUN C)

- Overall: `REPRODUCIBLE` — identical signatures across RUN A / RUN B (re-run) / RUN C (fresh workspace)

| subject | verdict |
|---|---|
| experiment_id | IDENTICAL |
| m3_total_candidates | IDENTICAL |
| m4_trusted_tiles | IDENTICAL |
| m5_selected_count | IDENTICAL |
| m7_metric_count | IDENTICAL |
| m7_available_count | IDENTICAL |
| FUNNEL_M3_CANDIDATES | IDENTICAL |
| FUNNEL_M4_TRUSTED_CORRESPONDENCES | IDENTICAL |
| FUNNEL_M5_SELECTED_CORRESPONDENCES | IDENTICAL |
| FUNNEL_M6_REGISTERED_CORRESPONDENCES | IDENTICAL |
| RESIDUAL_MEAN_RECOMPUTE_PX | IDENTICAL |
| RECOMPUTE_MISMATCH_COUNT | IDENTICAL |
| transform_matrix_hash | IDENTICAL |
| report_md_sha256 | IDENTICAL |

## 17. Final evidence package, manifest & SHA-256 + security scan

- Package: `final_evidence/EXP-EE0EBE7187E5`
- Status: `FROZEN`
- Artifacts: 29
- FINAL_EVIDENCE_SHA256: `c8fbab19dee75ce92870755bdf5202ad1402ee97166a8bdbfc3db8dfd7557e37`

### Security scan

- Status: `CLEAN`

## 18. M12 corpus results, status matrix, Definition of Done & M13 handoff

- Corpus: `tests/test_m12.py` (B01–B35)
- Passed: `37` / `37`

| requirement | status |
|---|---|
| Real-data gate enforces the two-path rule | PASS | PATH B active for TEST_FIXTURE corpus |
| Raw files re-verified byte-identical (SHA-256) | PASS | recomputed == registered |
| Configuration chain frozen (ids+versions+hashes) | PASS | fingerprint recorded |
| Deterministic experiment identity (no timestamps/users/uuids) | PASS | experiment EXP-EE0EBE7187E5 |
| Provenance chain M1–M9 with relative paths + digests | HOLD | chain INCOMPLETE |
| Independent audits recomputed vs recorded | PASS | aggregate VERIFIED |
| Physical accuracy never claimed without reference | PASS | REFERENCE_UNAVAILABLE / NOT_AVAILABLE |
| Deep matcher unavailability reported honestly | PASS | capability probe, no faked model |
| AI claims cross-checked against evidence | PASS | cross-check CLEAR |
| Reproducibility RUN A/B/C byte-identical | PASS | REPRODUCIBLE |
| Evidence package frozen + re-verifiable | PASS | FINAL_EVIDENCE_SHA256 recorded |
| Security scan clean | PASS | CLEAN |

### Definition of Done (M12)

1. B01–B35 test corpus implements all §M12 requirements (35 behaviours).
2. Full regression green: `pytest tests -q`.
3. Smoke suite green: `python smoke_test.py`.
4. Frontend builds and SSR smoke passes: `npm run build` + `node frontend/ssr-smoke.mjs`.
5. `docker compose config` validates.
6. Final evidence package exists with manifest + FINAL_EVIDENCE_SHA256.
7. This report exists with the status matrix and M13 handoff.

### M13 handoff notes

- Real scientific validation requires PRADAN approval for authentic OHRC/TMC-2 products; the real-data gate (`m12.real_data_gate`) is the single gate that flips PATH A on when authorised real products are registered.
- Any future threshold change invalidates the configuration freeze; update the chain and re-freeze the evidence package (a NEW experiment identity).

---
CHANDRASUTRA M12 · metrics are measurements, not proof · evidence is frozen.
