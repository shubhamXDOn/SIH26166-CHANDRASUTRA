"""M6 registration manifest (relative paths + SHA-256, no absolute paths)."""

from __future__ import annotations

from backend.app.config import rfc3339_now


def build_registration_manifest(
    pair_id: str,
    registration_config_id: str,
    registration_config_version: str,
    proc_cfg: str,
    matcher_cfg: str,
    trust_cfg: str,
    spatial_cfg: str,
    summary: dict,
    artifacts: list[dict],
    scientific_note: str,
) -> dict:
    return {
        "pair_id": pair_id,
        "registration_configuration_id": registration_config_id,
        "registration_configuration_version": registration_config_version,
        "processing_configuration_id": proc_cfg,
        "matcher_configuration_id": matcher_cfg,
        "trust_configuration_id": trust_cfg,
        "spatial_reliability_configuration_id": spatial_cfg,
        "generated_at": rfc3339_now(),
        "note": "Engineering defaults only; no scientifically validated lunar calibration."
                " Registration diagnostics are measurements, not proof of physical truth.",
        "scientific_note": scientific_note,
        "summary": {
            "state": summary.get("state"),
            "transform_type": summary.get("transform_type"),
            "validation_verdict": summary.get("validation_verdict"),
            "correspondences": summary.get("correspondences"),
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