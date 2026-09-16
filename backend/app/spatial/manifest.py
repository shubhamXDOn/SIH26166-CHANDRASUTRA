"""M5 spatial manifest (relative paths + SHA-256, no absolute paths)."""

from __future__ import annotations

from backend.app.config import rfc3339_now


def build_spatial_manifest(
    pair_id: str,
    spatial_config_id: str,
    spatial_config_version: str,
    coordinate_space: str,
    proc_cfg: str,
    matcher_cfg: str,
    trust_cfg: str,
    summary: dict,
    artifacts: list[dict],
) -> dict:
    return {
        "pair_id": pair_id,
        "spatial_reliability_configuration_id": spatial_config_id,
        "spatial_reliability_configuration_version": spatial_config_version,
        "coordinate_space": coordinate_space,
        "processing_configuration_id": proc_cfg,
        "matcher_configuration_id": matcher_cfg,
        "trust_configuration_id": trust_cfg,
        "generated_at": rfc3339_now(),
        "note": "Engineering/policy defaults only; no scientifically tuned lunar thresholds exist yet. "
                "Selection reflects measured spatial evidence, not a scientific alignment claim.",
        "summary": {
            "scene_cells_observed": summary.get("scene_cells_observed", 0),
            "reliable_cells": summary.get("reliable_cells", 0),
            "connected_components": summary.get("connected_components", 0),
            "verified_inlier_count": summary.get("verified_inlier_count", 0),
            "selected_correspondence_count": summary.get("selected_correspondence_count", 0),
            "selection_outcome": summary.get("selection_outcome"),
            "runtime_seconds": round(float(summary.get("runtime_seconds", 0.0)), 4),
        },
        "artifacts": artifacts,
    }


def artifact_spec(relative_path: str, sha256: str, kind: str) -> dict:
    return {
        "path": relative_path,
        "kind": kind,
        "sha256": sha256,
    }