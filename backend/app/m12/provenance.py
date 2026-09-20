"""M12 provenance chain: M1 -> M2 -> ... -> M9 with relative paths + sha256.

Extends the M6 per-stage chain (``registration.provenance``) to cover the whole
scientific surface: pair registration/validation (M1), processing (M2),
matching (M3), trust (M4), spatial (M5), registration (M6), metrics (M7),
deep matcher expansion (M8) and AI explanation evidence (M9). Every referenced
artefact is hashed; every path is POSIX-relative to the data root. Missing
stages yield a ``NOT_RUN`` entry so the builder can be run on a partial system
and report ``PROVENANCE_INCOMPLETE`` honestly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.config import rfc3339_now
from backend.app.registration.provenance import sha256_of


def _json_abs(path: Path) -> dict | None:
    import json

    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _art(path: Path | None, kind: str, data_root: Path) -> dict | None:
    if path is None or not path.is_file():
        return None
    rel = path.relative_to(data_root).as_posix()
    return {"path": rel, "kind": kind, "sha256": sha256_of(path)}


def _stage(milestone: str, role: str, run: Path | None, data_root: Path,
           status: str, *, artifacts: list[dict | None], note: str,
           configuration_id: str | None = None) -> dict[str, Any]:
    return {
        "milestone": milestone,
        "role": role,
        "status": status,
        "configuration_id": configuration_id,
        "artifacts": [a for a in artifacts if a is not None],
        "note": note,
    }


def _json_config_id(path: Path, keys: list[str]) -> str | None:
    data = _json_abs(path)
    if not data:
        return None
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return str(cur) if cur is not None else None


def build_full_provenance(pair_id: str, settings: Any) -> dict[str, Any]:
    """Assemble the M1..M9 provenance chain for a pair."""
    data_root: Path = settings.data_root_path
    chain: list[dict[str, Any]] = []
    missing: list[str] = []

    # --- M1 pair registration / validation ---------------------------------
    reg = data_root / "metadata" / "pairs.json"
    val = data_root / "metadata" / "pair_validation.json"
    if reg.is_file():
        chain.append(_stage(
            "M1", "pair registration & validation", reg.parent, data_root,
            "COMPLETE",
            artifacts=[_art(reg, "m1_pairs", data_root), _art(val, "m1_validation", data_root)],
            note="Pair identity, product metadata, raw SHA-256 recorded at registration.",
        ))
    else:
        missing.append("M1")
        chain.append(_stage("M1", "pair registration & validation", None, data_root, "NOT_RUN",
                            artifacts=[], note="No metadata/pairs.json present."))

    # --- M2 processing -----------------------------------------------------
    try:
        from backend.app.processing.service import ProcessingService
        proc_run = ProcessingService(settings).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        proc_run = None
    if proc_run is not None:
        cfg = _json_config_id(proc_run / "processing_manifest.json", ["configuration", "configuration_id"])
        chain.append(_stage(
            "M2", "sensor-native scene condition tiles + overlap geometry", proc_run, data_root,
            "COMPLETE",
            configuration_id=cfg,
            artifacts=[
                _art(proc_run / "processing_manifest.json", "m2_manifest", data_root),
                _art(proc_run / "diagnostics" / "overlap.json", "m2_overlap", data_root),
                _art(proc_run / "crops" / "tiles.json", "m2_tiles", data_root),
            ],
            note="No resampling, per M2 policy.",
        ))
    else:
        missing.append("M2")
        chain.append(_stage("M2", "sensor-native scene condition tiles + overlap geometry",
                            None, data_root, "NOT_RUN", artifacts=[], note="No processing run."))

    # --- M3 matching -------------------------------------------------------
    try:
        from backend.app.matching.service import MatchingService
        m3_run = MatchingService(settings).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        m3_run = None
    if m3_run is not None:
        cfg = _json_config_id(m3_run / "summary.json", ["configuration_id"])
        chain.append(_stage(
            "M3", "adaptive matcher candidate correspondences per tile", m3_run, data_root,
            "COMPLETE",
            configuration_id=cfg,
            artifacts=[
                _art(m3_run / "matching_status.json", "m3_status", data_root),
                _art(m3_run / "summary.json", "m3_summary", data_root),
                _art(m3_run / "candidates" / "candidates.json", "m3_candidates_index", data_root),
            ],
            note="Candidate correspondences are raw matcher output, not scientific claims.",
        ))
    else:
        missing.append("M3")
        chain.append(_stage("M3", "adaptive matcher candidate correspondences per tile",
                            None, data_root, "NOT_RUN", artifacts=[], note="No matching run."))

    # --- M4 trust ----------------------------------------------------------
    try:
        from backend.app.trust.service import TrustService
        trust_run = TrustService(data_root).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        trust_run = None
    if trust_run is not None:
        cfg = _json_config_id(trust_run / "trust_status.json", ["trust_configuration_id"])
        chain.append(_stage(
            "M4", "independent geometric verification / trust gate", trust_run, data_root,
            "COMPLETE",
            configuration_id=cfg,
            artifacts=[
                _art(trust_run / "trust_status.json", "m4_trust_status", data_root),
                _art(trust_run / "tile_trust.json", "m4_tile_trust", data_root),
            ],
            note="Only trusted tiles feed M5.",
        ))
    else:
        missing.append("M4")
        chain.append(_stage("M4", "independent geometric verification / trust gate",
                            None, data_root, "NOT_RUN", artifacts=[], note="No trust run."))

    # --- M5 spatial --------------------------------------------------------
    try:
        from backend.app.spatial.service import SpatialService
        m5_cfg = _load_m5_defaults()
        s_run = SpatialService(data_root, m5_cfg=m5_cfg["cfg"], m4_defaults=m5_cfg["m4"]).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        s_run = None
    if s_run is not None:
        cfg = _json_config_id(s_run / "status.json", ["spatial_reliability_configuration_id"])
        chain.append(_stage(
            "M5", "spatial reliability & reliability-aware selection", s_run, data_root,
            "COMPLETE",
            configuration_id=cfg,
            artifacts=[
                _art(s_run / "status.json", "m5_status", data_root),
                _art(s_run / "spatial_manifest.json", "m5_manifest", data_root),
                _art(s_run / "selection.json", "m5_selection", data_root),
                _art(s_run / "selected_correspondences.npz", "m5_selected_correspondences", data_root),
                _art(s_run / "reliability_map.json", "m5_reliability_map", data_root),
            ],
            note="Reliability-aware selection restricts evidence; it is not a scientific claim.",
        ))
    else:
        missing.append("M5")
        chain.append(_stage("M5", "spatial reliability & reliability-aware selection",
                            None, data_root, "NOT_RUN", artifacts=[], note="No spatial run."))

    # --- M6 registration ---------------------------------------------------
    try:
        from backend.app.registration.service import RegistrationService
        m5_cfg = _load_m5_defaults()
        reg_run = RegistrationService(
            data_root, m6_cfg={}, m5_cfg=m5_cfg["cfg"], m4_defaults=m5_cfg["m4"]).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        reg_run = None
    if reg_run is not None:
        cfg = _json_config_id(reg_run / "status.json", ["registration_configuration_id"])
        chain.append(_stage(
            "M6", "registration engine & verified alignment", reg_run, data_root,
            "COMPLETE",
            configuration_id=cfg,
            artifacts=[
                _art(reg_run / "status.json", "m6_status", data_root),
                _art(reg_run / "summary.json", "m6_summary", data_root),
                _art(reg_run / "transform.json", "m6_transform", data_root),
                _art(reg_run / "validation.json", "m6_validation", data_root),
                _art(reg_run / "diagnostics.json", "m6_diagnostics", data_root),
            ],
            note="Transform fit on M5-selected evidence; diagnostics are measurements, not proof.",
        ))
    else:
        missing.append("M6")
        chain.append(_stage("M6", "registration engine & verified alignment",
                            None, data_root, "NOT_RUN", artifacts=[], note="No registration run."))

    # --- M7 metrics --------------------------------------------------------
    try:
        from backend.app.metrics.service import MetricsService
        m5_cfg = _load_m5_defaults()
        met_run = MetricsService(
            data_root, m7_cfg={}, m6_cfg={}, m5_cfg=m5_cfg["cfg"], m4_defaults=m5_cfg["m4"]).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        met_run = None
    if met_run is not None:
        chain.append(_stage(
            "M7", "reproducible experiment metrics", met_run, data_root,
            "COMPLETE",
            configuration_id=_json_config_id(met_run / "status.json", ["metrics_configuration_id"]),
            artifacts=[
                _art(met_run / "status.json", "m7_status", data_root),
                _art(met_run / "report.json", "m7_report", data_root),
                _art(met_run / "report.md", "m7_report_markdown", data_root),
            ],
            note="Metrics are measurements of pipeline evidence; physical accuracy is NOT_AVAILABLE.",
        ))
    else:
        missing.append("M7")
        chain.append(_stage("M7", "reproducible experiment metrics",
                            None, data_root, "NOT_RUN", artifacts=[], note="No metrics run."))

    # --- M8 deep matcher expansion ----------------------------------------
    try:
        from backend.app.matching.m8.service import M8Service
        m8_run = M8Service(settings).find_run_for_pair(pair_id)
    except Exception:  # noqa: BLE001
        m8_run = None
    if m8_run is not None:
        cfg = _json_config_id(m8_run / "m8_status.json", ["configuration_id"])
        chain.append(_stage(
            "M8", "deep matcher expansion & adaptive routing", m8_run, data_root,
            "COMPLETE",
            configuration_id=cfg,
            artifacts=[
                _art(m8_run / "m8_status.json", "m8_status", data_root),
                _art(m8_run / "summary.json", "m8_summary", data_root),
                _art(m8_run / "m8_manifest.json", "m8_manifest", data_root),
                _art(m8_run / "routing" / "routing.json", "m8_routing", data_root),
            ],
            note="Routing decisions are what-to-try orders, never confidence verdicts.",
        ))
    else:
        missing.append("M8")
        chain.append(_stage("M8", "deep matcher expansion & adaptive routing",
                            None, data_root, "NOT_RUN", artifacts=[], note="No deep-matcher run."))

    # --- M9 AI evidence ----------------------------------------------------
    chain.append(_stage(
        "M9", "AI explanation evidence", None, data_root, "NOT_RUN",
        artifacts=[],
        note="M9 reasoning evidence packet is built on demand per explanation; "
             "AI claims are independently validated by m12.crosscheck.",
    ))

    status = "COMPLETE" if not missing else "INCOMPLETE"
    return {
        "pair_id": pair_id,
        "status": status,
        "missing_stages": missing,
        "generated_at": rfc3339_now(),
        "chain": chain,
        "note": "No absolute/home paths; sha256 over every referenced artifact; missing stages report NOT_RUN.",
    }


def _load_m5_defaults() -> dict:
    from backend.app.config import m4_config, m5_config
    return {"cfg": m5_config(), "m4": m4_config()["defaults"]}


__all__ = ["build_full_provenance", "sha256_of"]