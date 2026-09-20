# CHANDRASUTRA M7 — Reproducible Experiment Report

> Metrics are measurements of pipeline evidence, never a claim of
> scientific alignment accuracy. Blocked stages report NOT_RUN/BLOCKED.

- Experiment ID: `EXP-EE0EBE7187E5`
- Pair: `CS-P001`
- Run state: `COMPLETE`
- Configuration chain:
  - `matcher_configuration_id`: `MC-M3-001`
  - `metrics_configuration_id`: `MT-M7-001`
  - `metrics_configuration_version`: `1`
  - `processing_configuration_id`: `PC-M2-001`
  - `registration_configuration_id`: `RG-M6-001`
  - `scientifically_tuned`: `no`
  - `source`: `app.yaml`
  - `spatial_reliability_configuration_id`: `SR-M5-001`
  - `trust_configuration_id`: `TG-M4-001`

## Reference / physical truth

- Reference dataset: `NOT_AVAILABLE`
- No external reference/ground-truth dataset is integrated. Real-data truth requires PRADAN approval; until then all reference comparisons report REFERENCE_UNAVAILABLE and physical_accuracy is NOT_AVAILABLE.

- physical_accuracy: NOT_AVAILABLE (never 0 or 100%)

## Evidence funnel

| metric | value | unit | status |
|---|---|---|---|
| FUNNEL_M3_TILES — matched tiles | 2 | count | AVAILABLE |
| FUNNEL_M3_CANDIDATES — M3 candidate correspondences | 100 | count | AVAILABLE |
| FUNNEL_M3_SUCCESS_TILES — M3 tiles with candidates | — | count | NOT_APPLICABLE |
| FUNNEL_M4_TRUSTED_TILES — trusted tiles | 2 | count | AVAILABLE |
| FUNNEL_M4_REJECTED_TILES — rejected tiles | — | count | BLOCKED |
| FUNNEL_M4_TRUSTED_CORRESPONDENCES — trusted correspondences | 84 | count | AVAILABLE |
| FUNNEL_M5_SELECTED_CORRESPONDENCES — spatially selected correspondences | 19 | count | AVAILABLE |
| FUNNEL_M6_REGISTERED_CORRESPONDENCES — correspondences used in transform fit | 19 | count | AVAILABLE |

### Retention ratios (engineering diagnostics)

| metric | value | unit | status |
|---|---|---|---|
| FUNNEL_M3_TO_M4_RETENTION — candidate -> trusted retention ratio | 0.84 | ratio | AVAILABLE |
| FUNNEL_M4_TO_M5_RETENTION — trusted -> selected retention ratio | 0.22619 | ratio | AVAILABLE |
| FUNNEL_M5_TO_M6_RETENTION — selected -> fitted retention ratio | 1 | ratio | AVAILABLE |

### Rejection / attrition by reason code (real artefacts only)

| reason code | count |
|---|---|
| `SR_SELECTED_NEIGHBOR_SUPPORTED` | 19 |
| `SR_SELECTED_SPATIAL_COVERAGE` | 19 |
| `SR_SELECTED_SUPPORTED_REGION` | 19 |

## Measured metrics

### OBSERVATION

| metric_id | value | unit | scientific status | status |
|---|---|---|---|---|
| ATTENTION_DISTRIBUTION | SR_SELECTED_SUPPORTED_REGION=19 SR_SELECTED_NEIGHBOR_SUPPORTED=19 SR_SELECTED_SPATIAL_COVERAGE=19 | — | MEASUREMENT | AVAILABLE |
| FUNNEL_M3_CANDIDATES | 100 | count | ENGINEERING | AVAILABLE |
| FUNNEL_M3_SUCCESS_TILES | — | count | ENGINEERING | NOT_APPLICABLE |
| FUNNEL_M3_TILES | 2 | count | ENGINEERING | AVAILABLE |
| REG_FINITE_USABLE | 19 | count | MEASUREMENT | AVAILABLE |
| REG_OUTPUT_COLS | 500 | count | MEASUREMENT | AVAILABLE |
| REG_OUTPUT_ROWS | 400 | count | MEASUREMENT | AVAILABLE |
| REG_SELECTED_CORRESPONDENCES | 19 | count | MEASUREMENT | AVAILABLE |
| REG_SELECTION_REASON | PREFERRED | — | MEASUREMENT | AVAILABLE |
| REG_TRANSFORM_TYPE | HOMOGRAPHY | — | MEASUREMENT | AVAILABLE |
| SPATIAL_GRID_COLS | 8 | count | ENGINEERING | AVAILABLE |
| SPATIAL_GRID_ROWS | 8 | count | ENGINEERING | AVAILABLE |

### MEASUREMENT

