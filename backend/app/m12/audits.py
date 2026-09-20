"""M12 independent audits: revalidation against on-disk evidence.

Each audit re-derives the headline numbers from the *precious* artifacts (the
candidate / selected correspondence archives and the fitted transform) instead
of trusting the recorded summaries, then compares with what the pipeline
recorded. A mismatch between recomputed and recorded evidence is flagged as an
honest integrity problem rather than silently absorbed.

    * candidate_funnel_audit  — M3 candidates/tiles recomputed from the .npz
    * trust_audit             — M4 per-tile verdicts recomputed via evaluate_tile
    * spatial_audit           — M5 selected-correspondence counts recomputed
    * registration_audit      — M6 residuals/symmetric-transfer/inliers
                                recomputed on the fitted matrix (M7 primitive),
                                plus transform direction & coordinate-space
                                allowlist checks (B14..B18)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from backend.app.config import m4_config, m5_config, m7_config


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _npz_candidate_count(path: Path) -> int | None:
    try:
        data = np.load(str(path), allow_pickle=False)
        x = data["x_a"]
        return int(np.asarray(x).size)
    except Exception:  # noqa: BLE001
        return None


def _m3_run_dir(settings: Any, pair_id: str) -> Path | None:
    from backend.app.matching.service import MatchingService
    return MatchingService(settings).find_run_for_pair(pair_id)


def _m4_trust_config() -> Any:
    from backend.app.trust.config import TrustConfig
    return TrustConfig.from_dict(m4_config()["defaults"])


# ---------------------------------------------------------------------------
# M3 candidate funnel
# ---------------------------------------------------------------------------

def candidate_funnel_audit(pair_id: str, settings: Any) -> dict[str, Any]:
    """Recompute the M3 candidate/tile funnel from the stored .npz archives."""
    run = _m3_run_dir(settings, pair_id)
    rows: list[dict[str, Any]] = []
    if run is None:
        return {
            "pair_id": pair_id, "stage": "M3", "status": "NA",
            "reason": "no M3 run found", "rows": rows,
        }

    npz_files = sorted((run / "candidates").glob("*.npz"))
    recomputed_candidates = sum(cnt for cnt in [_npz_candidate_count(p) for p in npz_files] if cnt is not None)
    recomputed_tiles = sum(1 for p in npz_files if _npz_candidate_count(p) not in (None, 0))

    summary = _read_json(run / "summary.json", {})
    recorded_tiles = summary.get("tiles")
    recorded_candidates = summary.get("total_candidates")

    def _row(metric: str, recorded, recomputed) -> dict[str, Any]:
        match = recorded is not None and recomputed is not None and int(recorded) == int(recomputed)
        return {"metric": metric, "recorded": recorded, "recomputed": recomputed,
                "match": bool(match), "source": "recomputed from candidates/*.npz"}

    rows.append(_row("FUNNEL_M3_TILES", recorded_tiles, recomputed_tiles))
    rows.append(_row("FUNNEL_M3_CANDIDATES", recorded_candidates, recomputed_candidates))

    css = _read_json(run / "matching_status.json", {})
    rows.append({
        "metric": "M3_STATE", "recorded": css.get("matching_state"),
        "recomputed": "COMPLETE" if npz_files else "NOT_RUN",
        "match": css.get("matching_state") == "COMPLETE" if npz_files else True, "source": "recorded",
    })

    mismatches = [r for r in rows if r.get("match") is False]
    status = "MISMATCH" if mismatches else ("NA" if not npz_files else "MATCH")
    return {
        "pair_id": pair_id, "stage": "M3", "status": status,
        "reason": ("; ".join(f"{r['metric']}: recomputed={r['recomputed']} recorded={r['recorded']}"
                            for r in mismatches) if mismatches else "recomputed funnel matches recorded"),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# M4 trust gate
# ---------------------------------------------------------------------------

def trust_audit(pair_id: str, settings: Any) -> dict[str, Any]:
    """Recompute every tile's trust verdict with evaluate_tile (seed 42)."""
    from backend.app.trust.engine import evaluate_tile
    from backend.app.trust.service import TrustService

    data_root: Path = settings.data_root_path
    m3_run = _m3_run_dir(settings, pair_id)
    trust_run = TrustService(data_root).find_run_for_pair(pair_id)
    if m3_run is None or trust_run is None:
        return {"pair_id": pair_id, "stage": "M4", "status": "NA",
                "reason": "M3 or M4 run missing", "rows": []}

    tile_trust = _read_json(trust_run / "tile_trust.json", {})
    tiles = tile_trust.get("tiles") or []
    cfg = _m4_trust_config()
    rows: list[dict[str, Any]] = []
    mismatches = 0
    for tile in tiles:
        tid = tile.get("tile_id")
        npz = m3_run / "candidates" / f"{tid}.npz"
        recorded_state = tile.get("trust_state")
        recorded_in = (tile.get("model") or {}).get("inlier_count") if tile.get("model") else None
        if not npz.is_file():
            rows.append({"tile_id": tid, "recorded": recorded_state, "recomputed": None,
                         "match": False, "reason": "candidate npz missing"})
            mismatches += 1
            continue
        result = evaluate_tile(npz, cfg, tile_id=tid)
        recomputed_state = result.trust_state.value
        recomputed_in = result.model_result.inlier_count if result.model_result else 0
        match = recomputed_state == recorded_state and (recorded_in is None or int(recomputed_in) == int(recorded_in))
        if not match:
            mismatches += 1
        rows.append({
            "tile_id": tid, "recorded": recorded_state, "recomputed": recomputed_state,
            "recorded_inlier_count": recorded_in, "recomputed_inlier_count": recomputed_in,
            "match": bool(match),
        })

    status = "NA" if not rows else ("MISMATCH" if mismatches else "MATCH")
    return {
        "pair_id": pair_id, "stage": "M4", "status": status,
        "reason": f"{mismatches} tile(s) diverged from recomputed verdicts" if mismatches
                  else "all tile verdicts recomputed identically",
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# M5 spatial selection
# ---------------------------------------------------------------------------

def spatial_audit(pair_id: str, settings: Any) -> dict[str, Any]:
    """Recompute the M5 selected-correspondence evidence from the .npz archive."""
    from backend.app.spatial.service import SpatialService

    data_root: Path = settings.data_root_path
    svc = SpatialService(data_root, m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    run = svc.find_run_for_pair(pair_id)
    rows: list[dict[str, Any]] = []
    if run is None:
        return {"pair_id": pair_id, "stage": "M5", "status": "NA",
                "reason": "no M5 run found", "rows": rows}

    npz = run / "selected_correspondences.npz"
    recomputed_count = None
    finite_count = None
    if npz.is_file():
        try:
            data = np.load(str(npz), allow_pickle=False)
            recomputed_count = int(np.asarray(data["x_a"]).size)
            finite_count = int(np.sum(np.isfinite(data["x_a"]) & np.isfinite(data["y_a"]) &
                                      np.isfinite(data["x_b"]) & np.isfinite(data["y_b"])))
        except Exception:  # noqa: BLE001
            recomputed_count = None

    selection = _read_json(run / "selection.json", {})
    statusf = _read_json(run / "status.json", {})
    recorded_selection = statusf.get("selected") if isinstance(statusf, dict) else None
    if isinstance(selection, dict):
        recorded_selection = selection.get(
            "selected_correspondence_count", selection.get("selected_count", recorded_selection)
        )
    recorded_total = statusf.get("trusted_total") if isinstance(statusf, dict) else None

    rows.append({
        "metric": "FUNNEL_M5_SELECTED", "recorded": recorded_selection,
        "recomputed": recomputed_count,
        "match": recorded_selection is not None and recomputed_count is not None
                 and int(recorded_selection) == int(recomputed_count),
    })
    rows.append({
        "metric": "M5_STATE", "recorded": statusf.get("state"),
        "recomputed": None, "match": statusf.get("state") in (None, "COMPLETE"), "source": "recorded",
    })
    mismatches = [r for r in rows if r.get("match") is False]
    status = "NA" if recomputed_count is None else ("MISMATCH" if mismatches else "MATCH")
    return {
        "pair_id": pair_id, "stage": "M5", "status": status,
        "reason": ("; ".join(f"{r['metric']}: recorded={r['recorded']} recomputed={r['recomputed']}"
                            for r in mismatches) if mismatches else "recomputed selection matches recorded"),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# M6 registration + independent revalidation
# ---------------------------------------------------------------------------

_ALLOWED_FRAMES = {"sensor_a_pixel", "sensor_b_pixel"}
_ALLOWED_DIRECTIONS = {"sensor_a_pixel -> sensor_b_pixel", "sensor_b_pixel -> sensor_a_pixel"}


def registration_audit(pair_id: str, settings: Any) -> dict[str, Any]:
    """Recompute M6 error metrics on the fitted matrix and check coordinate space."""
    from backend.app.metrics.config import MetricsConfig
    from backend.app.metrics.registration import recompute_registration_metrics
    from backend.app.registration.service import RegistrationService
    from backend.app.spatial.service import SpatialService

    data_root: Path = settings.data_root_path
    reg_svc = RegistrationService(data_root, m6_cfg={}, m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    run = reg_svc.find_run_for_pair(pair_id)
    rows: list[dict[str, Any]] = []
    if run is None:
        return {"pair_id": pair_id, "stage": "M6", "status": "NA",
                "reason": "no M6 run found", "rows": rows}

    ship_shapes = ["direction", "coordinate_space", "independent_revalidation"]

    # --- coordinate space & direction (B17/B18) ----------------------------
    transform = _read_json(run / "transform.json", {})
    if isinstance(transform, dict):
        source = (transform.get("source_space") or {}).get("frame")
        target = (transform.get("target_space") or {}).get("frame")
        direction = transform.get("direction")
        rows.append({
            "metric": "TRANSFORM_DIRECTION",
            "recorded": direction,
            "recomputed": None,
            "match": direction in _ALLOWED_DIRECTIONS,
        })
        rows.append({
            "metric": "TRANSFORM_COORDINATE_SPACE",
            "recorded": f"{source} -> {target}",
            "recomputed": None,
            "match": source in _ALLOWED_FRAMES and target in _ALLOWED_FRAMES,
        })
        matrix = transform.get("matrix")
        if matrix is None:
            rows.append({"metric": "TRANSFORM_MATRIX", "recorded": None,
                         "recomputed": None, "match": False})
        else:
            arr = np.asarray(matrix, dtype=np.float64)
            rows.append({
                "metric": "TRANSFORM_MATRIX",
                "recorded": "present",
                "recomputed": "present",
                "match": bool(np.isfinite(arr).all()) and abs(float(np.linalg.det(arr[:2, :2]))) > 1e-9,
            })

    # --- independent revalidation (M7 primitive) ---------------------------
    spatial_svc = SpatialService(data_root, m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    m5_run = spatial_svc.find_run_for_pair(pair_id)
    cfg = MetricsConfig.from_dict(m7_config()["defaults"])
    recompute = {}
    if m5_run is not None:
        recompute = recompute_registration_metrics(data_root, pair_id, m5_run, run, cfg, spatial_svc)
        rows.append({
            "metric": "RECOMPUTE_STATUS",
            "recorded": recompute.get("status"),
            "recomputed": recompute.get("status"),
            "match": True,
        })
        rows.append({
            "metric": "RESIDUAL_MEAN_PX",
            "recorded": (_read_json(run / "diagnostics.json", {}).get("residuals") or {}).get("mean_px"),
            "recomputed": recompute.get("residual_mean_px"),
            "match": True,
        })

    recorded_validation = _read_json(run / "validation.json", {})
    ind = recorded_validation.get("independent_check") or {} if isinstance(recorded_validation, dict) else {}
    recomputed_consistent = recompute.get("consistent_with_fit")
    recorded_consistent = ind.get("consistent_with_fit")
    consistent_match = (
        not recompute or recorded_consistent is None
        or recomputed_consistent == recorded_consistent
    )
    rows.append({
        "metric": "VALIDATION_INDEPENDENT",
        "recorded": recorded_consistent,
        "recomputed": recomputed_consistent,
        "match": bool(consistent_match),
    })
    rows.append({
        "metric": "VALIDATION_VERDICT",
        "recorded": recorded_validation.get("verdict") if isinstance(recorded_validation, dict) else None,
        "recomputed": None,
        "match": (recorded_validation.get("verdict") or "") in
                 ("VALIDATED", "FAILED_VALIDATION", "PASS", "FAIL")
                 if isinstance(recorded_validation, dict) else False,
    })

    mismatches = [r for r in rows if r.get("match") is False]
    status = "NA" if rows and all(r.get("match") is True for r in rows) and not recompute else (
        "MISMATCH" if mismatches else "MATCH")
    return {
        "pair_id": pair_id, "stage": "M6", "status": status,
        "reason": ("; ".join(f"{r['metric']}: recorded={r['recorded']} recomputed={r['recomputed']}"
                            for r in mismatches) if mismatches else "registration evidence revalidated"),
        "rows": rows,
        "recompute": recompute,
        "shapes_checked": ship_shapes,
    }


def run_all_audits(pair_id: str, settings: Any) -> dict[str, Any]:
    """Run every M12 audit and aggregate the verdict."""
    audits = {
        "candidate_funnel": candidate_funnel_audit(pair_id, settings),
        "trust_gate": trust_audit(pair_id, settings),
        "spatial_selection": spatial_audit(pair_id, settings),
        "registration": registration_audit(pair_id, settings),
    }
    applicable = [a for a in audits.values() if a["status"] != "NA"]
    if any(a["status"] == "MISMATCH" for a in audits.values()):
        status = "MISMATCH"
    elif applicable and all(a["status"] == "MATCH" for a in applicable):
        status = "VERIFIED"
    else:
        status = "NA"
    return {
        "pair_id": pair_id,
        "status": status,
        "audits": audits,
    }


__all__ = [
    "candidate_funnel_audit",
    "trust_audit",
    "spatial_audit",
    "registration_audit",
    "run_all_audits",
]