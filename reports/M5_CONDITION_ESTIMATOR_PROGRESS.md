# M5 — Condition Estimator (pre-matcher pair characterization) — Progress Report

**Milestone:** M5 — deliver a reproducible, evidence-labelled pair-level CONDITION
ESTIMATOR that characterizes M2-validated products (texture/complexity, appearance
distribution, scale/GSD relationship, invalid-mask coverage) and records optional
latest-baseline matcher observations as a SEPARATE, explicitly-labelled section —
BEFORE any matcher selection. This layer never selects, recommends or routes a matcher.
**Report date:** 2026-09-22
**Execution status:** `CASE B (no genuine OHRC/TMC-2 products on disk)`
**M5 TOOLING / STRUCTURAL VALIDATION = DONE** (41 M5 tests + full M1–M13 regression green)
**M5 GENUINE REAL-DATA CONDITION ESTIMATION = BLOCKED_PENDING_OPERATOR_DATA**

---

## 1. Objective
Add a pre-matcher **condition-estimator** layer that turns validated M2 products
(`READY_FOR_MATCHING`) into a deterministic, per-pair condition dossier: per-side
intrinsic image condition (texture energy, edge density, Laplacian variance, entropy,
robust intensity statistics, invalid-mask coverage / classification bins) plus the
pair relationship (appearance histogram distance, recorded scale/GSD relationships,
native/effective scale gap). All values are factual, deterministic observations with
explicit thresholds recorded in every artifact. The layer is a prerequisite for the
later Trust Gate (scientific milestone) — it is **not** a matcher and performs **no**
selection/routing/confidence.

## 2. Execution statuses
| Item | Status |
| --- | --- |
| M5 configuration + package + service + API + frontend | `DONE` |
| M5 structural/integration validation (41 M5 tests + M1–M13 regression) | `DONE` |
| M5 genuine real-data condition estimation | `BLOCKED_PENDING_OPERATOR_DATA` |
| Configuration of record | `CE-M5-001` (version 1, `scientifically_tuned: false`) |

## 3. Honesty rules honoured
- **Determinism:** fixed-stride window sampling with a recorded seed; fixed input +
  fixed configuration + fixed libraries ⇒ identical metrics (verified run-to-run at
  metric and full-artifact level).
- **No fabrication:** blocked states are persisted as artifacts with stable codes
  (`PROCESSING_NOT_RUN`, `PROCESS_NOT_READY`, `PRODUCT_MISSING`, `REAL_DATA_BLOCKED`,
  `CONDITION_ESTIMATION_FAILED`), never simulated as SUCCESS.
- **Never selects a matcher:** payloads are scan-rejected (case-insensitive) for
  `selected_matcher / recommended_matcher / best_matcher / routing_decision /
  confidence`; `scientifically_tuned` is always `false`.
- **GSD honesty:** GSD comes only from recorded geometry/PDS4 label products
  (`RECORDED_GEOMETRY`, `NOMINAL_SENSOR`, `PDS4_LABEL`); when absent it is stored as
  `UNKNOWN` — never inferred from pixel counts.
- **Reference-frame honesty:** a morning-overlap × afternoon-overlap pair records GSD
  as `side_a_gsd / side_b_gsd` with a factual `gsd_ratio_relationship` and
  `gsd_ratio_factual_label`; no assumed swap, no normalized winner.
- **Unique-pixel statistics:** overlapping windows pool each examined valid pixel
  exactly once, so pooled percentiles/entropy/histograms reflect the actual examined
  distribution (a naive concatenation would double-count overlap-boundary pixels).

## 4. Configuration (CE-M5-001)
- New `m5_condition:` section in `configs/app.yaml` (id CE-M5-001, version 1,
  `derived_rel: metadata/m5_condition`); `_M5C_DEFAULTS` + `m5_condition_config()` in
  `backend/app/config.py` (cached, YAML fallback, deep-merge).
- Execution snapshot recorded in every artifact: `window_size_px 256`,
  `stride_px 128`, `seed 20260922`, `max_windows 1024` (stride grows ×2 to bound),
  Sobel ksize 3, Laplacian ksize 3, Canny 50/150 aperture 3, `histogram_bins 64`,
  robust percentiles, and explicit ordinal `low_lt / high_ge` thresholds per
  classification key (`textural_complexity` on `laplacian_variance`,
  `dynamic_range` on `p95_minus_p5_dn`, `invalid_fraction`).

## 5. Sampling plan (recorded, deterministic)
Every artifact records `sampling.method fixed_stride_grid`, `window_size_px`,
`stride_used_px`, `seed_recorded`, `windows_total`, `pixels_examined_aggregate`,
`pixels_total`, `sample_fraction` (capped at 1.0) + an overlap note. On the correlated
fixture: side A 1,160,064 / side B 1,210,944 examined pixels, fraction 1.0, 30 windows
each.

## 6. Metric set
- **Texture (unit-scaled plane u16/65535):** `gradient_energy_mean_mag_sq`,
  `laplacian_mean`, `laplacian_variance`, `canny_edge_fraction`,
  `canny_edge_pixels`, kernel sizes, `texture_metrics_unit` recorded.
- **Appearance (raw DN):** entropy bits, `is_constant_layout`, std/min/max,
  robust percentiles (p5/p25/p50/p75/p95, IQR, p95−p5), analytic histogram
  (`normalised_l1`).
