"""M12 reproducibility signature comparison (RUN A / RUN B / RUN C).

Pure functions that compute a deterministic *signature* of a completed
experiment from its on-disk artifacts, and compare three runs. The test/script
layer is responsible for constructing the workspaces; this module never runs
the pipeline itself, so it stays importable, fast and deterministic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.config import m4_config, m5_config, m6_config, m7_config

SIGNATURE_SUBJECTS = (
    "experiment_id",
    "m3_total_candidates",
    "m4_trusted_tiles",
    "m5_selected_count",
    "m7_metric_count",
    "m7_available_count",
    "FUNNEL_M3_CANDIDATES",
    "FUNNEL_M4_TRUSTED_CORRESPONDENCES",
    "FUNNEL_M5_SELECTED_CORRESPONDENCES",
    "FUNNEL_M6_REGISTERED_CORRESPONDENCES",
    "RESIDUAL_MEAN_RECOMPUTE_PX",
    "RECOMPUTE_MISMATCH_COUNT",
    "transform_matrix_hash",
    "report_md_sha256",
)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _metric_value(records: list[dict], metric_id: str) -> Any:
    for rec in records:
        if rec.get("metric_id") == metric_id:
            return rec.get("value")
    return None


def compute_run_signature(settings: Any, pair_id: str) -> dict[str, Any]:
    """Deterministic signature of the completed M2..M7 experiment."""
    data_root: Path = settings.data_root_path
    sig: dict[str, Any] = {}

    from backend.app.metrics.service import MetricsService
    from backend.app.spatial.service import SpatialService
    from backend.app.trust.service import TrustService

    met = MetricsService(
        data_root, m7_cfg=m7_config(), m6_cfg=m6_config(),
        m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])

    exp = met.experiment(pair_id)
    sig["experiment_id"] = exp.get("experiment_id") if isinstance(exp, dict) else None

    records = met.metrics(pair_id)
    sig["m7_metric_count"] = len(records)
    sig["m7_available_count"] = sum(1 for r in records if r.get("status") == "AVAILABLE")
    for mid in ("FUNNEL_M3_CANDIDATES", "FUNNEL_M4_TRUSTED_CORRESPONDENCES",
                "FUNNEL_M5_SELECTED_CORRESPONDENCES",
                "FUNNEL_M6_REGISTERED_CORRESPONDENCES"):
        sig[mid] = _metric_value(records, mid)
    sig["RESIDUAL_MEAN_RECOMPUTE_PX"] = _metric_value(records, "RESIDUAL_MEAN_RECOMPUTE_PX")
    sig["RECOMPUTE_MISMATCH_COUNT"] = int(_metric_value(records, "RECOMPUTE_MISMATCH") or 0)

    trust_run = TrustService(data_root).find_run_for_pair(pair_id)
    if trust_run is not None:
        ttt = _read_json(trust_run / "tile_trust.json", {})
        sig["m4_trusted_tiles"] = sum(
            1 for t in (ttt.get("tiles") or []) if t.get("trust_state") == "TRUSTED")
    else:
        sig["m4_trusted_tiles"] = None

    spatial = SpatialService(data_root, m5_cfg=m5_config(),
                             m4_defaults=m4_config()["defaults"])
    s_run = spatial.find_run_for_pair(pair_id)
    m5_npz = (s_run / "selected_correspondences.npz") if s_run else None
    if m5_npz is not None and m5_npz.is_file():
        d = np.load(str(m5_npz), allow_pickle=False)
        sig["m5_selected_count"] = int(np.asarray(d["x_a"]).size)
    else:
        sig["m5_selected_count"] = None

    sig["m3_total_candidates"] = None
    m6_run = met._registration_run(pair_id)
    if m6_run is not None:
        stages = met._resolve_stage_dirs(pair_id, m6_run)
        cand_dir = stages["m3"] / "candidates"
        if cand_dir.is_dir():
            sig["m3_total_candidates"] = sum(1 for p in cand_dir.glob("*.npz"))

    sig["transform_matrix_hash"] = None
    if m6_run is not None:
        tf = _read_json(m6_run / "transform.json", {})
        if isinstance(tf, dict):
            sig["transform_matrix_hash"] = hashlib.sha256(
                json.dumps(tf.get("matrix"), sort_keys=True, default=str)
                .encode("utf-8")).hexdigest()

    sig["report_md_sha256"] = None
    m7_run = met.find_run_for_pair(pair_id)
    if m7_run is not None and (m7_run / "report.md").is_file():
        sig["report_md_sha256"] = hashlib.sha256(
            (m7_run / "report.md").read_bytes()).hexdigest()

    return {k: sig.get(k) for k in SIGNATURE_SUBJECTS if k in sig}


def compare_signatures(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare RUN A / RUN B / RUN C signatures.

    runs: {"A": sig, "B": sig, "C": sig} (at least two).
    Returns verdict per subject: IDENTICAL / DRIFT / MISSING.
    """
    names = list(runs)
    subjects = list(runs[names[0]])
    verdicts: dict[str, str] = {}
    drifted: list[str] = []
    for subject in subjects:
        values = [runs[n].get(subject) for n in names]
        if any(v is None for v in values) and not all(v is None for v in values):
            status = "MISSING"
        elif all(v == values[0] for v in values):
            status = "IDENTICAL"
        else:
            status = "DRIFT"
        verdicts[subject] = status
        if status in ("DRIFT", "MISSING"):
            drifted.append(subject)
    return {
        "schema_version": "M12-REPRO-001",
        "runs": {n: dict(r) for n, r in runs.items()},
        "subjects": verdicts,
        "status": "REPRODUCIBLE" if not drifted else "DRIFTED",
        "drifted_subjects": drifted,
    }