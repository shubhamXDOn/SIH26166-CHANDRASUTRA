"""M7 evidence funnel — M3 candidates -> M4 trusted -> M5 selected -> M6 fitted.

All numbers are read from real artefacts; a missing/blocked stage produces
NOT_RUN/BLOCKED metrics with None values, never fabricated zeros.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from backend.app.metrics.schema import metric, unavailable_metric
from backend.app.metrics.states import (
    MetricCategory,
    MetricStatus,
    ScientificStatus,
)


def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def collect_funnel_metrics(
    m3_run: Path | None,
    m4_run: Path | None,
    m5_run: Path | None,
    m6_run: Path | None,
    data_root: Path,
) -> list[dict]:
    """Produce the evidence-funnel metric records."""

    records: list[dict] = []

    # ---- M3 candidates ---------------------------------------------------- #
    if m3_run is None:
        records.append(unavailable_metric(
            "FUNNEL_M3_TILES", "matched tiles", "count", MetricCategory.OBSERVATION,
            "M3", None, "no M3 matching run artefact present",
            "Matcher evidence unavailable for this pair.", MetricStatus.BLOCKED))
        records.append(unavailable_metric(
            "FUNNEL_M3_CANDIDATES", "M3 candidate correspondences", "count", MetricCategory.OBSERVATION,
            "M3", None, "no M3 matching run artefact present",
            "Matcher evidence unavailable for this pair.", MetricStatus.BLOCKED))
        records.append(unavailable_metric(
            "FUNNEL_M3_SUCCESS_TILES", "M3 tiles with candidates", "count", MetricCategory.OBSERVATION,
            "M3", None, "no M3 matching run artefact present",
            "Matcher evidence unavailable for this pair.", MetricStatus.BLOCKED))
    else:
        summary = _read_json(m3_run / "summary.json", {})
        rel = None
        if m3_run.is_relative_to(data_root):
            rel = m3_run.relative_to(data_root).as_posix() + "/summary.json"
        tiles = summary.get("tiles")
        candidates = summary.get("total_candidates")
        outcomes = summary.get("outcomes") or {}
        records.append(metric(
            "FUNNEL_M3_TILES", "matched tiles", tiles, "count", MetricCategory.OBSERVATION,
            "M3", rel, "read from matching summary.json 'tiles'",
            "Tiles offered to the adaptive matcher (raw candidate stage).",
            ScientificStatus.ENGINEERING,
            status=MetricStatus.AVAILABLE if tiles is not None else MetricStatus.BLOCKED))
        records.append(metric(
            "FUNNEL_M3_CANDIDATES", "M3 candidate correspondences", candidates, "count", MetricCategory.OBSERVATION,
            "M3", rel, "read from matching summary.json 'total_candidates'",
            "Raw matcher output before any geometric verification.",
            ScientificStatus.ENGINEERING,
            status=MetricStatus.AVAILABLE if candidates is not None else MetricStatus.BLOCKED))
        successes = outcomes.get("SUCCESS")
        records.append(metric(
            "FUNNEL_M3_SUCCESS_TILES", "M3 tiles with candidates", successes, "count", MetricCategory.OBSERVATION,
            "M3", rel,
            "read from matching summary.json 'outcomes.SUCCESS'",
            "Tiles that produced at least one candidate set.",
            ScientificStatus.ENGINEERING,
            status=MetricStatus.AVAILABLE if successes is not None else MetricStatus.NOT_APPLICABLE))

    # ---- M4 trusted ------------------------------------------------------- #
    trusted_tiles = rejected_tiles = trusted_corres = None
    m4_rel = None
    m4_reasons: dict = {}
    if m4_run is not None and m4_run.is_relative_to(data_root):
        m4_rel = m4_run.relative_to(data_root).as_posix()
    if m4_run is None or not (m4_run / "summary.json").is_file():
        records.append(unavailable_metric(
            "FUNNEL_M4_TRUSTED_TILES", "trusted tiles", "count", MetricCategory.VALIDATION,
            "M4", None, "no M4 trust gate artefact present",
            "Trust gate evidence unavailable.", MetricStatus.BLOCKED))
        records.append(unavailable_metric(
            "FUNNEL_M4_REJECTED_TILES", "rejected tiles", "count", MetricCategory.VALIDATION,
            "M4", None, "no M4 trust gate artefact present",
            "Trust gate evidence unavailable.", MetricStatus.BLOCKED))
        records.append(unavailable_metric(
            "FUNNEL_M4_TRUSTED_CORRESPONDENCES", "trusted correspondences", "count", MetricCategory.MEASUREMENT,
            "M4", None, "no M4 trust gate artefact present",
            "Trusted correspondence evidence unavailable.", MetricStatus.BLOCKED))
    else:
        summary = _read_json(m4_run / "summary.json", {})
        trusted_tiles = summary.get("trusted_tiles")
        rejected_tiles = summary.get("rejected_tiles", summary.get("failed_tiles"))
        m4_reasons = summary.get("reason_distribution") or {}
        npz = m4_run / "trusted_correspondences.npz"
        if npz.is_file():
            try:
                with np.load(str(npz), allow_pickle=False) as data:
                    keys = set(data.files)
                    if {"x_a", "y_a", "x_b", "y_b"}.issubset(keys):
                        trusted_corres = int(len(np.asarray(data["x_a"]).ravel()))
            except Exception:  # noqa: BLE001
                trusted_corres = None
        if trusted_corres is None:
            tile_trust = _read_json(m4_run / "tile_trust.json", {})
            trusted_corres = sum(
                int((t.get("model") or {}).get("inlier_count") or 0)
                for t in tile_trust.get("tiles", [])
                if t.get("trust_state") == "TRUSTED")
        records.append(metric(
            "FUNNEL_M4_TRUSTED_TILES", "trusted tiles", trusted_tiles, "count", MetricCategory.VALIDATION,
            "M4", (m4_rel + "/summary.json") if m4_rel else None,
            "read from trust summary.json 'trusted_tiles'",
            "Tiles that passed the independent geometric Trust Gate.",
            ScientificStatus.MEASUREMENT,
            status=MetricStatus.AVAILABLE if trusted_tiles is not None else MetricStatus.BLOCKED))
        records.append(metric(
            "FUNNEL_M4_REJECTED_TILES", "rejected tiles", rejected_tiles, "count", MetricCategory.VALIDATION,
            "M4", (m4_rel + "/summary.json") if m4_rel else None,
            "read from trust summary.json 'rejected_tiles'/'failed_tiles'",
            "Tiles rejected or failed at the Trust Gate.",
            ScientificStatus.MEASUREMENT,
            status=MetricStatus.AVAILABLE if rejected_tiles is not None else MetricStatus.BLOCKED))
        records.append(metric(
            "FUNNEL_M4_TRUSTED_CORRESPONDENCES", "trusted correspondences", trusted_corres, "count",
            MetricCategory.MEASUREMENT, "M4",
            (m4_rel + "/trusted_correspondences.npz") if m4_rel else None,
            "row count of trusted_correspondences.npz (fallback: sum of tile_trust model inlier counts)",
            "Correspondences surviving the Trust Gate across trusted tiles.",
            ScientificStatus.MEASUREMENT,
            status=MetricStatus.AVAILABLE if trusted_corres is not None else MetricStatus.BLOCKED))

    # ---- M5 selected ------------------------------------------------------ #
    selected_corres = None
    m5_rel = m5_selection_rel = None
    if m5_run is not None and m5_run.is_relative_to(data_root):
        m5_rel = m5_run.relative_to(data_root).as_posix()
    selection: dict = {}
    if m5_run is not None:
        selection = _read_json(m5_run / "selection.json", {})
        if selection:
            m5_selection_rel = (m5_rel + "/selection.json") if m5_rel else None
    if not selection:
        records.append(unavailable_metric(
            "FUNNEL_M5_SELECTED_CORRESPONDENCES", "spatially selected correspondences", "count",
            MetricCategory.MEASUREMENT, "M5", None, "no M5 selection.json artefact present",
            "Spatial selection evidence unavailable.", MetricStatus.BLOCKED))
    else:
        selected_corres = selection.get("selected_correspondence_count")
        records.append(metric(
            "FUNNEL_M5_SELECTED_CORRESPONDENCES", "spatially selected correspondences", selected_corres,
            "count", MetricCategory.MEASUREMENT, "M5", m5_selection_rel,
            "read from spatial selection.json 'selected_correspondence_count'",
            "Correspondences selected by M5 reliability-aware region selection.",
            ScientificStatus.MEASUREMENT,
            status=MetricStatus.AVAILABLE if selected_corres is not None else MetricStatus.BLOCKED))

    # ---- M6 fitted -------------------------------------------------------- #
    fitted = None
    m6_rel = None
    if m6_run is not None and m6_run.is_relative_to(data_root):
        m6_rel = m6_run.relative_to(data_root).as_posix()
    diagnostics = _read_json(m6_run / "diagnostics.json", {}) if m6_run else {}
    if not diagnostics:
        records.append(unavailable_metric(
            "FUNNEL_M6_REGISTERED_CORRESPONDENCES", "correspondences used in transform fit", "count",
            MetricCategory.MEASUREMENT, "M6", None, "no M6 diagnostics.json artefact present",
            "Registration evidence unavailable.", MetricStatus.BLOCKED))
    else:
        fitted = (diagnostics.get("correspondences") or {}).get("valid_for_fit")
        records.append(metric(
            "FUNNEL_M6_REGISTERED_CORRESPONDENCES", "correspondences used in transform fit", fitted,
            "count", MetricCategory.MEASUREMENT, "M6",
            (m6_rel + "/diagnostics.json") if m6_rel else None,
            "read from registration diagnostics.json 'correspondences.valid_for_fit'",
            "Correspondences that actually entered the transform fit.",
            ScientificStatus.MEASUREMENT,
            status=MetricStatus.AVAILABLE if fitted is not None else MetricStatus.BLOCKED))

    # ---- attrition distribution (real reason codes only) ------------------- #
    m5_reason_counts = selection.get("reason_counts") or {}
    attrition = {}
    attrition.update({str(k): int(v) for k, v in (m4_reasons or {}).items()})
    attrition.update({str(k): int(v) for k, v in m5_reason_counts.items()})
    records.append(metric(
        "ATTENTION_DISTRIBUTION", "rejection/attrition by reason code", attrition or None,
        None, MetricCategory.OBSERVATION, "M4/M5",
        (m4_rel + "/summary.json") if m4_rel else None,
        "merged from M4 reason_distribution and M5 selection.reason_counts",
        "Real rejection/attrition categories with per-code counts; no fabricated categories.",
        ScientificStatus.MEASUREMENT,
        status=MetricStatus.AVAILABLE if attrition else MetricStatus.NOT_APPLICABLE))

    # ---- retention ratios (engineering diagnostics) ------------------------ #
    def _ratio(num, den):
        if num is None or den in (None, 0):
            return None
        try:
            if float(den) <= 0:
                return None
            return round(float(num) / float(den), 6)
        except (TypeError, ValueError):
            return None

    records.append(metric(
        "FUNNEL_M3_TO_M4_RETENTION", "candidate -> trusted retention ratio", _ratio(trusted_corres, candidates),
        "ratio", MetricCategory.DIAGNOSTIC, "M3/M4",
        (m4_rel + "/trusted_correspondences.npz") if m4_rel else None,
        "trusted_correspondences / total_candidates (engineering diagnostic, not accuracy)",
        "Rough retention of evidence mass from raw candidates to trusted correspondence.",
        ScientificStatus.ENGINEERING,
        status=MetricStatus.AVAILABLE if (trusted_corres is not None and candidates) else MetricStatus.NOT_APPLICABLE))
    records.append(metric(
        "FUNNEL_M4_TO_M5_RETENTION", "trusted -> selected retention ratio", _ratio(selected_corres, trusted_corres),
        "ratio", MetricCategory.DIAGNOSTIC, "M4/M5",
        (m5_rel + "/selection.json") if m5_rel else None,
        "selected_correspondence_count / trusted_correspondences (reliability-aware reduction)",
        "Fraction of trusted correspondence mass kept by spatial selection.",
        ScientificStatus.ENGINEERING,
        status=MetricStatus.AVAILABLE if (selected_corres is not None and trusted_corres) else MetricStatus.NOT_APPLICABLE))
    records.append(metric(
        "FUNNEL_M5_TO_M6_RETENTION", "selected -> fitted retention ratio", _ratio(fitted, selected_corres),
        "ratio", MetricCategory.DIAGNOSTIC, "M5/M6",
        (m6_rel + "/diagnostics.json") if m6_rel else None,
        "valid_for_fit / selected_correspondence_count",
        "Fraction of selected evidence that participated in the transform fit.",
        ScientificStatus.ENGINEERING,
        status=MetricStatus.AVAILABLE if (fitted is not None and selected_corres) else MetricStatus.NOT_APPLICABLE))

    return records