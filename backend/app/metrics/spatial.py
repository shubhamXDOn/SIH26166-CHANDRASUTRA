"""M7 spatial metrics — read from real M5 artefacts (summary.json, reliability_map.json).

Values are measurements of the reliability grid, never scientific accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.metrics.schema import metric, unavailable_metric
from backend.app.metrics.states import MetricCategory, MetricStatus, ScientificStatus


def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def collect_spatial_metrics(m5_run: Path | None, data_root: Path) -> list[dict]:
    records: list[dict] = []
    rel = None
    if m5_run is not None and m5_run.is_relative_to(data_root):
        rel = m5_run.relative_to(data_root).as_posix()

    summary = _read_json(m5_run / "summary.json", {}) if m5_run else {}
    if not summary:
        for mid, name, unit, cat, sci in [
            ("SPATIAL_GRID_ROWS", "reliability grid rows", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
            ("SPATIAL_GRID_COLS", "reliability grid cols", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING),
            ("SPATIAL_CELLS_OBSERVED", "scene cells observed", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
            ("SPATIAL_RELIABLE_CELLS", "reliable cells", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
            ("SPATIAL_SUPPORTED_CELLS", "supported cells", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
            ("SPATIAL_CONNECTED_COMPONENTS", "connected components", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.MEASUREMENT),
            ("SPATIAL_LARGEST_COMPONENT_RATIO", "largest component coverage ratio", "ratio", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
            ("SPATIAL_EDGE_FRACTION", "edge-touching cell fraction", "fraction", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
            ("SPATIAL_VERIFIED_INLIER_COUNT", "verified inliers in scene", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT),
            ("SPATIAL_MEAN_DENSITY", "mean correspondence density per observed cell", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
            ("SPATIAL_SELECTION_OUTCOME", "M5 selection outcome", None, MetricCategory.VALIDATION, ScientificStatus.MEASUREMENT),
            ("SPATIAL_SELECTION_COVERAGE", "selected/observed cell coverage", "fraction", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC),
            ("SPATIAL_CAPPED_AT_LIMIT", "selection capped at configured limit", None, MetricCategory.VALIDATION, ScientificStatus.ENGINEERING),
        ]:
            records.append(unavailable_metric(
                mid, name, unit, cat, "M5", None, "no M5 spatial summary artefact present",
                "Spatial evidence unavailable.", MetricStatus.BLOCKED))
        return records

    grid = summary.get("grid") or {}
    reliability = summary.get("reliability") or {}
    frag = (summary.get("fragmentation") or {})
    boundary = (summary.get("boundary") or {})
    scene = summary.get("scene") or {}
    selection = summary.get("selection") or {}

    def _add(mid, name, unit, cat, sci, value, status, method, interpretation):
        records.append(metric(
            mid, name, value, unit, cat, "M5", (rel + "/summary.json") if rel else None,
            method, interpretation, sci, status=status))

    _add("SPATIAL_GRID_ROWS", "reliability grid rows", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING,
         grid.get("rows"), MetricStatus.AVAILABLE if grid.get("rows") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'grid.rows'", "Reliability grid height in cells (policy, not science).")
    _add("SPATIAL_GRID_COLS", "reliability grid cols", "count", MetricCategory.OBSERVATION, ScientificStatus.ENGINEERING,
         grid.get("cols"), MetricStatus.AVAILABLE if grid.get("cols") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'grid.cols'", "Reliability grid width in cells (policy, not science).")
    _add("SPATIAL_CELLS_OBSERVED", "scene cells observed", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         reliability.get("scene_cells_observed"), MetricStatus.AVAILABLE if reliability.get("scene_cells_observed") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'reliability.scene_cells_observed'", "Cells receiving any verified evidence.")
    _add("SPATIAL_RELIABLE_CELLS", "reliable cells", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         reliability.get("reliable_cells"), MetricStatus.AVAILABLE if reliability.get("reliable_cells") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'reliability.reliable_cells'", "Cells meeting reliability criteria in trusted tiles.")
    _add("SPATIAL_SUPPORTED_CELLS", "supported cells", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         reliability.get("supported_cells"), MetricStatus.AVAILABLE if reliability.get("supported_cells") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'reliability.supported_cells'", "Neighborhood-supported reliable cells.")
    _add("SPATIAL_CONNECTED_COMPONENTS", "connected components", "count", MetricCategory.DIAGNOSTIC, ScientificStatus.MEASUREMENT,
         reliability.get("connected_components"), MetricStatus.AVAILABLE if reliability.get("connected_components") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'reliability.connected_components'", "Connected reliable-cell regions.")
    _add("SPATIAL_LARGEST_COMPONENT_RATIO", "largest component coverage ratio", "ratio", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         frag.get("largest_component_ratio"), MetricStatus.AVAILABLE if frag.get("largest_component_ratio") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'fragmentation.largest_component_ratio'", "Spatial concentration of evidence (not an accuracy metric).")
    _add("SPATIAL_EDGE_FRACTION", "edge-touching cell fraction", "fraction", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         boundary.get("edge_fraction"), MetricStatus.AVAILABLE if boundary.get("edge_fraction") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'boundary.edge_fraction'", "Fraction of cells touching the scene boundary.")
    _add("SPATIAL_VERIFIED_INLIER_COUNT", "verified inliers in scene", "count", MetricCategory.MEASUREMENT, ScientificStatus.MEASUREMENT,
         scene.get("verified_inlier_count"), MetricStatus.AVAILABLE if scene.get("verified_inlier_count") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'scene.verified_inlier_count'", "Total verified inlier correspondences in the scene.")
    _add("SPATIAL_SELECTION_OUTCOME", "M5 selection outcome", None, MetricCategory.VALIDATION, ScientificStatus.MEASUREMENT,
         selection.get("outcome"), MetricStatus.AVAILABLE if selection.get("outcome") else MetricStatus.BLOCKED,
         "read from spatial summary.json 'selection.outcome'", "M5 selection outcome (SELECTED/INSUFFICIENT).")
    _add("SPATIAL_SELECTION_COVERAGE", "selected/observed cell coverage", "fraction", MetricCategory.DIAGNOSTIC, ScientificStatus.DIAGNOSTIC,
         None, MetricStatus.NOT_APPLICABLE, "selected_cells / scene_cells_observed",
         "Fraction of observed scene covered by the selected region.")
    observed = reliability.get("scene_cells_observed")
    selected_cells = selection.get("selected_cells")
    if observed not in (None, 0) and selected_cells is not None:
        records[-1] = metric(
            "SPATIAL_SELECTION_COVERAGE", "selected/observed cell coverage",
            round(float(selected_cells) / float(observed), 6), "fraction",
            MetricCategory.DIAGNOSTIC, "M5", (rel + "/summary.json") if rel else None,
            "selected_cells / scene_cells_observed",
            "Fraction of observed scene covered by the selected region.",
            ScientificStatus.DIAGNOSTIC, status=MetricStatus.AVAILABLE)
    _add("SPATIAL_CAPPED_AT_LIMIT", "selection capped at configured limit", None, MetricCategory.VALIDATION, ScientificStatus.ENGINEERING,
         bool(selection.get("capped_at_limit", False)), MetricStatus.AVAILABLE if selection.get("capped_at_limit") is not None else MetricStatus.BLOCKED,
         "read from spatial summary.json 'selection.capped_at_limit'", "True if selection hit the configured cap.")

    # mean spatial density over observed cells (from reliability_map.json)
    mean_density = None
    density_status = MetricStatus.BLOCKED
    density_method = "read from spatial reliability_map.json 'cells[].spatial_density'"
    rmap = _read_json(m5_run / "reliability_map.json", {}) if m5_run else {}
    cells = rmap.get("cells") or []
    observed_cells = [c for c in cells if c.get("observed") and c.get("spatial_density") is not None]
    if observed_cells:
        mean_density = round(float(sum(float(c["spatial_density"]) for c in observed_cells) / len(observed_cells)), 6)
        density_status = MetricStatus.AVAILABLE
    elif cells:
        density_status = MetricStatus.NOT_APPLICABLE
    records.append(metric(
        "SPATIAL_MEAN_DENSITY", "mean correspondence density per observed cell", mean_density,
        "count", MetricCategory.DIAGNOSTIC, "M5",
        (rel + "/reliability_map.json") if rel else None,
        density_method, "Average verified-inlier density across observed cells.",
        ScientificStatus.DIAGNOSTIC, status=density_status))

    return records