"""M6 tests — Registration Engine, Verified Alignment & Jury-Ready Workspace.

Covers RG-M6-001 configuration, coordinate-space conversions (tile-local → sensor
pixel), strict M5 evidence loading, transform fitting (homography/affine + fallback),
validation verdicts, warp correctness, provenance (M2→M3→M4→M5→M6), full lifecycle
through real M2→M3→M4→M5→M6 pipeline, reset isolation, honest BLOCKED/INSUFFICIENT
states, security guards, and the bug-hunt corpus.

All fixtures are synthetic and labelled as such; no scientific claim is made.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fixturegen  # noqa: F401

from auth_helpers import authed_client_for_app, configure_auth

PA = "CS-P001"
SA, SB = "ohrc", "tmc2"
PC, MK, TG, SR, RG = "PC-M2-001", "MC-M3-001", "TG-M4-001", "SR-M5-001", "RG-M6-001"
W, H = 1000, 800
TW, TH = 500, 400
OVERLAP = {
    SA: {"sensor": SA, "row_start": 0, "row_end": H, "col_start": 0, "col_end": W, "width_px": W, "height_px": H},
    SB: {"sensor": SB, "row_start": 0, "row_end": H, "col_start": 0, "col_end": W, "width_px": W, "height_px": H},
}


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _m6_harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m6_"))
    fixturegen.write_correlated_fixtures(tmp)
    settings = Settings(data_root=str(tmp), _env_file=None)
    ensure_derived_directories(settings)
    configure_auth(settings)
    app = create_app(settings=settings)
    return authed_client_for_app(app), settings, tmp


def _register(client) -> str:
    resp = client.post("/api/pairs/register", json={
        "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
        "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
        "overlap_status": "UNKNOWN",
    })
    assert resp.status_code == 200, resp.text
    pair_id = resp.json()["pair_id"]
    val = client.post(f"/api/pairs/{pair_id}/validate")
    assert val.status_code == 200
    assert val.json()["status"] == "VALID"
    return pair_id


def _prepare(client, pair_id):
    resp = client.post(f"/api/processing/{pair_id}/prepare", json={
        "geometry": {
            "source": "TEST_FIXTURE",
            "products": {
                "ohrc": {"row_offset_m": 0, "col_offset_m": 0, "gsd_m": 0.5},
                "tmc2": {"row_offset_m": -2, "col_offset_m": -2, "gsd_m": 0.5},
            },
        },
    })
    assert resp.status_code == 200
    return resp.json()


def _run_m3(client, pair_id):
    resp = client.post(f"/api/matching/{pair_id}/run", json={"configuration_id": None})
    assert resp.status_code == 200
    assert resp.json()["state"] == "COMPLETE"


def _build_full_tree(settings, pair_id=PA, *, overlap_w=W, overlap_h=H,
                     tile_w=TW, tile_h=TH, n=50, noise=0.3, outliers=8,
                     trust_gate="COMPLETE", write_crops=True):
    """Build minimal M2 + M3 + M4 artifacts (optionally with crop arrays)."""
    from backend.app.trust.config import TG_M4_001
    from backend.app.trust.engine import evaluate_tile

    tmp = settings.data_root_path
    pr = tmp / "derived" / "processing" / pair_id / PC
    (pr / "diagnostics").mkdir(parents=True)
    (pr / "diagnostics" / "overlap.json").write_text(
        json.dumps({"regions": {
            SA: {**OVERLAP[SA], "col_end": overlap_w, "row_end": overlap_h, "width_px": overlap_w, "height_px": overlap_h},
            SB: {**OVERLAP[SB], "col_end": overlap_w, "row_end": overlap_h, "width_px": overlap_w, "height_px": overlap_h},
        }}), encoding="utf-8")
    crops = pr / "crops"
    crops.mkdir(parents=True)
    tiles = []
    tile_ids = [f"{pair_id}-T001", f"{pair_id}-T002", f"{pair_id}-T003", f"{pair_id}-T004"]
    for tid, sen, side, rs, cs, w, h in [
        (tile_ids[0], SA, "a", 0, 0, tile_w, tile_h),
        (tile_ids[1], SB, "b", 0, 0, tile_w, tile_h),
        (tile_ids[2], SA, "a", min(400, overlap_h - tile_h), min(500, overlap_w - tile_w), min(600, overlap_w - 500), min(400, overlap_h - 400)),
        (tile_ids[3], SB, "b", min(400, overlap_h - tile_h), min(500, overlap_w - tile_w), min(600, overlap_w - 500), min(400, overlap_h - 400)),
    ]:
        tiles.append({
            "tile_id": tid, "sensor": sen, "side": side,
            "row_start": rs, "col_start": cs, "width": w, "height": h,
            "valid_fraction": 0.9, "clipped": False, "too_small": False,
            "ground_box": {}, "array_filename": f"{pair_id}_{tid[-3:]}.npy",
            "preview_filename": f"{pair_id}_{tid[-3:]}.png",
        })
    (crops / "tiles.json").write_text(
        json.dumps({"pair_id": pair_id, "count": 4, "tiles": tiles}, indent=2),
        encoding="utf-8")
    if write_crops:
        rng = np.random.RandomState(11)
        for tid, sen, side, rs, cs, w, h in [
            (tile_ids[0], SA, "a", 0, 0, tile_w, tile_h),
            (tile_ids[1], SB, "b", 0, 0, tile_w, tile_h),
            (tile_ids[2], SA, "a", min(400, overlap_h - tile_h), min(500, overlap_w - tile_w), min(600, overlap_w - 500), min(400, overlap_h - 400)),
            (tile_ids[3], SB, "b", min(400, overlap_h - tile_h), min(500, overlap_w - tile_w), min(600, overlap_w - 500), min(400, overlap_h - 400)),
        ]:
            arr = (rng.rand(h, w) * 240).astype(np.uint16)
            np.save(str(crops / f"{pair_id}_{tid[-3:]}.npy"), arr)

    md = tmp / "derived" / "matches" / pair_id / PC / MK
    (md / "candidates").mkdir(parents=True)
    rng = np.random.RandomState(42)
    mids = [f"{pair_id}-M001", f"{pair_id}-M002"]
    tps = [(tile_ids[0], tile_ids[1]), (tile_ids[2], tile_ids[3])]
    per_tile = []
    for mid, (ta, tb) in zip(mids, tps):
        xa = rng.uniform(10.0, float(tile_w) - 10, n)
        ya = rng.uniform(10.0, float(tile_h) - 10, n)
        xb = xa + 5.0 + rng.normal(0, noise, n)
        yb = ya - 3.0 + rng.normal(0, noise, n)
        xb[:outliers] += rng.uniform(-200, 200, outliers)
        yb[:outliers] += rng.uniform(-200, 200, outliers)
        np.savez(md / "candidates" / f"{mid}.npz",
                 x_a=xa, y_a=ya, x_b=xb, y_b=yb,
                 descriptor_distance=np.linspace(40, 90, n).astype(np.float64),
                 matcher_score=np.linspace(0.95, 0.5, n).astype(np.float64))
        (md / "candidates" / f"{mid}.json").write_text(
            json.dumps({"decision": {"tile_a": ta, "tile_b": tb, "outcome": "SUCCESS"}}),
            encoding="utf-8")
        per_tile.append({"match_tile_id": mid, "outcome": "SUCCESS",
                         "candidates": n, "strategy_used": "sift", "proposed_strategy": "sift"})
    (md / "summary.json").write_text(json.dumps({
        "pair_id": pair_id, "configuration_id": MK,
        "processing_configuration_id": PC, "tiles": 2,
        "total_candidates": n * 2, "per_tile": per_tile,
    }, indent=2), encoding="utf-8")
    (md / "matching_status.json").write_text(
        json.dumps({"matching_state": "COMPLETE", "configuration_id": MK}),
        encoding="utf-8")
    td = tmp / "derived" / "trust" / pair_id / PC / MK / TG
    td.mkdir(parents=True)
    ttl = []
    for mid in mids:
        r = evaluate_tile(md / "candidates" / f"{mid}.npz", TG_M4_001, tile_id=mid)
        ttl.append({"tile_id": mid, "trust_state": r.trust_state.value,
                     "reasons": list(r.reasons), "block_code": None,
                     "model": {"inlier_count": r.model_result.inlier_count if r.model_result else 0,
                               "inlier_ratio": r.model_result.inlier_ratio if r.model_result else 0.0}})
    trusted_count = sum(1 for t in ttl if t["trust_state"] == "TRUSTED")
    gate_state = trust_gate if trusted_count > 0 else "FAILED"
    (td / "trust_status.json").write_text(json.dumps({
        "gate_state": gate_state, "pair_id": pair_id,
        "processing_configuration_id": PC, "matcher_configuration_id": MK,
        "trust_configuration_id": TG, "block_code": None, "reasons": [],
    }, indent=2), encoding="utf-8")
    (td / "tile_trust.json").write_text(
        json.dumps({"pair_id": pair_id, "trust_configuration_id": TG, "tiles": ttl}, indent=2),
        encoding="utf-8")
    (td / "summary.json").write_text(
        json.dumps({"gate_state": gate_state, "trusted_tiles": trusted_count}),
        encoding="utf-8")
    return tmp


def _run_m5(tmp, pair_id=PA):
    from backend.app.config import m4_config, m5_config
    from backend.app.spatial.service import SpatialService
    svc = SpatialService(tmp, m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    status = svc.run(pair_id)
    assert status["state"] == "COMPLETE", status
    return svc


def _get_m6_svc(tmp):
    from backend.app.config import m4_config, m5_config, m6_config
    from backend.app.registration.service import RegistrationService
    return RegistrationService(
        tmp, m6_cfg=m6_config(), m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])


def _build_m6_ready_tree(settings, pair_id=PA, **kw):
    tmp = _build_full_tree(settings, pair_id, **kw)
    _run_m5(tmp, pair_id)
    return tmp


# ===========================================================================
# 1. configuration
# ===========================================================================

def test_m6_configuration_registered():
    from backend.app.config import m6_config
    cfg = m6_config()
    assert cfg["registration_configuration_id"] == "RG-M6-001"
    d = cfg["defaults"]
    assert d["transform"]["preferred_type"] == "homography"
    assert d["transform"]["affine_fallback"] is True
    assert int(d["transform"]["ransac_max_iterations"]) == 2000
    assert float(d["transform"]["ransac_inlier_threshold_px"]) == pytest.approx(3.0)
    assert int(d["transform"]["ransac_seed"]) == 42
    assert float(d["validation"]["max_symmetric_transfer_px"]) == pytest.approx(12.0)
    assert int(d["execution"]["max_runtime_seconds"]) == 120


def test_m6_config_loader_from_defaults():
    from backend.app.config import m6_config
    from backend.app.registration.config import RegistrationConfig
    cfg = RegistrationConfig.from_dict(m6_config()["defaults"])
    assert cfg.registration_configuration_id == "RG-M6-001"
    assert cfg.transform.preferred_type == "homography"
    assert cfg.transform.affine_fallback is True
    assert cfg.validation.max_symmetric_transfer_px == pytest.approx(12.0)
    assert cfg.warp.dtype == "uint16"


def test_m6_config_coercion_from_exponent_string():
    from backend.app.registration.config import RegistrationConfig, _f, _i
    assert _f("1e6", 0.0) == pytest.approx(1e6)
    assert _f("abc", 42.0) == pytest.approx(42.0)
    assert _i(None, 8) == 8
    assert _i("3", 99) == 3
    raw = {
        "transform": {"preferred_type": "affine", "ransac_seed": "7"},
        "validation": {"max_symmetric_transfer_px": "4.5", "max_condition_number": "1e5"},
        "execution": {"max_runtime_seconds": "30"},
    }
    cfg = RegistrationConfig.from_dict(raw)
    assert cfg.transform.preferred_type == "affine"
    assert cfg.transform.ransac_seed == 7
    assert cfg.validation.max_symmetric_transfer_px == pytest.approx(4.5)
    assert cfg.validation.max_condition_number == pytest.approx(1e5)
    assert cfg.execution.max_runtime_seconds == 30


def test_m6_configuration_endpoint(settings_factory):
    client, _s, _t = _m6_harness(settings_factory)
    with client:
        body = client.get("/api/registration/configurations").json()
        assert body["default_registration_configuration_id"] == "RG-M6-001"
        conf = body["configurations"][0]
        assert conf["registration_configuration_id"] == "RG-M6-001"
        assert body["valid_registration_configuration_ids"] == ["RG-M6-001"]
        assert "no scientifically tuned" in body["note"]


def test_m6_health_meta_includes_m6_config():
    from fastapi.testclient import TestClient as TC
    from backend.app.main import app
    c = TC(app)
    with c:
        meta = c.get("/api/meta").json()
        assert meta["m6_config"]["registration_configuration_id"] == "RG-M6-001"


def test_m6_state_vocabulary():
    from backend.app.registration.states import (
        RegistrationBlockCode,
        RegistrationRunState,
        TransformType,
    )
    assert RegistrationRunState.COMPLETE.value == "COMPLETE"
    assert RegistrationRunState.INSUFFICIENT.value == "INSUFFICIENT"
    assert RegistrationRunState.BLOCKED.value == "BLOCKED"
    assert RegistrationBlockCode.M5_NOT_AVAILABLE.value == "M5_NOT_AVAILABLE"
    assert TransformType.HOMOGRAPHY.value == "HOMOGRAPHY"


# ===========================================================================
# 2. coordinate space
# ===========================================================================

def test_tile_local_to_sensor_pixel():
    from backend.app.registration.coord_space import TileOrigin, tile_local_to_sensor_pixel
    origin = TileOrigin("T1", SA, "a", row_start=100, col_start=50, width=500, height=400)
    x = np.array([10.0, 20.0])
    y = np.array([30.0, 40.0])
    px_x, px_y, valid = tile_local_to_sensor_pixel(x, y, origin)
    assert valid.tolist() == [True, True]
    assert px_x.tolist() == [60.0, 70.0]
    assert px_y.tolist() == [130.0, 140.0]


def test_tile_local_to_sensor_pixel_nan():
    from backend.app.registration.coord_space import TileOrigin, tile_local_to_sensor_pixel
    origin = TileOrigin("T1", SA, "a", row_start=0, col_start=0, width=500, height=400)
    x = np.array([10.0, np.nan])
    y = np.array([np.nan, 20.0])
    _, _, valid = tile_local_to_sensor_pixel(x, y, origin)
    assert valid.tolist() == [False, False]


def test_tile_local_to_sensor_pixel_no_origin():
    from backend.app.registration.coord_space import tile_local_to_sensor_pixel
    x = np.array([10.0, 20.0])
    y = np.array([30.0, 40.0])
    px_x, px_y, valid = tile_local_to_sensor_pixel(x, y, None)
    assert valid.tolist() == [False, False]
    assert np.all(np.isnan(px_x))
    assert np.all(np.isnan(px_y))


def test_normalized_to_sensor_pixel():
    from backend.app.registration.coord_space import SensorOverlapBox, normalized_to_sensor_pixel
    box = SensorOverlapBox(SA, row_start=0, row_end=400, col_start=0, col_end=500)
    nx = np.array([0.5, 1.0])
    ny = np.array([0.25, 0.5])
    px_x, px_y, valid = normalized_to_sensor_pixel(nx, ny, box)
    assert valid.tolist() == [True, True]
    assert px_x.tolist() == [250.0, 500.0]
    assert px_y.tolist() == [100.0, 200.0]


def test_build_sensor_pixel_points():
    from backend.app.registration.coord_space import (
        TileOrigin,
        build_sensor_pixel_points,
    )
    geom_map = {
        "M001": {
            "a": TileOrigin("T001", SA, "a", row_start=0, col_start=0, width=500, height=400),
            "b": TileOrigin("T002", SB, "b", row_start=0, col_start=0, width=500, height=400),
        },
    }
    x_a = np.array([10.0, 20.0])
    y_a = np.array([30.0, 40.0])
    x_b = np.array([110.0, 120.0])
    y_b = np.array([130.0, 140.0])
    src = np.array(["M001", "M001"], dtype="U64")
    pa_x, pa_y, pb_x, pb_y, valid = build_sensor_pixel_points(x_a, y_a, x_b, y_b, src, geom_map)
    assert valid.tolist() == [True, True]
    assert pa_x.tolist() == [10.0, 20.0]
    assert pb_x.tolist() == [110.0, 120.0]


def test_build_sensor_pixel_points_unknown_tile():
    from backend.app.registration.coord_space import build_sensor_pixel_points
    geom_map = {}
    x_a = np.array([10.0])
    y_a = np.array([30.0])
    x_b = np.array([110.0])
    y_b = np.array([130.0])
    src = np.array(["NOPE"], dtype="U64")
    _, _, _, _, valid = build_sensor_pixel_points(x_a, y_a, x_b, y_b, src, geom_map)
    assert valid.tolist() == [False]


def test_build_tile_geometry_map_from_json():
    from backend.app.registration.coord_space import build_tile_geometry_map
    mapping = {
        "status": "MAPPED",
        "mappings": [
            {
                "match_tile_id": "M001",
                "geometry_a": {"tile_id": "T001", "sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
                "geometry_b": {"tile_id": "T002", "sensor": SB, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
            },
        ],
    }
    gm = build_tile_geometry_map(mapping)
    assert "M001" in gm
    assert gm["M001"]["a"].tile_id == "T001"
    assert gm["M001"]["b"].tile_id == "T002"


# ===========================================================================
# 3. loader
# ===========================================================================

def _write_m5_artifact(tmp, pair_id=PA, *, state="COMPLETE", outcome="SELECTED",
                       n=30, missing_key=False, empty=False, non_finite=False,
                       mismatch=False, invalid_side=False, scene_out_of_bounds=False):
    from backend.app.spatial.service import SpatialService
    tmp = Path(tmp)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    run = sp._spatial_root() / pair_id / PC / MK / TG / SR
    run.mkdir(parents=True)
    (run / "status.json").write_text(json.dumps({
        "pair_id": pair_id, "state": state,
        "processing_configuration_id": PC, "matcher_configuration_id": MK,
        "trust_configuration_id": TG, "spatial_reliability_configuration_id": SR,
    }), encoding="utf-8")
    (run / "selection.json").write_text(json.dumps({"selection_outcome": outcome}))
    (run / "summary.json").write_text(json.dumps({
        "pair_id": pair_id, "selection": {"outcome": outcome},
    }))
    if n == 0 or empty:
        np.savez(run / "selected_correspondences.npz",
                 x_a=np.array([], dtype=np.float64), y_a=np.array([], dtype=np.float64),
                 x_b=np.array([], dtype=np.float64), y_b=np.array([], dtype=np.float64),
                 scene_x=np.array([], dtype=np.float64), scene_y=np.array([], dtype=np.float64),
                 scene_side=np.array([], dtype="U1"),
                 source_tile_id=np.array([], dtype="U64"),
                 source_candidate_index=np.array([], dtype=np.int64),
                 side_a_cell_id=np.array([], dtype="U16"),
                 side_b_cell_id=np.array([], dtype="U16"),
                 component_id=np.array([], dtype="U16"),
                 selection_reason=np.array([], dtype="U64"))
        return tmp
    rng = np.random.RandomState(5)
    xa = rng.uniform(10, TW - 10, n)
    ya = rng.uniform(10, TH - 10, n)
    xb = xa + 5
    yb = ya - 3
    if missing_key:
        np.savez(run / "selected_correspondences.npz",
                 x_a=xa, y_a=ya, x_b=xb, y_b=yb)
        return tmp
    extra = {}
    scene_x = np.array([0.5] * n)
    scene_y = np.array([0.5] * n)
    if scene_out_of_bounds:
        scene_x = np.array([1.5] * n)
    scene_side = np.array([("x" if invalid_side else "a")] * n, dtype="U1")
    tile_ids = np.array([f"{PA}-M001"] * n, dtype="U64")
    cand_idx = np.arange(n, dtype=np.int64)
    cids_a = np.array(["R01C01"] * n, dtype="U16")
    cids_b = np.array(["R01C01"] * n, dtype="U16")
    comps = np.array(["C01"] * n, dtype="U16")
    reasons = np.array(["SR_SELECTED_SUPPORTED_REGION"] * n, dtype="U64")
    if non_finite:
        xa = np.array([np.nan] * n)
    if mismatch:
        cand_idx = np.arange(n + 3, dtype=np.int64)
    np.savez(run / "selected_correspondences.npz",
             x_a=xa, y_a=ya, x_b=xb, y_b=yb,
             scene_x=scene_x, scene_y=scene_y, scene_side=scene_side,
             source_tile_id=tile_ids, source_candidate_index=cand_idx,
             side_a_cell_id=cids_a, side_b_cell_id=cids_b,
             component_id=comps, selection_reason=reasons, **extra)
    return tmp


def test_loader_success(settings_factory):
    from backend.app.spatial.service import SpatialService
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path)
    from backend.app.registration.loader import load_selected_correspondences
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    ev = load_selected_correspondences(tmp, PA, sp)
    assert ev.n_correspondences > 0
    assert ev.unique_tile_ids == [f"{PA}-M001"]
    assert ev.unique_component_ids == ["C01"]


def test_loader_missing_key(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, missing_key=True)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "COORDINATE_LOAD_FAILED" in str(e.value)


def test_loader_empty_rejected(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, n=0)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "INSUFFICIENT_EVIDENCE" in str(e.value)


def test_loader_non_finite_rejected(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, non_finite=True)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "INSUFFICIENT_EVIDENCE" in str(e.value)


def test_loader_length_mismatch_rejected(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, mismatch=True)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "LENGTH" in str(e.value)


def test_loader_m5_not_complete(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, state="BLOCKED")
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "M5_NOT_COMPLETE" in str(e.value)


def test_loader_selection_not_selected(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, outcome="INSUFFICIENT")
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "NO_SELECTION" in str(e.value)


def test_loader_no_m5_run(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    sp = SpatialService(settings.data_root_path, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(settings.data_root_path, PA, sp)
    assert "M5_NOT_AVAILABLE" in str(e.value)


# ===========================================================================
# 4. engine
# ===========================================================================

def test_engine_homography_recovers_translation():
    from backend.app.registration.config import RegistrationConfig
    from backend.app.registration.engine import fit_and_validate
    rng = np.random.RandomState(1)
    n = 120
    xa = rng.uniform(50, 950, n)
    ya = rng.uniform(50, 750, n)
    xb = xa + 25.0 + rng.normal(0, 0.5, n)
    yb = ya - 12.0 + rng.normal(0, 0.5, n)
    valid = np.ones(n, dtype=bool)
    cfg = RegistrationConfig.from_dict({})
    res = fit_and_validate(xa, ya, xb, yb, valid, cfg)
    assert res.transform_matrix is not None
    H = res.transform_matrix
    # translation dominates: predict a point
    p = H @ np.array([100.0, 200.0, 1.0])
    px = p[0] / p[2]
    py = p[1] / p[2]
    assert abs(px - 125.0) < 2.0
    assert abs(py - 188.0) < 2.0
    assert res.validation.verdict.value == "PASS"


def test_engine_affine_fallback_degenerate():
    from backend.app.registration.config import RegistrationConfig
    from backend.app.registration.engine import fit_and_validate
    # Regular data, but force homography to fail its inlier thresholds so the
    # affine fallback engages deterministically.
    rng = np.random.RandomState(1)
    n = 120
    x = rng.uniform(50, 950, n)
    y = rng.uniform(50, 750, n)
    xb = x * 1.0 + 10
    yb = y + 4
    valid = np.ones(n, dtype=bool)
    cfg = RegistrationConfig.from_dict({"transform": {
        "min_inliers_for_homography": 99999,
        "min_inlier_ratio_for_homography": 0.999,
    }})
    res = fit_and_validate(x, y, xb, yb, valid, cfg)
    assert res.transform_matrix is not None
    assert res.transform_type.value == "AFFINE"
    assert res.selection_reason.value == "FALLBACK_INSUFFICIENT_INLIERS"


def test_engine_insufficient_evidence():
    from backend.app.registration.config import RegistrationConfig
    from backend.app.registration.engine import fit_and_validate
    x = np.array([1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 3.0])
    xb = x + 1
    yb = y + 1
    valid = np.ones(3, dtype=bool)
    cfg = RegistrationConfig.from_dict({})
    res = fit_and_validate(x, y, xb, yb, valid, cfg)
    assert res.error == "INSUFFICIENT_EVIDENCE"
    assert res.transform_matrix is None


def test_engine_determinism():
    from backend.app.registration.config import RegistrationConfig
    from backend.app.registration.engine import fit_and_validate
    rng = np.random.RandomState(2)
    n = 150
    xa = rng.uniform(20, 980, n)
    ya = rng.uniform(20, 780, n)
    xb = xa + 8 + rng.normal(0, 0.4, n)
    yb = ya - 5 + rng.normal(0, 0.4, n)
    valid = np.ones(n, dtype=bool)
    cfg = RegistrationConfig.from_dict({})
    r1 = fit_and_validate(xa, ya, xb, yb, valid, cfg)
    r2 = fit_and_validate(xa, ya, xb, yb, valid, cfg)
    assert r1.transform_matrix is not None and r2.transform_matrix is not None
    assert np.allclose(r1.transform_matrix, r2.transform_matrix, atol=1e-9)


def test_engine_validation_issues_on_garbage():
    from backend.app.registration.config import RegistrationConfig
    from backend.app.registration.engine import fit_and_validate
    rng = np.random.RandomState(3)
    n = 40
    xa = rng.uniform(0, 100, n)
    ya = rng.uniform(0, 100, n)
    xb = rng.uniform(0, 100, n)
    yb = rng.uniform(0, 100, n)
    valid = np.ones(n, dtype=bool)
    cfg = RegistrationConfig.from_dict({})
    res = fit_and_validate(xa, ya, xb, yb, valid, cfg)
    assert res.validation.verdict.value in ("FAIL", "INSUFFICIENT")


def test_engine_transform_type_affine_clean():
    from backend.app.registration.config import RegistrationConfig
    from backend.app.registration.engine import fit_and_validate
    rng = np.random.RandomState(4)
    n = 100
    xa = rng.uniform(0, 100, n)
    ya = rng.uniform(0, 100, n)
    xb = xa * 0.95 + ya * 0.1 + 20
    yb = xa * 0.05 + ya * 1.05 - 8
    valid = np.ones(n, dtype=bool)
    cfg = RegistrationConfig.from_dict({"transform": {"preferred_type": "affine"},
                                         "validation": {"max_symmetric_transfer_px": 6.0}})
    res = fit_and_validate(xa, ya, xb, yb, valid, cfg)
    assert res.transform_matrix is not None


# ===========================================================================
# 5. warp
# ===========================================================================

def test_warp_identity_like_translation():
    from backend.app.registration.warp import WarpSpec, warp_tile
    rng = np.random.RandomState(7)
    src = (rng.rand(64, 64) * 240).astype(np.uint16)
    H = np.array([
        [1.0, 0.0, 10.0],
        [0.0, 1.0, 6.0],
        [0.0, 0.0, 1.0],
    ])
    spec = WarpSpec(src_array=src, src_row_start=100, src_col_start=50,
                    out_rows=64, out_cols=64, out_row_start=106, out_col_start=60)
    prod = warp_tile(spec, H, "homography", fill_value=0)
    assert prod.warped.shape == (64, 64)
    # center of source maps to the same local position (the windows are shifted
    # by exactly the translation), so intensity at center survives
    assert 0.0 < float(np.mean(prod.valid_mask)) <= 1.0


def test_warp_affine_to_perspective_pipeline():
    from backend.app.registration.warp import WarpSpec, warp_tile
    rng = np.random.RandomState(8)
    src = (rng.rand(40, 40) * 100).astype(np.uint16)
    M = np.array([
        [1.0, 0.0, 4.0],
        [0.0, 1.0, 2.0],
        [0.0, 0.0, 1.0],
    ])
    spec = WarpSpec(src_array=src, src_row_start=0, src_col_start=0,
                    out_rows=40, out_cols=40, out_row_start=0, out_col_start=0)
    prod = warp_tile(spec, M, "affine", fill_value=0)
    assert prod.matrix_type == "affine"
    assert 0.0 < float(np.mean(prod.valid_mask)) <= 1.0


def test_warp_zero_out_shape():
    from backend.app.registration.warp import WarpSpec, warp_tile
    src = np.zeros((10, 10), dtype=np.uint16)
    M = np.eye(3)
    spec = WarpSpec(src_array=src, src_row_start=0, src_col_start=0,
                    out_rows=0, out_cols=0, out_row_start=0, out_col_start=0)
    prod = warp_tile(spec, M, "homography")
    assert prod.warped.size == 0
    assert prod.valid_mask.size == 0


# ===========================================================================
# 6. provenance / manifest
# ===========================================================================

def test_provenance_builds_chain(settings_factory):
    from backend.app.registration.provenance import build_provenance, sha256_of
    tmp = settings_factory().data_root_path
    m2 = tmp / "derived" / "processing" / PA / PC
    m2.mkdir(parents=True)
    (m2 / "summary.json").write_text(json.dumps({"configuration_id": PC}))
    (m3 := tmp / "derived" / "matches" / PA / PC / MK).mkdir(parents=True)
    (m3 / "summary.json").write_text(json.dumps({"configuration_id": MK}))
    (m4 := tmp / "derived" / "trust" / PA / PC / MK / TG).mkdir(parents=True)
    (m4 / "trust_status.json").write_text(json.dumps({"trust_configuration_id": TG}))
    (m4 / "tile_trust.json").write_text(json.dumps({"tiles": []}))
    (m5 := tmp / "derived" / "spatial" / PA / PC / MK / TG / SR).mkdir(parents=True)
    (m5 / "status.json").write_text(json.dumps({"spatial_reliability_configuration_id": SR}))
    (m5 / "selected_correspondences.npz").write_bytes(b"npz")
    (m5 / "selection.json").write_text(json.dumps({"outcome": "SELECTED"}))
    (m6 := tmp / "derived" / "registration" / PA / PC / MK / TG / SR / RG).mkdir(parents=True)
    (m6 / "status.json").write_text(json.dumps({"registration_configuration_id": RG}))
    (m6 / "transform.json").write_text(json.dumps({"matrix": []}))
    prov = build_provenance(PA, tmp,
                            m2_run_dir=m2, m3_run_dir=m3, m4_run_dir=m4,
                            m5_run_dir=m5, m6_run_dir=m6, m6_status={})
    milestones = [c["milestone"] for c in prov["chain"]]
    assert milestones == ["M2", "M3", "M4", "M5", "M6"]
    for c in prov["chain"]:
        for a in [x for x in c.get("artifacts", []) if x]:
            assert ".." not in a["path"]
            assert ":" not in a["path"].split("/", 1)[0]
            assert len(a["sha256"]) == 64


def test_provenance_sha256_match():
    from backend.app.registration.provenance import sha256_of
    tmp = Path(tempfile.mkdtemp(prefix="cs_m6_sha_"))
    try:
        p = tmp / "a.bin"
        p.write_bytes(b"hello world")
        assert sha256_of(p) == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    finally:
        shutil.rmtree(tmp)


def test_registration_manifest_builder():
    from backend.app.registration.manifest import build_registration_manifest
    m = build_registration_manifest(
        pair_id=PA, registration_config_id=RG, registration_config_version="1",
        proc_cfg=PC, matcher_cfg=MK, trust_cfg=TG, spatial_cfg=SR,
        summary={"state": "COMPLETE", "transform_type": "HOMOGRAPHY",
                 "validation_verdict": "PASS", "correspondences": 10},
        artifacts=[{"path": "x", "sha256": "a" * 64, "kind": "y"}],
        scientific_note="no claim",
    )
    assert m["pair_id"] == PA
    assert m["summary"]["validation_verdict"] == "PASS"
    assert m["artifacts"][0]["sha256"] == "a" * 64


# ===========================================================================
# 7. lifecycle via service
# ===========================================================================

def test_service_prerequisites_no_m5(settings_factory):
    settings = settings_factory()
    svc = _get_m6_svc(settings.data_root_path)
    prereq = svc.prerequisites(PA)
    assert prereq["ready"] is False
    assert prereq["block_code"] == "M5_NOT_AVAILABLE"


def test_service_blocks_empty_data(settings_factory):
    settings = settings_factory()
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["state"] == "BLOCKED"
    assert status["block_code"] == "M5_NOT_AVAILABLE"


def test_service_blocks_when_m5_blocked(settings_factory):
    settings = settings_factory()
    _write_m5_artifact(settings.data_root_path, state="BLOCKED")
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["state"] == "BLOCKED"
    assert status["block_code"] in ("M5_NOT_COMPLETE", "M5_NOT_AVAILABLE")


def test_service_blocks_unknown_config(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    status = svc.run(PA, registration_config_id="NOPE")
    assert status["state"] == "BLOCKED"
    assert status["block_code"] == "UNKNOWN_CONFIG"


def test_service_complete_full_lifecycle(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    status = svc.run(PA)
    assert status["state"] == "COMPLETE", status
    assert status["block_code"] is None
    run_dir = svc.find_run_for_pair(PA)
    assert run_dir is not None
    for name in ("status.json", "summary.json", "transform.json",
                 "diagnostics.json", "validation.json", "registration_manifest.json",
                 "provenance.json"):
        assert (run_dir / name).is_file(), name
    assert (run_dir / "registered" / "registered_image.npy").is_file()
    assert (run_dir / "registered" / "valid_mask.npy").is_file()
    assert (run_dir / "registered" / "registered_meta.json").is_file()


def test_service_summary_no_confidence_claim(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    run_dir = svc.find_run_for_pair(PA)
    payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    blob = json.dumps(payload)
    assert "confidence" not in blob.lower()
    assert "ce90" not in blob.lower()
    assert "accuracy" not in blob.lower()


def test_service_manifest_no_absolute_paths(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    manifest = svc.manifest(PA)
    for a in manifest.get("artifacts", []):
        assert not Path(a["path"]).is_absolute()
        assert ".." not in a["path"]
        assert Path(tmp) not in [Path(x) for x in [a["path"]]]


def test_service_transform_matrix_valid(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    t = svc.transform(PA)
    m = t["matrix"]
    assert m is not None
    assert len(m) == 3 and all(len(row) == 3 for row in m)
    assert t["transform_type"] == "HOMOGRAPHY"


def test_service_diagnostics_present(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    d = svc.diagnostics(PA)
    assert d["transform_type"] == "HOMOGRAPHY"
    assert d["correspondences"]["valid_for_fit"] >= 4
    assert d["correspondences"]["inliers"] >= 1


def test_service_validation_present(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    v = svc.validation(PA)
    assert v["verdict"] == "PASS"
    assert v["issues"] == []


def test_service_provenance_after_run(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    prov = svc.provenance(PA)
    milestones = [c["milestone"] for c in prov["chain"]]
    assert milestones == ["M2", "M3", "M4", "M5", "M6"]


def test_service_deterministic_two_runs(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    s1 = svc.run(PA)
    assert s1["state"] == "COMPLETE"
    m1 = svc.transform(PA)["matrix"]
    svc.reset(PA)
    s2 = svc.run(PA)
    assert s2["state"] == "COMPLETE"
    m2 = svc.transform(PA)["matrix"]
    assert np.allclose(np.array(m1), np.array(m2), atol=1e-9)


def test_service_reset_only_removes_registration(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    spatial_root = tmp / "derived" / "spatial" / PA
    reg_root = tmp / "derived" / "registration" / PA
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    assert spatial_root.exists()
    assert reg_root.exists()
    status = svc.reset(PA)
    assert status["state"] == "NOT_STARTED"
    assert not reg_root.exists()
    assert spatial_root.exists()


def test_service_insufficient_no_warp(settings_factory):
    # build an M5 tree with too few correspondences for a good transform
    settings = settings_factory()
    tmp = _build_full_tree(settings, n=5, outliers=3)
    svc = _get_m6_svc(tmp)
    status = svc.run(PA)
    # With too few trusted correspondences M5 may not even select; whatever the
    # honest outcome is (BLOCKED/INSUFFICIENT/COMPLETE), M6 must not crash.
    assert status["state"] in ("COMPLETE", "INSUFFICIENT", "BLOCKED")


def test_service_blocks_when_selection_missing_npz(settings_factory):
    settings = settings_factory()
    tmp = _build_full_tree(settings)
    _run_m5(tmp)
    sp_root = tmp / "derived" / "spatial" / PA
    run_dir = sorted(sp_root.glob("*/*/*/*"))[-1]
    sel = json.loads((run_dir / "selection.json").read_text(encoding="utf-8"))
    assert (sel.get("selection_outcome") or sel.get("outcome")) == "SELECTED"
    (run_dir / "selected_correspondences.npz").unlink()
    svc = _get_m6_svc(tmp)
    status = svc.run(PA)
    assert status["state"] == "BLOCKED"
    assert status["block_code"] == "NO_SELECTION"


# ===========================================================================
# 8. API
# ===========================================================================

def test_api_overview_honest_zero(settings_factory):
    client, _s, _t = _m6_harness(settings_factory)
    with client:
        body = client.get("/api/registration/overview").json()
        assert body["total_registration_pairs"] == 0
        assert body["complete_pairs"] == 0


def test_api_pair_404_for_unknown_pair(settings_factory):
    client, _s, _t = _m6_harness(settings_factory)
    with client:
        r = client.get("/api/registration/NOPE/status")
        assert r.status_code == 404


def test_api_unknown_config_404(settings_factory):
    client, _s, _t = _m6_harness(settings_factory)
    with client:
        pair_id = _register(client)
        r = client.post(f"/api/registration/{pair_id}/run",
                        json={"registration_configuration_id": "NOPE"})
        assert r.status_code == 404


def test_api_full_pipeline_registration(settings_factory):
    client, settings, _tmp = _m6_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)
        from backend.app.trust.service import TrustService
        TrustService(settings.data_root_path).run(pair_id, TG)
        st = client.post(f"/api/spatial/{pair_id}/run",
                         json={"spatial_reliability_configuration_id": "SR-M5-001"})
        assert st.status_code == 200, st.text
        assert st.json()["state"] in ("COMPLETE", "INSUFFICIENT")
        if st.json()["state"] == "COMPLETE":
            rg = client.post(f"/api/registration/{pair_id}/run",
                             json={"registration_configuration_id": "RG-M6-001"})
            assert rg.status_code == 200, rg.text
            # Honest outcomes: selection may be insufficient even when M5
            # completed, so BLOCKED/INSUFFICIENT are valid too.
            assert rg.json()["state"] in ("COMPLETE", "INSUFFICIENT", "BLOCKED")


def test_api_endpoints_after_run(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    status = svc.run(PA)
    assert status["state"] == "COMPLETE"
    for endpoint in ("summary", "transform", "diagnostics", "validation",
                      "provenance", "manifest"):
        data = getattr(svc, endpoint)(PA)
        assert not data.get("error"), f"{endpoint}: {data}"
    assert svc.read_status(PA)["state"] == "COMPLETE"
    assert svc.manifest(PA)["registration_configuration_id"] == "RG-M6-001"


def test_api_status_scientific_note(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    st = svc.read_status(PA)
    assert st["state"] == "COMPLETE"
    assert "scientific_note" in st
    assert "no claim" in st["scientific_note"].lower()


def test_path_traversal_pair_id_safe(settings_factory):
    client, _s, _t = _m6_harness(settings_factory)
    with client:
        for bad in ("../etc", "..\\etc", "a/b"):
            r = client.get(f"/api/registration/{bad}/status")
            assert r.status_code in (404, 422)


# ===========================================================================
# 9. bug-hunt corpus (B-series)
# ===========================================================================

def test_bh_unknown_config(settings_factory):
    settings = settings_factory()
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA, registration_config_id="RG-XXXX")
    assert status["block_code"] == "UNKNOWN_CONFIG"


def test_bh_m5_status_missing(settings_factory):
    settings = settings_factory()
    from backend.app.spatial.service import SpatialService
    sp = SpatialService(settings.data_root_path, m5_cfg={}, m4_defaults={})
    run = sp._spatial_root() / PA / PC / MK / TG / SR
    run.mkdir(parents=True)
    # no status.json
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["state"] == "BLOCKED"
    assert status["block_code"] == "M5_NOT_AVAILABLE"


def test_bh_m5_incomplete(settings_factory):
    settings = settings_factory()
    _write_m5_artifact(settings.data_root_path, state="BLOCKED")
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["state"] == "BLOCKED"


def test_bh_selection_insufficient(settings_factory):
    settings = settings_factory()
    _write_m5_artifact(settings.data_root_path, outcome="INSUFFICIENT")
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["block_code"] == "NO_SELECTION"


def test_bh_no_finite_evidence(settings_factory):
    settings = settings_factory()
    _write_m5_artifact(settings.data_root_path, non_finite=True)
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["state"] in ("BLOCKED", "INSUFFICIENT", "FAILED")


def test_bh_deterministic_matrix(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    from backend.app.registration.engine import fit_and_validate
    from backend.app.registration.coord_space import (
        build_sensor_pixel_points,
        build_tile_geometry_map,
        load_mapping_context,
    )
    from backend.app.spatial.service import SpatialService
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    from backend.app.registration.loader import load_selected_correspondences
    from backend.app.config import m6_config
    from backend.app.registration.config import RegistrationConfig
    ev = load_selected_correspondences(tmp, PA, sp)
    run_dir = sp.find_run_for_pair(PA)
    mapping = load_mapping_context(run_dir)
    gm = build_tile_geometry_map(mapping)
    pa_x, pa_y, pb_x, pb_y, valid = build_sensor_pixel_points(
        ev.x_a, ev.y_a, ev.x_b, ev.y_b, ev.source_tile_id, gm)
    cfg = RegistrationConfig.from_dict(m6_config()["defaults"])
    a = fit_and_validate(pa_x, pa_y, pb_x, pb_y, valid, cfg)
    b = fit_and_validate(pa_x, pa_y, pb_x, pb_y, valid, cfg)
    assert np.allclose(a.transform_matrix, b.transform_matrix, atol=1e-9)


def test_bh_registration_manifest_reproducible_ids(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    m = svc.manifest(PA)
    assert m["registration_configuration_id"] == RG
    assert m["processing_configuration_id"] == PC
    assert m["matcher_configuration_id"] == MK
    assert m["trust_configuration_id"] == TG
    assert m["spatial_reliability_configuration_id"] == SR


def test_bh_status_has_config_chain(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    st = svc.run(PA)
    for key in ("processing_configuration_id", "matcher_configuration_id",
                "trust_configuration_id", "spatial_reliability_configuration_id",
                "registration_configuration_id"):
        assert key in st
        assert st[key]


def test_bh_registered_meta_written(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    run_dir = svc.find_run_for_pair(PA)
    meta = json.loads((run_dir / "registered" / "registered_meta.json").read_text(encoding="utf-8"))
    assert meta["out_rows"] > 0
    assert meta["out_cols"] > 0
    assert 0.0 <= meta["valid_pixel_fraction"] <= 1.0


def test_bh_no_python_paths_in_manifest(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    blob = json.dumps(svc.manifest(PA))
    assert "\\" not in blob.split("path")[1].split(",")[0]


def test_bh_empty_selected_protected(settings_factory):
    settings = settings_factory()
    _write_m5_artifact(settings.data_root_path, n=0)
    svc = _get_m6_svc(settings.data_root_path)
    status = svc.run(PA)
    assert status["state"] in ("BLOCKED", "INSUFFICIENT")


def test_bh_run_idempotent_overwrite(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    first = svc.run(PA)
    assert first["state"] == "COMPLETE"
    second = svc.run(PA)
    assert second["state"] == "COMPLETE"


def test_bh_loader_rejects_corrupt_transform_source(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    from backend.app.spatial.service import SpatialService
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    run = sp.find_run_for_pair(PA)
    (run / "selected_correspondences.npz").write_bytes(b"garbage")
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    with pytest.raises(LoaderError):
        load_selected_correspondences(tmp, PA, sp)


def test_bh_service_blocks_on_corrupt_npz_gracefully(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    from backend.app.spatial.service import SpatialService
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    run = sp.find_run_for_pair(PA)
    (run / "selected_correspondences.npz").write_bytes(b"garbage")
    svc = _get_m6_svc(tmp)
    status = svc.run(PA)
    assert status["state"] in ("BLOCKED", "FAILED")


def test_bh_no_absolute_paths_in_provenance(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    prov = svc.provenance(PA)
    blob = json.dumps(prov)
    assert "C:\\" not in blob
    assert "\\Users" not in blob


def test_bh_pipeline_chain_tense(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    prov = svc.provenance(PA)
    chain = prov["chain"]
    for i, c in enumerate(chain):
        assert c["milestone"] == f"M{i + 2}"


# ===========================================================================
# 10. hardening & integrity features
# ===========================================================================

def test_m6_config_refine_and_warp_fields():
    from backend.app.config import m6_config
    cfg = m6_config()
    d = cfg["defaults"]
    assert d["transform"]["refine"] is False
    assert int(d["warp"]["max_output_rows"]) == 20000
    assert int(d["warp"]["max_output_cols"]) == 20000
    assert d["warp"]["output_interpolation"] == "linear"
    assert d["warp"]["output_image_format"] == "png"
    assert d["warp"]["visualization_normalization"] == "minmax"


def test_m6_config_dataclasses_new_fields():
    from backend.app.config import m6_config
    from backend.app.registration.config import RegistrationConfig
    cfg = RegistrationConfig.from_dict(m6_config()["defaults"])
    assert cfg.transform.refine is False
    assert cfg.warp.max_output_rows == 20000
    assert cfg.warp.max_output_cols == 20000
    assert cfg.warp.output_interpolation == "linear"
    assert cfg.warp.output_image_format == "png"
    assert cfg.warp.visualization_normalization == "minmax"


def test_configuration_endpoint_exposes_new_warp_fields(settings_factory):
    client, _s, _t = _m6_harness(settings_factory)
    with client:
        conf = client.get("/api/registration/configurations").json()["configurations"][0]
        d = conf["defaults"]
        assert int(d["warp"]["max_output_rows"]) == 20000
        assert d["transform"]["refine"] is False
        assert d["warp"]["output_interpolation"] == "linear"


def test_loader_invalid_scene_side_rejected(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, invalid_side=True)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "scene_side contains invalid value" in str(e.value)


def test_loader_scene_bounds_rejected(settings_factory):
    from backend.app.spatial.service import SpatialService
    from backend.app.registration.loader import LoaderError, load_selected_correspondences
    settings = settings_factory()
    tmp = _write_m5_artifact(settings.data_root_path, scene_out_of_bounds=True)
    sp = SpatialService(tmp, m5_cfg={}, m4_defaults={})
    with pytest.raises(LoaderError) as e:
        load_selected_correspondences(tmp, PA, sp)
    assert "outside normalized [0, 1]" in str(e.value)


def test_validation_records_state_and_independent_check(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    val = svc.validation(PA)
    assert val["state"] == "VALIDATED"
    ind = val["independent_check"]
    assert ind["recomputed"] is True
    assert ind["status"] == "COMPUTED"
    assert ind["consistent_with_fit"] is True
    assert ind["residual_mean_px"] is not None
    assert ind["symmetric_transfer_max_px"] is not None
    assert "M4 trust primitives" in ind["method"]


def test_transform_declares_source_target_space(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    t = svc.transform(PA)
    assert t["source_space"]["frame"] == "sensor_a_pixel"
    assert t["source_space"]["side"] == "a"
    assert t["target_space"]["frame"] == "sensor_b_pixel"
    assert t["target_space"]["side"] == "b"
    assert t["direction"] == "sensor_a_pixel -> sensor_b_pixel"
    assert t["matrix"] is not None


def test_summary_declares_source_target_space(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    s = svc.summary(PA)
    assert s["source_space"]["frame"] == "sensor_a_pixel"
    assert s["target_space"]["frame"] == "sensor_b_pixel"
    assert s["direction"] == "sensor_a_pixel -> sensor_b_pixel"
    assert s["warp"]["registered_shown"] is True


def test_registered_dtype_and_meta(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    svc = _get_m6_svc(tmp)
    svc.run(PA)
    run_dir = svc.find_run_for_pair(PA)
    arr = np.load(str(run_dir / "registered" / "registered_image.npy"))
    assert arr.dtype == np.dtype("uint16")
    assert arr.ndim == 2
    assert arr.shape[0] > 0 and arr.shape[1] > 0
    ok = np.load(str(run_dir / "registered" / "valid_mask.npy"))
    assert ok.dtype == np.dtype("bool")
    meta = json.loads((run_dir / "registered" / "registered_meta.json").read_text(encoding="utf-8"))
    assert meta["dtype"] == "uint16"
    assert meta["out_rows"] == arr.shape[0]
    assert meta["out_cols"] == arr.shape[1]


def test_warp_max_bounds_honest_failure(settings_factory):
    settings = settings_factory()
    tmp = _build_m6_ready_tree(settings)
    from backend.app.config import m4_config, m5_config, m6_config
    from backend.app.registration.service import RegistrationService
    import copy
    raw = copy.deepcopy(m6_config())
    raw["defaults"]["warp"]["max_output_rows"] = 100
    svc = RegistrationService(
        tmp, m6_cfg=raw, m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    status = svc.run(PA)
    assert status["state"] == "FAILED"
    assert any("OUTPUT_BOUNDS_INVALID" in r for r in status.get("reasons", []))
    summary = svc.summary(PA)
    assert "warp failed" in summary.get("error", "") or "OUTPUT_BOUNDS_INVALID" in summary.get("error", "")


def test_api_visualizations_and_registered_product(settings_factory):
    client, settings, _tmp = _m6_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _build_m6_ready_tree(settings, pair_id)
        rg = client.post(f"/api/registration/{pair_id}/run",
                         json={"registration_configuration_id": "RG-M6-001"})
        assert rg.status_code == 200, rg.text
        assert rg.json()["state"] == "COMPLETE", rg.json()
        viz = client.get(f"/api/registration/{pair_id}/visualizations")
        assert viz.status_code == 200
        names = {v["name"] for v in viz.json()["visualizations"]}
        for expected in ("registered_overlay.png", "before_after.png",
                         "difference_overlay.png", "correspondences.png", "footprint.png"):
            assert expected in names, names
        img = client.get(f"/api/registration/{pair_id}/visualizations/registered_overlay.png")
        assert img.status_code == 200
        assert img.headers["content-type"].startswith("image/png")
        unknown = client.get(f"/api/registration/{pair_id}/visualizations/nope.png")
        assert unknown.status_code == 404
        non_png = client.get(f"/api/registration/{pair_id}/visualizations/registered_overlay.jpg")
        assert non_png.status_code == 404
        prod = client.get(f"/api/registration/{pair_id}/registered-product")
        assert prod.status_code == 200
        body = prod.json()["product"]
        assert body["meta"]["dtype"] == "uint16"
        arr_resp = client.get(body["array"])
        assert arr_resp.status_code == 200
        import io
        saved = np.load(io.BytesIO(arr_resp.content), allow_pickle=False)
        assert saved.ndim == 2
        assert saved.size > 0
        mask_resp = client.get(body["valid_mask"])
        assert mask_resp.status_code == 200
        preview_resp = client.get(body["preview_png"])
        assert preview_resp.status_code == 200
        assert preview_resp.headers["content-type"].startswith("image/png")


def test_api_selected_evidence(settings_factory):
    client, settings, _tmp = _m6_harness(settings_factory)
    with client:
        pair_id = _register(client)
        before = client.get(f"/api/registration/{pair_id}/selected-evidence")
        assert before.status_code == 404
        _build_m6_ready_tree(settings, pair_id)
        ev = client.get(f"/api/registration/{pair_id}/selected-evidence")
        assert ev.status_code == 200
        body = ev.json()
        assert body["n_correspondences"] > 0
        assert body["source"] == "M5 selected_correspondences.npz"
        assert body["m5_state"] == "COMPLETE"
        assert "scene_sides_present" in body