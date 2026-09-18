"""M7 metrics manifest + M2->M7 provenance (POSIX-relative paths, SHA-256 only)."""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.config import rfc3339_now
from backend.app.registration.provenance import _artifact, sha256_of


def _read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def build_metrics_manifest(
    pair_id: str,
    metrics_config_id: str,
    metrics_config_version: str,
    run_dir: Path,
    data_root: Path,
) -> dict:
    """Manifest over the M7 artefacts written in run_dir (not the manifest itself)."""
    artifact_paths = [
        (run_dir / "experiment.json", "experiment"),
        (run_dir / "status.json", "status"),
        (run_dir / "summary.json", "summary"),
        (run_dir / "report.json", "report_json"),
        (run_dir / "report.md", "report_markdown"),
        (run_dir / "registration_metrics.json", "registration_metrics"),
        (run_dir / "provenance.json", "provenance"),
    ]
    artifacts = []
    for path, kind in artifact_paths:
        if path.is_file():
            artifacts.append({
                "path": path.relative_to(data_root).as_posix(),
                "kind": kind,
                "sha256": sha256_of(path),
            })
    return {
        "pair_id": pair_id,
        "metrics_configuration_id": metrics_config_id,
        "metrics_configuration_version": metrics_config_version,
        "generated_at": rfc3339_now(),
        "artifacts": sorted(artifacts, key=lambda a: a["path"]),
        "note": "Metrics artefacts recorded with SHA-256; paths are POSIX-relative to the data root.",
    }


def build_metrics_provenance(
    pair_id: str,
    data_root: Path,
    *,
    metrics_config_id: str = "MT-M7-001",
    m2_run_dir: Path | None,
    m3_run_dir: Path | None,
    m4_run_dir: Path | None,
    m5_run_dir: Path | None,
    m6_run_dir: Path | None,
    m7_run_dir: Path,
) -> dict:
    """Full M2 -> M7 chain referencing the artefacts metrics consumed."""
    chain: list[dict] = []

    def _node(milestone, role, run_dir: Path | None, configuration_id: str | None, artifacts: list[dict], note: str):
        if run_dir is None:
            return
        present = [a for a in artifacts if a]
        chain.append({
            "milestone": milestone,
            "role": role,
            "configuration_id": configuration_id,
            "artifacts": present,
            "note": note,
        })

    if m2_run_dir is not None:
        _node("M2", "sensor-native scene conditioning + overlap geometry", m2_run_dir,
              m2_run_dir.name, [
                  _artifact(m2_run_dir / "processing_status.json", "m2_status", data_root) if (m2_run_dir / "processing_status.json").is_file() else None,
                  _artifact(m2_run_dir / "diagnostics" / "overlap.json", "m2_overlap", data_root) if (m2_run_dir / "diagnostics" / "overlap.json").is_file() else None,
              ], "Per-pair conditioning state consumed by the funnel.")
    if m3_run_dir is not None:
        _node("M3", "adaptive matcher candidate correspondences", m3_run_dir,
              m3_run_dir.name, [
                  _artifact(m3_run_dir / "summary.json", "m3_summary", data_root) if (m3_run_dir / "summary.json").is_file() else None,
              ], "Total candidate counts consumed by the funnel.")
    if m4_run_dir is not None:
        _node("M4", "independent geometric verification / trust gate", m4_run_dir,
              m4_run_dir.name, [
                  _artifact(m4_run_dir / "summary.json", "m4_summary", data_root) if (m4_run_dir / "summary.json").is_file() else None,
                  _artifact(m4_run_dir / "trusted_correspondences.npz", "m4_trusted_correspondences", data_root) if (m4_run_dir / "trusted_correspondences.npz").is_file() else None,
              ], "Trusted/trusted-correspondence counts consumed by the funnel.")
    if m5_run_dir is not None:
        _node("M5", "spatial reliability & selection", m5_run_dir,
              m5_run_dir.name, [
                  _artifact(m5_run_dir / "summary.json", "m5_summary", data_root) if (m5_run_dir / "summary.json").is_file() else None,
                  _artifact(m5_run_dir / "reliability_map.json", "m5_reliability_map", data_root) if (m5_run_dir / "reliability_map.json").is_file() else None,
                  _artifact(m5_run_dir / "selection.json", "m5_selection", data_root) if (m5_run_dir / "selection.json").is_file() else None,
                  _artifact(m5_run_dir / "mapping.json", "m5_mapping", data_root) if (m5_run_dir / "mapping.json").is_file() else None,
                  _artifact(m5_run_dir / "selected_correspondences.npz", "m5_selected_correspondences", data_root) if (m5_run_dir / "selected_correspondences.npz").is_file() else None,
              ], "Spatial summary, reliability grid and selected evidence consumed by M7.")
    if m6_run_dir is not None:
        _node("M6", "registration engine & verified alignment", m6_run_dir,
              m6_run_dir.name, [
                  _artifact(m6_run_dir / "diagnostics.json", "m6_diagnostics", data_root) if (m6_run_dir / "diagnostics.json").is_file() else None,
                  _artifact(m6_run_dir / "transform.json", "m6_transform", data_root) if (m6_run_dir / "transform.json").is_file() else None,
                  _artifact(m6_run_dir / "validation.json", "m6_validation", data_root) if (m6_run_dir / "validation.json").is_file() else None,
                  _artifact(m6_run_dir / "summary.json", "m6_summary", data_root) if (m6_run_dir / "summary.json").is_file() else None,
              ], "Transform, diagnostics and validation consumed and independently recomputed by M7.")

    chain.append({
        "milestone": "M7",
        "role": "quantitative metrics, reproducible experiment reports & scientific diagnostics",
        "configuration_id": metrics_config_id,
        "artifacts": [a for a in [
            _artifact(m7_run_dir / "experiment.json", "m7_experiment", data_root) if (m7_run_dir / "experiment.json").is_file() else None,
            _artifact(m7_run_dir / "report.json", "m7_report_json", data_root) if (m7_run_dir / "report.json").is_file() else None,
            _artifact(m7_run_dir / "report.md", "m7_report_markdown", data_root) if (m7_run_dir / "report.md").is_file() else None,
            _artifact(m7_run_dir / "summary.json", "m7_summary", data_root) if (m7_run_dir / "summary.json").is_file() else None,
        ] if a],
        "note": "All metrics are measurements, never scientific accuracy claims.",
    })

    return {
        "pair_id": pair_id,
        "generated_at": rfc3339_now(),
        "chain": [n for n in chain],
        "note": "No absolute/home paths; sha256 over every referenced artefact.",
    }