| metric_id | value | unit | scientific status | status |
|---|---|---|---|---|
| FUNNEL_M4_TRUSTED_CORRESPONDENCES | 84 | count | MEASUREMENT | AVAILABLE |
| FUNNEL_M5_SELECTED_CORRESPONDENCES | 19 | count | MEASUREMENT | AVAILABLE |
| FUNNEL_M6_REGISTERED_CORRESPONDENCES | 19 | count | MEASUREMENT | AVAILABLE |
| REG_INLIERS | 19 | count | MEASUREMENT | AVAILABLE |
| REG_INLIER_RATIO | 1 | ratio | MEASUREMENT | AVAILABLE |
| REG_OUTLIERS | 0 | count | MEASUREMENT | AVAILABLE |
| REG_RESIDUAL_MAX_PX | 2.67345 | px | MEASUREMENT | AVAILABLE |
| REG_RESIDUAL_MEAN_PX | 0.969228 | px | MEASUREMENT | AVAILABLE |
| REG_RESIDUAL_MEDIAN_PX | 0.978944 | px | MEASUREMENT | AVAILABLE |
| REG_RESIDUAL_P95_PX | 2.45215 | px | MEASUREMENT | AVAILABLE |
| REG_SYMMETRIC_TRANSFER_MAX_PX | 2.67345 | px | MEASUREMENT | AVAILABLE |
| REG_SYMMETRIC_TRANSFER_MEAN_PX | 0.970708 | px | MEASUREMENT | AVAILABLE |
| REG_VALID_FOR_FIT | 19 | count | MEASUREMENT | AVAILABLE |
| REG_VALID_PIXEL_FRACTION | 0.9875 | fraction | MEASUREMENT | AVAILABLE |
| SPATIAL_CELLS_OBSERVED | 30 | count | MEASUREMENT | AVAILABLE |
| SPATIAL_RELIABLE_CELLS | 8 | count | MEASUREMENT | AVAILABLE |
| SPATIAL_SUPPORTED_CELLS | 7 | count | MEASUREMENT | AVAILABLE |
| SPATIAL_VERIFIED_INLIER_COUNT | 84 | count | MEASUREMENT | AVAILABLE |

### VALIDATION

| metric_id | value | unit | scientific status | status |
|---|---|---|---|---|
| FUNNEL_M4_REJECTED_TILES | — | count | MEASUREMENT | BLOCKED |
| FUNNEL_M4_TRUSTED_TILES | 2 | count | MEASUREMENT | AVAILABLE |
| REG_VALIDATION_VERDICT | PASS | — | MEASUREMENT | AVAILABLE |
| SPATIAL_CAPPED_AT_LIMIT | no | — | ENGINEERING | AVAILABLE |
| SPATIAL_SELECTION_OUTCOME | SELECTED | — | MEASUREMENT | AVAILABLE |

### DIAGNOSTIC

| metric_id | value | unit | scientific status | status |
|---|---|---|---|---|
| FUNNEL_M3_TO_M4_RETENTION | 0.84 | ratio | ENGINEERING | AVAILABLE |
| FUNNEL_M4_TO_M5_RETENTION | 0.22619 | ratio | ENGINEERING | AVAILABLE |
| FUNNEL_M5_TO_M6_RETENTION | 1 | ratio | ENGINEERING | AVAILABLE |
| RECOMPUTE_INLIER_COUNT | 19 | count | DIAGNOSTIC | AVAILABLE |
| RECOMPUTE_MISMATCH | — | — | DIAGNOSTIC | NOT_APPLICABLE |
| RECOMPUTE_RESIDUAL_MEAN_PX | 0.969228 | px | DIAGNOSTIC | AVAILABLE |
| RECOMPUTE_RESIDUAL_MEDIAN_PX | 0.978944 | px | DIAGNOSTIC | AVAILABLE |
| RECOMPUTE_RESIDUAL_P95_PX | 2.45215 | px | DIAGNOSTIC | AVAILABLE |
| RECOMPUTE_SYMMETRIC_TRANSFER_MAX_PX | 2.67345 | px | DIAGNOSTIC | AVAILABLE |
| RECOMPUTE_VALID_PROJECTION_COUNT | 19 | count | DIAGNOSTIC | AVAILABLE |
| REG_CONDITION_NUMBER | 1.0472 | — | DIAGNOSTIC | AVAILABLE |
| REG_DEGENERACY_FLAGS | — | — | DIAGNOSTIC | AVAILABLE |
| REG_DETERMINANT | 0.968043 | — | DIAGNOSTIC | AVAILABLE |
| REG_ITERATIONS_USED | 2000 | count | DIAGNOSTIC | AVAILABLE |
| REG_ROTATION_DEG | 1.2616 | degrees | DIAGNOSTIC | AVAILABLE |
| REG_RUNTIME_SECONDS | — | seconds | DIAGNOSTIC | BLOCKED |
| REG_SCALE_X | 1.00685 | dimensionless | DIAGNOSTIC | AVAILABLE |
| REG_SCALE_Y | 0.961461 | dimensionless | DIAGNOSTIC | AVAILABLE |
| REG_TRANSLATION_PX | 13.3624, 2.90267 | px | DIAGNOSTIC | AVAILABLE |
| SPATIAL_CONNECTED_COMPONENTS | 3 | count | MEASUREMENT | AVAILABLE |
| SPATIAL_EDGE_FRACTION | — | fraction | DIAGNOSTIC | BLOCKED |
| SPATIAL_LARGEST_COMPONENT_RATIO | — | ratio | DIAGNOSTIC | BLOCKED |
| SPATIAL_MEAN_DENSITY | 179.2 | count | DIAGNOSTIC | AVAILABLE |
| SPATIAL_SELECTION_COVERAGE | 0.133333 | fraction | DIAGNOSTIC | AVAILABLE |

## Independent recomputation

| statistic | recomputed | recorded | consistent |
|---|---|---|---|
| forward residual mean (px) | 0.969228 | — | True |
| recomputed inlier count | 19 | — | — |
| valid projection count | 19 | — | — |

## Methodology notes

- Independent recomputation re-derives forward residuals, symmetric transfer, inlier count (policy threshold) and valid projection count directly from the fitted matrix and the selected evidence using M4 trust primitives.
- This report is generated deterministically from artefacts; see report.json for the generation timestamp.

---
CHANDRASUTRA M7 · metrics are measurements, not proof.
