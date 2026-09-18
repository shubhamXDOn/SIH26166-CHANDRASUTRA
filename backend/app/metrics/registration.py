"""M7 registration metrics — read from real M6 artefacts and independently recomputed.

Recomputation deliberately rebuilds forward residuals and symmetric transfer on
the fitted matrix using the M4 trust primitives, and a policy inlier threshold,
so the report can truthfully state that the numbers were re-derived rather than
copied from the fit package.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from backend.app.metrics.config import MetricsConfig
from backend.app.metrics.schema import metric, unavailable_metric, METRIC_RECOMPUTATION_MISMATCH
from backend.app.metrics.states import (
    MetricCategory,
    MetricStatus,
    ScientificStatus,
)
from backend.app.registration.coord_space import (
    build_sensor_pixel_points,
    build_tile_geometry_map,
    load_mapping_context,
)
from backend.app.registration.loader import load_selected_correspondences
from backend.app.trust.geometry import _compute_residuals_forward, compute_symmetric_transfer


def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _f_round(value, ndigits: int = 6):
    if value is None:
        return None
    try:
        if not math.isfinite(float(value)):
            return float(value) if float(value) in (math.inf, -math.inf) else None
        return round(float(value), ndigits)
    except (TypeError, ValueError):
        return None


def decompose_transform(matrix) -> dict:
    """Estimate translation/scale/rotation from the fitted matrix linear part.

    Homography projective content makes these local approximations at the source
    origin; never presented as a rigorous camera-model decomposition.
    """
    m = np.asarray(matrix, dtype=np.float64)
    if m is None or m.ndim != 2 or m.shape[0] < 2 or m.shape[1] < 3:
        return {"scale_x": None, "scale_y": None, "rotation_deg": None,
                "translation": None, "note": "no usable matrix"}
    A = m[:2, :2]
    t = m[:2, 2]
    scale = None
    angle = None
    try:
        _u, s, _vt = np.linalg.svd(A)
        R = _u @ _vt
        angle = float(math.degrees(math.atan2(float(R[1, 0]), float(R[0, 0]))))
        scale = (float(s[0]), float(s[1]))
    except np.linalg.LinAlgError:
        scale = None
        angle = None
    return {
        "scale_x": scale[0] if scale is not None else None,
        "scale_y": scale[1] if scale is not None else None,
        "rotation_deg": _f_round(angle, 4) if angle is not None else None,
        "translation": [round(float(t[0]), 6), round(float(t[1]), 6)] if np.all(np.isfinite(t)) else None,
        "note": "SVD of the 2x2 linear part of the fitted matrix; local engineering estimate only.",
    }


def collect_registration_metrics(m6_run: Path | None, data_root: Path) -> list[dict]:
    """Read registration metrics from M6 artefacts (diagnostics/transform/validation)."""
    records: list[dict] = []
    rel = None
    if m6_run is not None and m6_run.is_relative_to(data_root):
        rel = m6_run.relative_to(data_root).as_posix()

    diagnostics = _read_json(m6_run / "diagnostics.json", {}) if m6_run else {}
    if not diagnostics:
        for mid, name, unit, cat in [
            ("REG_SELECTED_CORRESPONDENCES", "M6 selected correspondences", "count", MetricCategory.OBSERVATION),
            ("REG_FINITE_USABLE", "finite usable correspondences", "count", MetricCategory.OBSERVATION),
            ("REG_VALID_FOR_FIT", "correspondences valid for fit", "count", MetricCategory.MEASUREMENT),
            ("REG_INLIERS", "transform inliers", "count", MetricCategory.MEASUREMENT),
            ("REG_OUTLIERS", "transform outliers", "count", MetricCategory.MEASUREMENT),
            ("REG_INLIER_RATIO", "inlier ratio", "ratio", MetricCategory.MEASUREMENT),
            ("REG_RESIDUAL_MEAN_PX", "forward residual mean", "px", MetricCategory.MEASUREMENT),
            ("REG_RESIDUAL_MEDIAN_PX", "forward residual median", "px", MetricCategory.MEASUREMENT),
            ("REG_RESIDUAL_P95_PX", "forward residual p95", "px", MetricCategory.MEASUREMENT),
            ("REG_RESIDUAL_MAX_PX", "forward residual max", "px", MetricCategory.MEASUREMENT),
            ("REG_SYMMETRIC_TRANSFER_MEAN_PX", "symmetric transfer mean", "px", MetricCategory.MEASUREMENT),
            ("REG_SYMMETRIC_TRANSFER_MAX_PX", "symmetric transfer max", "px", MetricCategory.MEASUREMENT),
            ("REG_DETERMINANT", "determinant of linear part", None, MetricCategory.DIAGNOSTIC),
            ("REG_CONDITION_NUMBER", "condition number of linear part", None, MetricCategory.DIAGNOSTIC),
            ("REG_DEGENERACY_FLAGS", "degeneracy flags", None, MetricCategory.DIAGNOSTIC),
            ("REG_ITERATIONS_USED", "RANSAC iterations used", "count", MetricCategory.DIAGNOSTIC),
            ("REG_RUNTIME_SECONDS", "transform fit runtime", "seconds", MetricCategory.DIAGNOSTIC),
            ("REG_TRANSLATION_PX", "translation (tx, ty)", "px", MetricCategory.DIAGNOSTIC),
            ("REG_SCALE_X", "estimated scale x (SVD of linear part)", "dimensionless", MetricCategory.DIAGNOSTIC),
            ("REG_SCALE_Y", "estimated scale y (SVD of linear part)", "dimensionless", MetricCategory.DIAGNOSTIC),
            ("REG_ROTATION_DEG", "estimated rotation", "degrees", MetricCategory.DIAGNOSTIC),
        ]:
            records.append(unavailable_metric(
                mid, name, unit, cat, "M6", None, "no M6 diagnostics.json artefact present",
                "Registration diagnostics unavailable.", MetricStatus.BLOCKED))
        return records

    corr = diagnostics.get("correspondences") or {}
    resid = diagnostics.get("residuals") or {}
    sym = diagnostics.get("symmetric_transfer") or {}
    num = diagnostics.get("numerics") or {}

    def _add(mid, name, unit, cat, sci, value, status, method, interp, src=None):
        records.append(metric(
            mid, name, value, unit, cat, "M6", src or ((rel + "/diagnostics.json") if rel else None),
            method, interp, sci, status=status))

    def _avail(v):
        return MetricStatus.AVAILABLE if v is not None else MetricStatus.BLOCKED

    _add("REG_SELECTED_CORRESPONDENCES", "M6 selected correspondences", "count", MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT,
         corr.get("selected_total"), _avail(corr.get("selected_total")), "read from diagnostics.json 'correspondences.selected_total'",
         "Correspondences M6 received from M5 selection.")
    _add("REG_FINITE_USABLE", "finite usable correspondences", "count", MetricCategory.OBSERVATION, ScientificStatus.MEASUREMENT,
         corr.get("finite_usable"), _avail(corr.get("finite_usable")), "read from diagnostics.json 'correspondences.finite_usable'",
         "Correspondences with finite coordinates usable for fitting.")
    _add("REG_VALID_FOR_FIT", "correspondences valid for fit", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         corr.get("valid_for_fit"), _avail(corr.get("valid_for_fit")), "read from diagnostics.json 'correspondences.valid_for_fit'",
         "Correspondences that entered the transform fit.")
    _add("REG_INLIERS", "transform inliers", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         corr.get("inliers"), _avail(corr.get("inliers")), "read from diagnostics.json 'correspondences.inliers'",
         "RANSAC-consensus inliers of the fitted transform.")
    _add("REG_OUTLIERS", "transform outliers", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         corr.get("outliers"), _avail(corr.get("outliers")), "read from diagnostics.json 'correspondences.outliers'",
         "Correspondences rejected by consensus.")
    _add("REG_INLIER_RATIO", "inlier ratio", "ratio", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         corr.get("inlier_ratio"), _avail(corr.get("inlier_ratio")), "read from diagnostics.json 'correspondences.inlier_ratio'",
         "Inlier/valid-for-fit ratio; internal consistency, not physical accuracy.")
    _add("REG_RESIDUAL_MEAN_PX", "forward residual mean", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         _f_round(resid.get("mean_px")), _avail(resid.get("mean_px")), "read from diagnostics.json 'residuals.mean_px'",
         "Mean forward-projection residual over inlier correspondences.")
    _add("REG_RESIDUAL_MEDIAN_PX", "forward residual median", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         _f_round(resid.get("median_px")), _avail(resid.get("median_px")), "read from diagnostics.json 'residuals.median_px'",
         "Median forward-projection residual over inlier correspondences.")
    _add("REG_RESIDUAL_P95_PX", "forward residual p95", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         _f_round(resid.get("p95_px")), _avail(resid.get("p95_px")), "read from diagnostics.json 'residuals.p95_px'",
         "95th percentile forward-projection residual.")
    _add("REG_RESIDUAL_MAX_PX", "forward residual max", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         _f_round(resid.get("max_px")), _avail(resid.get("max_px")), "read from diagnostics.json 'residuals.max_px'",
         "Maximum inlier forward-projection residual.")
    _add("REG_SYMMETRIC_TRANSFER_MEAN_PX", "symmetric transfer mean", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         _f_round(sym.get("mean_px")), _avail(sym.get("mean_px")), "read from diagnostics.json 'symmetric_transfer.mean_px'",
         "Mean symmetric transfer error fwd+inv.")
    _add("REG_SYMMETRIC_TRANSFER_MAX_PX", "symmetric transfer max", "px", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         _f_round(sym.get("max_px")), _avail(sym.get("max_px")), "read from diagnostics.json 'symmetric_transfer.max_px'",
         "Max symmetric transfer error.")
    _add("REG_DETERMINANT", "determinant of linear part", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         num.get("determinant"), _avail(num.get("determinant")), "read from diagnostics.json 'numerics.determinant'",
         "Determinant of the linear part; near-zero signals degeneracy.")
    _add("REG_CONDITION_NUMBER", "condition number of linear part", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         num.get("condition_number"), _avail(num.get("condition_number")), "read from diagnostics.json 'numerics.condition_number'",
         "Condition number of the linear part.")
    _add("REG_DEGENERACY_FLAGS", "degeneracy flags", None, MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         list(num.get("degeneracy_flags") or []) or None, MetricStatus.AVAILABLE if num.get("degeneracy_flags") is not None else MetricStatus.BLOCKED,
         "read from diagnostics.json 'numerics.degeneracy_flags'", "Model degeneracy flags from fitting.")
    _add("REG_ITERATIONS_USED", "RANSAC iterations used", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         num.get("iterations_used"), _avail(num.get("iterations_used")), "read from diagnostics.json 'numerics.iterations_used'",
         "RANSAC iterations consumed while fitting.")
    _add("REG_RUNTIME_SECONDS", "transform fit runtime", "seconds", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         diagnostics.get("runtime_seconds"), _avail(diagnostics.get("runtime_seconds")), "read from diagnostics.json 'runtime_seconds'",
         "Transform fit wall time.")

    validation = _read_json(m6_run / "validation.json", {}) if m6_run else {}
    verdict = validation.get("verdict")
    records.append(metric(
        "REG_VALIDATION_VERDICT", "M6 validation verdict", verdict,
        None, MetricCategory.VALIDATION, "M6", (rel + "/validation.json") if rel else None,
        "read from registration validation.json 'verdict'",
        "Verdict of M6 validation thresholds (PASS/FAIL/INSUFFICIENT).",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if verdict is not None else MetricStatus.BLOCKED))

    transform = _read_json(m6_run / "transform.json", {}) if m6_run else {}
    matrix = transform.get("matrix")
    decomposed = decompose_transform(matrix) if matrix else {}
    rec = records
    rec.append(metric(
        "REG_TRANSFORM_TYPE", "fitted transform type", transform.get("transform_type"),
        None, MetricCategory.OBSERVATION, "M6", (rel + "/transform.json") if rel else None,
        "read from registration transform.json 'transform_type'",
        "Type of the fitted transform (HOMOGRAPHY/AFFINE).",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if transform.get("transform_type") else MetricStatus.BLOCKED))
    rec.append(metric(
        "REG_SELECTION_REASON", "transform selection reason",
        diagnostics.get("selection_reason"), None, MetricCategory.OBSERVATION, "M6",
        (rel + "/diagnostics.json") if rel else None,
        "read from diagnostics.json 'selection_reason'",
        "Why the preferred/fallback transform model was chosen.",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if diagnostics.get("selection_reason") else MetricStatus.BLOCKED))
    rec.append(metric(
        "REG_TRANSLATION_PX", "translation (tx, ty)", decomposed.get("translation"),
        "px", MetricCategory.DIAGNOSTIC, "M6", (rel + "/transform.json") if rel else None,
        "fitted matrix column 3 (tx, ty)",
        "Reported shift components of the fitted matrix; not a geolocation quantity.",
        ScientificStatus.DIAGNOSTIC,
        status=MetricStatus.AVAILABLE if decomposed.get("translation") is not None else MetricStatus.NOT_APPLICABLE))
    rec.append(metric(
        "REG_SCALE_X", "estimated scale x (SVD of linear part)", decomposed.get("scale_x"),
        "dimensionless", MetricCategory.DIAGNOSTIC, "M6", (rel + "/transform.json") if rel else None,
        decomposed.get("note", "SVD of linear part"),
        "Estimated scale along x of the linear part (local approximation).",
        ScientificStatus.DIAGNOSTIC,
        status=MetricStatus.AVAILABLE if decomposed.get("scale_x") is not None else MetricStatus.NOT_APPLICABLE))
    rec.append(metric(
        "REG_SCALE_Y", "estimated scale y (SVD of linear part)", decomposed.get("scale_y"),
        "dimensionless", MetricCategory.DIAGNOSTIC, "M6", (rel + "/transform.json") if rel else None,
        decomposed.get("note", "SVD of linear part"),
        "Estimated scale along y of the linear part (local approximation).",
        ScientificStatus.DIAGNOSTIC,
        status=MetricStatus.AVAILABLE if decomposed.get("scale_y") is not None else MetricStatus.NOT_APPLICABLE))
    rec.append(metric(
        "REG_ROTATION_DEG", "estimated rotation", decomposed.get("rotation_deg"),
        "degrees", MetricCategory.DIAGNOSTIC, "M6", (rel + "/transform.json") if rel else None,
        decomposed.get("note", "SVD of linear part"),
        "Estimated rotation angle of the linear part (local approximation).",
        ScientificStatus.DIAGNOSTIC,
        status=MetricStatus.AVAILABLE if decomposed.get("rotation_deg") is not None else MetricStatus.NOT_APPLICABLE))

    reg_meta = _read_json(m6_run / "registered" / "registered_meta.json", {}) if m6_run else {}
    rec.append(metric(
        "REG_VALID_PIXEL_FRACTION", "registered valid pixel fraction", reg_meta.get("valid_pixel_fraction"),
        "fraction", MetricCategory.MEASUREMENT, "M6",
        (rel + "/registered/registered_meta.json") if rel else None,
        "read from registered_meta.json 'valid_pixel_fraction'",
        "Fraction of the registered window covered by valid (filled) source pixels.",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if reg_meta.get("valid_pixel_fraction") is not None else MetricStatus.BLOCKED))
    rec.append(metric(
        "REG_OUTPUT_ROWS", "registered output rows", reg_meta.get("out_rows"),
        "count", MetricCategory.OBSERVATION, "M6",
        (rel + "/registered/registered_meta.json") if rel else None,
        "read from registered_meta.json 'out_rows'",
        "Height of the registered product.",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if reg_meta.get("out_rows") is not None else MetricStatus.BLOCKED))
    rec.append(metric(
        "REG_OUTPUT_COLS", "registered output cols", reg_meta.get("out_cols"),
        "count", MetricCategory.OBSERVATION, "M6",
        (rel + "/registered/registered_meta.json") if rel else None,
        "read from registered_meta.json 'out_cols'",
        "Width of the registered product.",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if reg_meta.get("out_cols") is not None else MetricStatus.BLOCKED))

    return records


def recompute_registration_metrics(
    data_root: Path,
    pair_id: str,
    m5_run: Path,
    m6_run: Path,
    cfg: MetricsConfig,
    spatial_service,
) -> dict:
    """Independently recompute M6 error metrics from on-disk evidence.

    Returns a payload with METRIC_RECOMPUTATION_MISMATCH entries when the
    recomputation diverges from the recorded M6 diagnostics beyond tolerance.
    """
    mismatch: list[str] = []
    try:
        evidence = load_selected_correspondences(data_root, pair_id, spatial_service)
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "ERROR",
            "reason": str(exc).split(":", 1)[0],
            "recomputed": False,
            "match_mismatch": [METRIC_RECOMPUTATION_MISMATCH + ": cannot recompute — " + str(exc).split(":", 1)[0]],
        }

    mapping = load_mapping_context(m5_run)
    if mapping is None:
        return {"status": "ERROR", "recomputed": False, "reason": "MAPPING_MISSING",
                "match_mismatch": [METRIC_RECOMPUTATION_MISMATCH + ": mapping.json missing"]}
    tile_geom_map = build_tile_geometry_map(mapping)

    px_a_x, px_a_y, px_b_x, px_b_y, valid = build_sensor_pixel_points(
        evidence.x_a, evidence.y_a, evidence.x_b, evidence.y_b,
        evidence.source_tile_id, tile_geom_map,
    )
    n_valid = int(np.sum(valid))
    if n_valid < 4:
        return {"status": "INSUFFICIENT", "recomputed": False,
                "reason": f"only {n_valid} valid sensor-pixel correspondences",
                "match_mismatch": []}

    transform = _read_json(m6_run / "transform.json", {})
    matrix = transform.get("matrix")
    if not matrix:
        return {"status": "NOT_APPLICABLE", "recomputed": False,
                "reason": "no transform matrix recorded", "match_mismatch": []}

    h = np.asarray(matrix, dtype=np.float64)
    pts_a = np.column_stack([px_a_x[valid], px_a_y[valid]])
    pts_b = np.column_stack([px_b_x[valid], px_b_y[valid]])

    res = _compute_residuals_forward(pts_a, pts_b, h)
    sym = compute_symmetric_transfer(pts_a, pts_b, h)

    finite = np.isfinite(res)
    valid_projection_count = int(np.sum(finite))
    threshold = cfg.recompute.inlier_threshold_px
    inlier = finite & (res < threshold)
    inlier_count = int(np.sum(inlier))

    inlier_stats = None
    inlier_vals = res[inlier]
    if inlier_vals.size:
        inlier_stats = {
            "mean_px": round(float(np.mean(inlier_vals)), 6),
            "median_px": round(float(np.median(inlier_vals)), 6),
            "p95_px": round(float(np.percentile(inlier_vals, 95)), 6),
        }
    sym_finite = sym[np.isfinite(sym)]
    sym_max = round(float(np.max(sym_finite)), 6) if sym_finite.size else None

    # ---- consistency vs recorded M6 diagnostics ---------------------------
    diagnostics = _read_json(m6_run / "diagnostics.json", {})
    resid = diagnostics.get("residuals") or {}
    symd = diagnostics.get("symmetric_transfer") or {}
    ref_mean = resid.get("mean_px")
    ref_median = resid.get("median_px")
    ref_p95 = resid.get("p95_px")
    ref_sym_max = symd.get("max_px")
    tol = float(cfg.recompute.consistency_tolerance)

    def _consistent(rec, ref):
        if rec is None or ref is None:
            return ref is None
        if not (math.isfinite(float(rec)) and math.isfinite(float(ref))):
            return True
        return abs(float(rec) - float(ref)) <= tol * max(1.0, abs(float(ref)))

    compare = [
        ("residual_mean_px", inlier_stats["mean_px"] if inlier_stats else None, ref_mean),
        ("residual_median_px", inlier_stats["median_px"] if inlier_stats else None, ref_median),
        ("residual_p95_px", inlier_stats["p95_px"] if inlier_stats else None, ref_p95),
        ("symmetric_transfer_max_px", sym_max, ref_sym_max),
    ]
    for name, rec, ref in compare:
        if not _consistent(rec, ref):
            mismatch.append(f"{METRIC_RECOMPUTATION_MISMATCH} on {name}: recomputed={rec} vs recorded={ref}")

    return {
        "status": "COMPUTED",
        "recomputed": True,
        "method": "recompute forward residuals + symmetric transfer + policy-threshold inliers "
                  "on the fitted matrix using M4 trust primitives",
        "residual_mean_px": inlier_stats["mean_px"] if inlier_stats else None,
        "residual_median_px": inlier_stats["median_px"] if inlier_stats else None,
        "residual_p95_px": inlier_stats["p95_px"] if inlier_stats else None,
        "symmetric_transfer_max_px": sym_max,
        "inlier_count": inlier_count,
        "inlier_threshold_px": threshold,
        "valid_projection_count": valid_projection_count,
        "consistent_with_fit": not mismatch,
        "match_mismatch": mismatch,
    }


def recompute_metric_records(recompute: dict) -> list[dict]:
    """Convert a recompute payload into canonical metric records."""
    if not recompute.get("recomputed"):
        status = MetricStatus.NOT_APPLICABLE
        if recompute.get("status") == "ERROR":
            status = MetricStatus.FAILED
        elif recompute.get("status") == "INSUFFICIENT":
            status = MetricStatus.INSUFFICIENT
        return [
            unavailable_metric(
                "RECOMPUTE_RESIDUAL_MEAN_PX", "recomputed forward residual mean", "px",
                MetricCategory.DIAGNOSTIC, "M7", None,
                recompute.get("method", "recompute not run"), recompute.get("reason", ""), status),
            unavailable_metric(
                "RECOMPUTE_RESIDUAL_MEDIAN_PX", "recomputed forward residual median", "px",
                MetricCategory.DIAGNOSTIC, "M7", None,
                recompute.get("method", "recompute not run"), recompute.get("reason", ""), status),
            unavailable_metric(
                "RECOMPUTE_RESIDUAL_P95_PX", "recomputed forward residual p95", "px",
                MetricCategory.DIAGNOSTIC, "M7", None,
                recompute.get("method", "recompute not run"), recompute.get("reason", ""), status),
            unavailable_metric(
                "RECOMPUTE_SYMMETRIC_TRANSFER_MAX_PX", "recomputed symmetric transfer max", "px",
                MetricCategory.DIAGNOSTIC, "M7", None,
                recompute.get("method", "recompute not run"), recompute.get("reason", ""), status),
            unavailable_metric(
                "RECOMPUTE_INLIER_COUNT", "recomputed inlier count (threshold policy)", "count",
                MetricCategory.DIAGNOSTIC, "M7", None,
                recompute.get("method", "recompute not run"), recompute.get("reason", ""), status),
            unavailable_metric(
                "RECOMPUTE_VALID_PROJECTION_COUNT", "correspondences with finite projection", "count",
                MetricCategory.DIAGNOSTIC, "M7", None,
                recompute.get("method", "recompute not run"), recompute.get("reason", ""), status),
            metric(
                "RECOMPUTE_MISMATCH", "recomputation mismatch diagnostics",
                recompute.get("match_mismatch") or None, None, MetricCategory.DIAGNOSTIC, "M7", None,
                "consistency comparison against recorded M6 diagnostics",
                "Reports divergence between independent recomputation and recorded M6 numbers.",
                ScientificStatus.DIAGNOSTIC,
                status=MetricStatus.AVAILABLE if recompute.get("match_mismatch") else MetricStatus.NOT_APPLICABLE),
        ]

    records = [
        metric("RECOMPUTE_RESIDUAL_MEAN_PX", "recomputed forward residual mean",
               recompute.get("residual_mean_px"), "px", MetricCategory.DIAGNOSTIC, "M7", None,
               recompute.get("method", ""), "Independently recomputed mean forward residual.",
               ScientificStatus.DIAGNOSTIC),
        metric("RECOMPUTE_RESIDUAL_MEDIAN_PX", "recomputed forward residual median",
               recompute.get("residual_median_px"), "px", MetricCategory.DIAGNOSTIC, "M7", None,
               recompute.get("method", ""), "Independently recomputed median forward residual.",
               ScientificStatus.DIAGNOSTIC),
        metric("RECOMPUTE_RESIDUAL_P95_PX", "recomputed forward residual p95",
               recompute.get("residual_p95_px"), "px", MetricCategory.DIAGNOSTIC, "M7", None,
               recompute.get("method", ""), "Independently recomputed p95 forward residual.",
               ScientificStatus.DIAGNOSTIC),
        metric("RECOMPUTE_SYMMETRIC_TRANSFER_MAX_PX", "recomputed symmetric transfer max",
               recompute.get("symmetric_transfer_max_px"), "px", MetricCategory.DIAGNOSTIC, "M7", None,
               recompute.get("method", ""), "Independently recomputed max symmetric transfer.",
               ScientificStatus.DIAGNOSTIC),
        metric("RECOMPUTE_INLIER_COUNT", "recomputed inlier count (threshold policy)",
               recompute.get("inlier_count"), "count", MetricCategory.DIAGNOSTIC, "M7", None,
               recompute.get("method", ""),
               f"Count of forward residuals below policy threshold {recompute.get('inlier_threshold_px')} px.",
               ScientificStatus.DIAGNOSTIC),
        metric("RECOMPUTE_VALID_PROJECTION_COUNT", "correspondences with finite projection",
               recompute.get("valid_projection_count"), "count", MetricCategory.DIAGNOSTIC, "M7", None,
               recompute.get("method", ""), "Correspondences whose forward projection is finite.",
               ScientificStatus.DIAGNOSTIC),
        metric("RECOMPUTE_MISMATCH", "recomputation mismatch diagnostics",
               recompute.get("match_mismatch") or None, None, MetricCategory.DIAGNOSTIC, "M7", None,
               "consistency comparison against recorded M6 diagnostics",
               "Reports divergence between independent recomputation and recorded M6 numbers.",
               ScientificStatus.DIAGNOSTIC,
               status=MetricStatus.AVAILABLE if recompute.get("match_mismatch") else MetricStatus.NOT_APPLICABLE),
    ]
    return records