"""M7 metric taxonomy — the canonical registry of metric definitions.

Every metric_id produced by M7 must be declared here with its category,
unit and scientific status. This is the single source of truth the tests and
the report generation validate against.
"""

from __future__ import annotations

from backend.app.metrics.states import MetricCategory, ScientificStatus

# metric_id -> (name, unit, category, scientific_status)
TAXONOMY: dict[str, tuple[str, str | None, MetricCategory, ScientificStatus]] = {
    # ---- M3 evidence funnel ------------------------------------------------ #
    "FUNNEL_M3_TILES": ("matched tiles", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
    "FUNNEL_M3_CANDIDATES": ("M3 candidate correspondences", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
    "FUNNEL_M3_SUCCESS_TILES": ("M3 tiles with candidates", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
    # ---- M4 trust gate ----------------------------------------------------- #
    "FUNNEL_M4_TRUSTED_TILES": ("trusted tiles", "count", MetricCategory.VALIDATION, ScientificStatus.MEASUREMENT),
    "FUNNEL_M4_REJECTED_TILES": ("rejected tiles", "count", MetricCategory.VALIDATION, ScientificStatus.MEASUREMENT),
    "FUNNEL_M4_TRUSTED_CORRESPONDENCES": ("trusted correspondences", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    # ---- M5 spatial selection ---------------------------------------------- #
    "FUNNEL_M5_SELECTED_CORRESPONDENCES": ("spatially selected correspondences", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    # ---- M6 registration --------------------------------------------------- #
    "FUNNEL_M6_REGISTERED_CORRESPONDENCES": ("correspondences used in transform fit", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    # ---- power/attrition --------------------------------------------------- #
    "ATTENTION_DISTRIBUTION": ("rejection/attrition by reason code", None, MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    "FUNNEL_M3_TO_M4_RETENTION": ("candidate -> trusted retention ratio", "ratio", MetricCategory.DIAGNOSTIC, ScientificStatus.ENGINEERING),
    "FUNNEL_M4_TO_M5_RETENTION": ("trusted -> selected retention ratio", "ratio", MetricCategory.DIAGNOSTIC, ScientificStatus.ENGINEERING),
    "FUNNEL_M5_TO_M6_RETENTION": ("selected -> fitted retention ratio", "ratio", MetricCategory.DIAGNOSTIC, ScientificStatus.ENGINEERING),
    # ---- spatial reliability (M5) ------------------------------------------ #
    "SPATIAL_GRID_ROWS": ("reliability grid rows", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
    "SPATIAL_GRID_COLS": ("reliability grid cols", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
    "SPATIAL_CELLS_OBSERVED": ("scene cells observed", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "SPATIAL_RELIABLE_CELLS": ("reliable cells", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "SPATIAL_SUPPORTED_CELLS": ("supported cells", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "SPATIAL_CONNECTED_COMPONENTS": ("connected components", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.MEASUREMENT),
    "SPATIAL_LARGEST_COMPONENT_RATIO": ("largest component coverage ratio", "ratio", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "SPATIAL_EDGE_FRACTION": ("edge-touching cell fraction", "fraction", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "SPATIAL_VERIFIED_INLIER_COUNT": ("verified inliers in scene", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "SPATIAL_MEAN_DENSITY": ("mean correspondence density per observed cell", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "SPATIAL_SELECTION_OUTCOME": ("M5 selection outcome", None, MetricCategory.VALIDATION, ScientificStatus.MEASUREMENT),
    "SPATIAL_SELECTION_COVERAGE": ("selected/observed cell coverage", "fraction", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "SPATIAL_CAPPED_AT_LIMIT": ("selection capped at configured limit", None, MetricCategory.VALIDATION, ScientificStatus.ENGINEERING),
    # ---- registration (M6, artefact-read) ---------------------------------- #
    "REG_SELECTED_CORRESPONDENCES": ("M6 selected correspondences", "count", MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    "REG_FINITE_USABLE": ("finite usable correspondences", "count", MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    "REG_VALID_FOR_FIT": ("correspondences valid for fit", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_INLIERS": ("transform inliers", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_OUTLIERS": ("transform outliers", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_INLIER_RATIO": ("inlier ratio", "ratio", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_RESIDUAL_MEAN_PX": ("forward residual mean", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_RESIDUAL_MEDIAN_PX": ("forward residual median", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_RESIDUAL_P95_PX": ("forward residual p95", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_RESIDUAL_MAX_PX": ("forward residual max", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_SYMMETRIC_TRANSFER_MEAN_PX": ("symmetric transfer mean", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_SYMMETRIC_TRANSFER_MAX_PX": ("symmetric transfer max", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_DETERMINANT": ("determinant of linear part", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_CONDITION_NUMBER": ("condition number of linear part", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_DEGENERACY_FLAGS": ("degeneracy flags", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_ITERATIONS_USED": ("RANSAC iterations used", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_RUNTIME_SECONDS": ("transform fit runtime", "seconds", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_VALIDATION_VERDICT": ("M6 validation verdict", None, MetricCategory.VALIDATION, ScientificStatus.MEASUREMENT),
    "REG_TRANSFORM_TYPE": ("fitted transform type", None, MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    "REG_SELECTION_REASON": ("transform selection reason", None, MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    "REG_TRANSLATION_PX": ("translation (tx, ty)", "px", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_SCALE_X": ("estimated scale x (SVD of linear part)", "dimensionless", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_SCALE_Y": ("estimated scale y (SVD of linear part)", "dimensionless", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_ROTATION_DEG": ("estimated rotation", "degrees", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "REG_VALID_PIXEL_FRACTION": ("registered valid pixel fraction", "fraction", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
    "REG_OUTPUT_ROWS": ("registered output rows", "count", MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    "REG_OUTPUT_COLS": ("registered output cols", "count", MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT),
    # ---- independent recomputation (M7) ------------------------------------ #
    "RECOMPUTE_RESIDUAL_MEAN_PX": ("recomputed forward residual mean", "px", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "RECOMPUTE_RESIDUAL_MEDIAN_PX": ("recomputed forward residual median", "px", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "RECOMPUTE_RESIDUAL_P95_PX": ("recomputed forward residual p95", "px", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "RECOMPUTE_SYMMETRIC_TRANSFER_MAX_PX": ("recomputed symmetric transfer max", "px", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "RECOMPUTE_INLIER_COUNT": ("recomputed inlier count (threshold policy)", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "RECOMPUTE_VALID_PROJECTION_COUNT": ("correspondences with finite projection", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    "RECOMPUTE_MISMATCH": ("recomputation mismatch diagnostics", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
    # ---- reference/physical truth (M7, always NOT_AVAILABLE at M7) --------- #
    "PHYSICAL_TRUTH_AVAILABLE": ("physical truth dataset availability", None, MetricCategory.REFERENCE, ScientificStatus.REFERENCE),
    "PHYSICAL_ACCURACY": ("physical alignment accuracy", None, MetricCategory.REFERENCE, ScientificStatus.REFERENCE),
}

# metrics that may legitimately appear with a dict/list value
DICT_VALUE_METRICS = {
    "ATTENTION_DISTRIBUTION",
    "REG_DEGENERACY_FLAGS",
    "REG_TRANSLATION_PX",
    "RECOMPUTE_MISMATCH",
}


def taxonomy_lookup(metric_id: str) -> dict:
    name, unit, category, sci = TAXONOMY[metric_id]
    return {
        "metric_id": metric_id,
        "name": name,
        "unit": unit,
        "category": category.value,
        "scientific_status": sci.value,
    }