- **Invalid mask:** total/valid/invalid fractions + `contributing_flags`
  (`nan_inf/saturated/negative/unknown/unspecified`) using the M2 convention
  (0 == valid). Verified never inverted.
- **Classification:** engineering-level `LOW/MEDIUM/HIGH` ordinals with explicit
  thresholds + metric + value + honesty note stored per key.
- **Pair relationship:** shared-edge-bin chi-square histogram distance,
  GSD facts + ratio + factual label, native pixel-count scale gap
  (`absolute_pixel_ratio`, `native_vs_effective`), per-side coverage.

## 7. Reference-frame handling
Both sides' `native_scale_gap` records `native_equals_effective_true`,
`resampling_applied false`, `side_a_pixels`, `side_b_pixels`, and
`absolute_pixel_ratio = max/min` (≥ 1). No plane is resampled for M5 estimation.

## 8. Matcher-observation separation
`matcher_derived_observations` is `null` until an M3 baseline run exists, then records
`source: M3_BASELINE_OBSERVATION`, `baseline_configuration: MB-M3-001`,
`latest_baseline_run_id` and candidate counts — as context only. Intrinsic estimates are
byte-identical with and without the observation section (verified by test).

## 9. API surface (all auth-guarded)
- `GET /api/matching/conditions/capabilities` — CE-M5-001, configuration block,
  `data_gate` (`REAL_DATA_BLOCKED` while only fixtures), honesty note.
- `POST /api/pairs/{pair_id}/conditions/run` — `guard_run` (derived_stage `conditions`).
- `GET /api/pairs/{pair_id}/conditions/status` and `/conditions/runs`.
- `GET /api/conditions/runs/{run_id}` — full artifact read (404 for unknown).

## 10. Persistence & provenance
- One artifact per run: `data/metadata/m5_condition/<run_id>.json`, ids
  `ce-<pair>-<8hex>`, never overwritten (`write_artifact` raises `OSError`).
- Artifacts: run/source-gate/configuration/environment/estimate blocks, all product
  references relative; **no absolute machine paths** (asserted by test).

## 11. Blocked-outcome matrix
| Condition | Outcome |
| --- | --- |
| No M2 run | `BLOCKED / PROCESSING_NOT_RUN` (persisted) |
| M2 state ≠ READY_FOR_MATCHING | `BLOCKED / PROCESS_NOT_READY` |
| Products deleted | `BLOCKED / PRODUCT_MISSING` |
| No genuine data | capabilities/gate `REAL_DATA_BLOCKED` |
| No genuine pair | `BLOCKED / PAIR_NOT_AVAILABLE` |
| Structural input defects | `INVALID_INPUT` (loud) |
| Ms/Voss estimate failure | `BLOCKED / CONDITION_ESTIMATION_FAILED` |

## 12. Frontend
`frontend/src/components/ConditionAnalysisCard.jsx` wired into `Analysis.jsx` after the
baseline M3 section (CE-M5-001 badge, honest wording). `npm run build` passes.

## 13. Test summary
`tests/test_m5_condition.py` — **41 passed**. Coverage: config load + unknown-id reject;
input validation (ND/shape/empty/null); metric determinism (run-level + field-level);
sampling-plan determinism; texture orderings (textured > flat for gradient/Laplacian/
Canny); entropy + constant detection; saturation/nan-inf/negative/unknown/valid mask
fractions (never inverted); robust percentiles; chi-square distance (same ⇒ 0, different
⇒ > 0); bounded large-image sampling; recorded GSD sources + ratio; UNKNOWN GSD when the
manifest is absent; native/effective scale; forbidden-field scan; matcher-observation
separation; explicit classification thresholds; gates (PROCESSING_NOT_RUN /
PRODUCT_MISSING / real-shaped pair / synthetic labelling); artifact persistence + no
absolute paths + no-overwrite; capabilities/run/status/runs/read endpoints; auth 401;
unknown pair 404; M1/M2 regression hooks.

Regression (batched `.venv\Scripts\python.exe -m pytest`): M0 dirs/config/backend/
security 28, M1(+realdata) 42, M2+M3(+realdata) 93, M4+M5(+realdata) 131, M8+M10+M11 86,
M12+M13+M5-condition 118 — **all green** (M6/M7/M9 excluded from this milestone's scope).

## 14. Known limitation / operator step
Genuine OHRC/TMC-2 condition estimation remains `BLOCKED_PENDING_OPERATOR_DATA`. Once
real `.img`+`.xml` products are provisioned, run
`.venv\Scripts\python.exe scripts\activate_real_data.py --data-root data`; M5 then runs
on the real pair under the normal source gate.

## 15. Definition of Done mapping
- [x] Condition-estimator package/service/API/frontend (CE-M5-001).
- [x] Deterministic sampling; run-to-run determinism verified.
- [x] No selection/routing/confidence vocabulary (scan-enforced).
- [x] GSD only from recorded sources; UNKNOWN when absent.
- [x] Matcher observations in a separate labelled section.
- [x] Persisted artifacts, no overwrite, no absolute paths.
- [x] 41 M5 tests + full required regression green; report written.
- [ ] Real-data condition estimation — awaits operator data provisioning.

## 16. Sign-off status
**M5 TOOLING / STRUCTURAL VALIDATION = DONE**
**M5 GENUINE REAL-DATA CONDITION ESTIMATION = BLOCKED_PENDING_OPERATOR_DATA**