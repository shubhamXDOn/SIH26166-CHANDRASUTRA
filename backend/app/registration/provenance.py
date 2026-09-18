"""M6 provenance chain: M2 -> M3 -> M4 -> M5 -> M6 with POSIX relative paths + sha256."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.app.config import rfc3339_now


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _artifact(path: Path, kind: str, data_root: Path) -> dict:
    rel = path.relative_to(data_root).as_posix()
    return {
        "path": rel,
        "kind": kind,
        "sha256": sha256_of(path),
    }


def _json_abs(path: str | None) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def build_provenance(
    pair_id: str,
    data_root: Path,
    *,
    m2_run_dir: Path,
    m3_run_dir: Path,
    m4_run_dir: Path,
    m5_run_dir: Path,
    m6_run_dir: Path,
    m6_status: dict,
) -> dict:
    chain = []

    if m2_run_dir is not None:
        m2_summary = _json_abs(str(m2_run_dir / "summary.json"))
        chain.append({
            "milestone": "M2",
            "role": "sensor-native scene condition tiles + overlap geometry",
            "configuration_id": (m2_summary or {}).get("configuration_id"),
            "artifacts": [
                _artifact(m2_run_dir / "summary.json", "m2_summary", data_root)
                if (m2_run_dir / "summary.json").is_file() else None,
                _artifact(m2_run_dir / "diagnostics" / "overlap.json", "m2_overlap", data_root)
                if (m2_run_dir / "diagnostics" / "overlap.json").is_file() else None,
                _artifact(m2_run_dir / "crops" / "tiles.json", "m2_tiles", data_root)
                if (m2_run_dir / "crops" / "tiles.json").is_file() else None,
            ],
            "note": "No resampling, per M2 policy",
        })

    if m3_run_dir is not None:
        m3_summary = _json_abs(str(m3_run_dir / "summary.json"))
        chain.append({
            "milestone": "M3",
            "role": "adaptive matcher candidate correspondences per tile",
            "configuration_id": (m3_summary or {}).get("configuration_id"),
            "artifacts": [
                _artifact(m3_run_dir / "summary.json", "m3_summary", data_root)
                if (m3_run_dir / "summary.json").is_file() else None,
            ],
            "note": "Candidate correspondences are raw matcher output.",
        })

    if m4_run_dir is not None:
        m4_status = _json_abs(str(m4_run_dir / "trust_status.json"))
        chain.append({
            "milestone": "M4",
            "role": "independent geometric verification / trust gate",
            "configuration_id": (m4_status or {}).get("trust_configuration_id"),
            "artifacts": [
                _artifact(m4_run_dir / "trust_status.json", "m4_trust_status", data_root)
                if (m4_run_dir / "trust_status.json").is_file() else None,
                _artifact(m4_run_dir / "tile_trust.json", "m4_tile_trust", data_root)
                if (m4_run_dir / "tile_trust.json").is_file() else None,
            ],
            "note": "Only trusted tiles feed M5.",
        })

    if m5_run_dir is not None:
        m5_status = _json_abs(str(m5_run_dir / "status.json"))
        chain.append({
            "milestone": "M5",
            "role": "spatial reliability & reliability-aware selection",
            "configuration_id": (m5_status or {}).get("spatial_reliability_configuration_id"),
            "artifacts": [
                _artifact(m5_run_dir / "status.json", "m5_status", data_root)
                if (m5_run_dir / "status.json").is_file() else None,
                _artifact(m5_run_dir / "selected_correspondences.npz", "m5_selected_correspondences", data_root)
                if (m5_run_dir / "selected_correspondences.npz").is_file() else None,
                _artifact(m5_run_dir / "selection.json", "m5_selection", data_root)
                if (m5_run_dir / "selection.json").is_file() else None,
            ],
            "note": "Reliability-aware selection restricts evidence; it is not a scientific claim.",
        })

    if m6_run_dir is not None:
        chain.append({
            "milestone": "M6",
            "role": "registration engine & verified alignment",
            "configuration_id": (m6_status or {}).get("registration_configuration_id"),
            "artifacts": [
                _artifact(m6_run_dir / "status.json", "m6_status", data_root)
                if (m6_run_dir / "status.json").is_file() else None,
                _artifact(m6_run_dir / "transform.json", "m6_transform", data_root)
                if (m6_run_dir / "transform.json").is_file() else None,
            ],
            "note": "Transform fit on M5-selected evidence; diagnostics are measurements, not proof.",
        })

    return {
        "pair_id": pair_id,
        "generated_at": rfc3339_now(),
        "chain": chain,
        "note": "No absolute/home paths; sha256 over every referenced artifact.",
    }