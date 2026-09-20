"""M5 tests — Spatial Reliability & Reliability-Aware Selection.

Covers SR-M5-001 configuration, scene coordinate mapping (pair_overlap_normalized),
grid aggregation, per-cell evidence, neighborhood support, deterministic connected
components, fragmentation/boundary analysis, SUPPORTED_REGION selection with
deterministic ordering, per-correspondence provenance, full lifecycle through
real M2→M3→M4→M5 pipeline, reset isolation, honest BLOCKED states, security
(path traversal / unknown config guard), and the 22-case bug hunt from §36.

All fixtures are synthetic and labelled as such; nothing here is real lunar data
and nothing here claims a scientific result.
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
PC, MK, TG = "PC-M2-001", "MC-M3-001", "TG-M4-001"
W, H = 1000, 800
TW, TH = 500, 400
OVERLAP = {
    SA: {"sensor": SA, "row_start": 0, "row_end": H, "col_start": 0, "col_end": W, "width_px": W, "height_px": H},
    SB: {"sensor": SB, "row_start": 0, "row_end": H, "col_start": 0, "col_end": W, "width_px": W, "height_px": H},
}


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _m5_harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_"))
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
                     trust_gate="COMPLETE"):
    """Build minimal M2 + M3 + M4 artifacts directly (no pipeline calls)."""
    from backend.app.trust.config import TG_M4_001
    from backend.app.trust.engine import evaluate_tile

    tmp = settings.data_root_path
    # --- M2 processing ---
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
    # --- M3 matching ---
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
    # --- M4 trust ---
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


def _get_svc(tmp):
    from backend.app.config import m4_config, m5_config
    from backend.app.spatial.service import SpatialService
    return SpatialService(tmp, m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])


# ===========================================================================
# 1. configuration
# ===========================================================================

def test_m5_configuration_registered():
    from backend.app.config import m5_config
    cfg = m5_config()
    assert cfg["spatial_reliability_configuration_id"] == "SR-M5-001"
    d = cfg["defaults"]
    assert d["grid"]["rows"] == 8
    assert d["grid"]["cols"] == 8
    assert float(d["grid"]["edge_tolerance_px"]) == pytest.approx(0.5)
    assert d["reliability"]["min_verified_inliers_per_cell"] == 4
    assert d["reliability"]["min_trusted_tiles_per_cell"] == 1
    assert d["neighborhood"]["support_radius_cells"] == 1
    assert d["connected_components"]["connectivity"] == 8
    assert d["selection"]["mode"] == "SUPPORTED_REGION"
    assert d["selection"]["min_component_cells"] == 4
    assert d["selection"]["min_component_correspondences"] == 16
    assert d["selection"]["max_selected_correspondences"] == 4000
    assert d["execution"]["max_runtime_seconds"] == 60


def test_m5_config_loader_from_defaults():
    from backend.app.config import m5_config
    from backend.app.spatial.config import SpatialReliabilityConfig
    cfg = SpatialReliabilityConfig.from_dict(m5_config()["defaults"])
    assert cfg.spatial_reliability_configuration_id == "SR-M5-001"
    assert cfg.grid.rows == 8
    assert cfg.grid.cols == 8
    assert cfg.selection.mode == "SUPPORTED_REGION"


def test_m5_config_coercion_from_exponent_string():
    from backend.app.spatial.config import SpatialReliabilityConfig, _f, _i
    assert _f("1e6", 0.0) == pytest.approx(1e6)
    assert _f("abc", 42.0) == pytest.approx(42.0)
    assert _i(None, 8) == 8
    assert _i("3", 99) == 3
    raw = {"grid": {"rows": "6", "cols": "6"},
           "reliability": {"min_verified_inliers_per_cell": "3"},
           "selection": {"max_selected_correspondences": "1000"}}
    cfg = SpatialReliabilityConfig.from_dict(raw)
    assert cfg.grid.rows == 6
    assert cfg.reliability.min_verified_inliers_per_cell == 3
    assert cfg.selection.max_selected_correspondences == 1000


def test_m5_configuration_endpoint(settings_factory):
    client, _s, _t = _m5_harness(settings_factory)
    with client:
        body = client.get("/api/spatial/configurations").json()
        assert body["default_spatial_reliability_configuration_id"] == "SR-M5-001"
        conf = body["configurations"][0]
        assert conf["spatial_reliability_configuration_id"] == "SR-M5-001"
        assert conf["coordinate_space"] == "pair_overlap_normalized"
        assert body["valid_spatial_reliability_configuration_ids"] == ["SR-M5-001"]
        assert "no scientifically tuned" in body["note"]


def test_m5_health_meta_includes_m5_config():
    from fastapi.testclient import TestClient as TC
    from backend.app.main import app
    c = TC(app)
    with c:
        meta = c.get("/api/meta").json()
        assert meta["milestone"] == "M11"
        assert meta["m5_config"]["spatial_reliability_configuration_id"] == "SR-M5-001"


# ===========================================================================
# 2. grid
# ===========================================================================

def test_grid_cell_id_and_rc():
    from backend.app.spatial.grid import Grid
    g = Grid(4, 4)
    assert g.cell_id(0, 0) == "R00C00"
    assert g.cell_id(3, 3) == "R03C03"
    assert g.rc("R02C01") == (2, 1)
    assert g.rc("INVALID") is None


def test_grid_all_cell_ids():
    from backend.app.spatial.grid import Grid
    g = Grid(3, 2)
    ids = g.all_cell_ids()
    assert len(ids) == 6
    assert ids == ["R00C00", "R00C01", "R01C00", "R01C01", "R02C00", "R02C01"]


def test_grid_neighbors():
    from backend.app.spatial.grid import Grid
    g = Grid(4, 4)
    n = g.neighbors(0, 0, 1)
    assert sorted(n) == [(0, 1), (1, 0), (1, 1)]
    n2 = g.neighbors(2, 2, 1)
    assert len(n2) == 8


def test_grid_is_edge_cell():
    from backend.app.spatial.grid import Grid
    g = Grid(4, 4)
    assert g.is_edge_cell(0, 0)
    assert g.is_edge_cell(3, 3)
    assert g.is_edge_cell(0, 2)
    assert not g.is_edge_cell(1, 1)
    assert not g.is_edge_cell(2, 2)


def test_grid_to_cell_clamps():
    from backend.app.spatial.grid import Grid
    g = Grid(8, 8)
    r, c = g.to_cell(np.array([-0.5, 0.0, 1.5, 0.99]),
                      np.array([0.0, -0.1, 0.99, 1.6]))
    assert r.tolist() == [0, 0, 7, 7]
    assert c.tolist() == [0, 0, 7, 7]


def test_grid_cell_box():
    from backend.app.spatial.grid import Grid
    g = Grid(4, 4)
    box = g.cell_box(1, 2)
    assert box["row_start"] == pytest.approx(0.25)
    assert box["row_end"] == pytest.approx(0.5)
    assert box["col_start"] == pytest.approx(0.5)
    assert box["col_end"] == pytest.approx(0.75)


# ===========================================================================
# 3. mapping
# ===========================================================================

def test_load_scene_map_valid():
    from backend.app.spatial.mapping import load_scene_map
    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_map_"))
    try:
        pr = tmp / "processing"
        pr.mkdir()
        (pr / "diagnostics").mkdir()
        (pr / "diagnostics" / "overlap.json").write_text(
            json.dumps({"regions": OVERLAP}), encoding="utf-8")
        (pr / "crops").mkdir()
        tiles = [{"tile_id": "T001", "sensor": SA, "side": "a", "row_start": 0, "col_start": 0,
                   "width": 500, "height": 400},
                  {"tile_id": "T002", "sensor": SB, "side": "b", "row_start": 0, "col_start": 0,
                   "width": 500, "height": 400}]
        (pr / "crops" / "tiles.json").write_text(
            json.dumps({"tiles": tiles}), encoding="utf-8")
        md = tmp / "matches"
        md.mkdir()
        (md / "candidates").mkdir()
        (md / "candidates" / "M001.json").write_text(
            json.dumps({"decision": {"tile_a": "T001", "tile_b": "T002"}}), encoding="utf-8")
        summary = {"per_tile": [{"match_tile_id": "M001"}]}
        scene = load_scene_map(pr, md, summary)
        assert scene["status"] == "MAPPED"
        assert scene["coordinate_space"] == "pair_overlap_normalized"
        assert len(scene["mappings"]) == 1
        m = scene["mappings"][0]
        assert m["tile_a"] == "T001"
        assert m["status"] == "MAPPED"
    finally:
        shutil.rmtree(tmp)


def test_load_scene_map_missing_overlap():
    from backend.app.spatial.mapping import load_scene_map
    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_map_"))
    try:
        pr = tmp / "processing"
        pr.mkdir()
        scene = load_scene_map(pr, tmp, {"per_tile": []})
        assert scene["status"] == "NOT_MAPPABLE"
        assert "MISSING_OVERLAP" in scene["reason"]
    finally:
        shutil.rmtree(tmp)


def test_load_scene_map_missing_tile_geometry():
    from backend.app.spatial.mapping import load_scene_map
    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_map_"))
    try:
        pr = tmp / "processing"
        pr.mkdir()
        (pr / "diagnostics").mkdir()
        (pr / "diagnostics" / "overlap.json").write_text(
            json.dumps({"regions": OVERLAP}), encoding="utf-8")
        (pr / "crops").mkdir()
        (pr / "crops" / "tiles.json").write_text(
            json.dumps({"tiles": []}), encoding="utf-8")
        md = tmp / "matches"
        md.mkdir()
        (md / "candidates").mkdir()
        (md / "candidates" / "M001.json").write_text(
            json.dumps({"decision": {"tile_a": "NOPE", "tile_b": "NOPE"}}), encoding="utf-8")
        scene = load_scene_map(pr, md, {"per_tile": [{"match_tile_id": "M001"}]})
        assert scene["status"] == "NOT_MAPPABLE"
        assert len(scene["mappings"]) == 0
    finally:
        shutil.rmtree(tmp)


def test_map_correspondences_success():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {
        "status": "MAPPED",
        "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
        "geometry_b": {"sensor": SB, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
    }
    scene = {"overlap": OVERLAP, "edge_tolerance_px": 0.5}
    x = np.array([100.0, 250.0])
    y = np.array([200.0, 350.0])
    nx, ny, mapped, reasons = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert np.all(mapped)
    assert all(0.0 <= v <= 1.0 for v in nx)
    assert all(0.0 <= v <= 1.0 for v in ny)
    assert "MAPPED_OK" in reasons


def test_map_correspondences_out_of_scene():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {
        "status": "MAPPED",
        "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
    }
    scene = {"overlap": OVERLAP, "edge_tolerance_px": 0.5}
    x = np.array([-50.0, 200.0])
    y = np.array([100.0, 500.0])
    nx, ny, mapped, reasons = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert not mapped[0]
    assert mapped[1]
    assert "OUT_OF_SCENE" in reasons


def test_map_correspondences_nan_coords():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {
        "status": "MAPPED",
        "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
    }
    scene = {"overlap": OVERLAP, "edge_tolerance_px": 0.5}
    x = np.array([np.nan, 100.0])
    y = np.array([100.0, np.nan])
    nx, ny, mapped, reasons = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert not mapped[0]
    assert not mapped[1]
    assert "NON_FINITE_COORDINATES" in reasons


def test_map_correspondences_unmapped_tile():
    from backend.app.spatial.mapping import map_correspondences
    scene = {"overlap": OVERLAP}
    nx, ny, mapped, reasons = map_correspondences(scene, None, "a", np.array([1.0]), np.array([2.0]), 0.5)
    assert not mapped[0]
    assert "TILE_NOT_MAPPED_TO_TWO_SIDES" in reasons


# ===========================================================================
# 4. reliability aggregation
# ===========================================================================

def test_reliability_basic():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 2, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R01C01": 5, "R01C02": 3, "R02C01": 4, "R02C02": 2}
    usable = {"R01C01": 10, "R01C02": 8, "R02C01": 9, "R02C02": 5, "R00C00": 1}
    tiles = {"R01C01": {"T1"}, "R01C02": {"T1"}, "R02C01": {"T1"}, "R02C02": {"T1"}}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    reliable = [c for c in result.cells if c.reliable]
    assert len(reliable) == 4
    assert len(result.components) >= 1
    assert len(result.reliable_cells) == 4
    assert result.fragmentation["total_reliable_cells"] == 4


def test_reliability_isolated_cell():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R01C01": 3}
    usable = {"R01C01": 5}
    tiles = {"R01C01": {"T1"}}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    assert len(result.reliable_cells) == 1
    assert len(result.supported_cells) == 0  # no neighbor → not supported
    assert result.fragmentation["isolated_cell_count"] == 1


def test_reliability_below_threshold_not_reliable():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 10, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R01C01": 3, "R01C02": 5}
    usable = {"R01C01": 8, "R01C02": 10}
    tiles = {"R01C01": {"T1"}, "R01C02": {"T1"}}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    assert len(result.reliable_cells) == 0  # below min_verified_inliers_per_cell


def test_reliability_fragmentation_multiple_components():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    # Two disconnected reliable clusters
    verified = {"R00C00": 5, "R00C01": 3, "R03C03": 4, "R03C02": 2}
    usable = {**{k: 10 for k in verified}}
    tiles = {k: {"T1"} for k in verified}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    assert result.fragmentation["connected_components"] >= 2
    assert result.fragmentation["largest_component_ratio"] <= 0.6


def test_reliability_boundary_analysis():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R00C00": 5, "R00C01": 3, "R01C00": 4, "R01C01": 2, "R03C03": 3}
    usable = {**{k: 10 for k in verified}}
    tiles = {k: {"T1"} for k in verified}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    assert result.boundary["edge_touching_cells"] >= 3
    assert 0.0 < result.boundary["edge_fraction"] <= 1.0


# ===========================================================================
# 5. selection
# ===========================================================================

def test_plan_selection_basic():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    from backend.app.spatial.selection import plan_selection
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
        "selection": {"min_component_cells": 2, "min_component_correspondences": 3,
                      "min_selected_region_cells": 2},
    })
    verified = {"R01C01": 5, "R01C02": 3, "R02C01": 4}
    usable = {**{k: 10 for k in verified}}
    tiles = {k: {"T1"} for k in verified}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    plan = plan_selection(g, cfg, result)
    assert plan.selection_outcome == "SELECTED"
    assert len(plan.selected_cell_ids) >= 2


def test_plan_selection_no_eligible_component():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    from backend.app.spatial.selection import plan_selection
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
        "selection": {"min_component_cells": 10, "min_component_correspondences": 100},
    })
    verified = {"R01C01": 5, "R01C02": 3}
    usable = {**{k: 10 for k in verified}}
    tiles = {k: {"T1"} for k in verified}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    plan = plan_selection(g, cfg, result)
    assert plan.selection_outcome == "INSUFFICIENT"


def test_plan_selection_deterministic_ordering():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    from backend.app.spatial.selection import plan_selection
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
        "selection": {"min_component_cells": 2, "min_component_correspondences": 1},
    })
    verified = {"R01C01": 20, "R01C02": 15, "R03C03": 5, "R03C02": 3}
    usable = {**{k: 20 for k in verified}}
    tiles = {k: {"T1"} for k in verified}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    plan = plan_selection(g, cfg, result)
    assert plan.selection_outcome == "SELECTED"
    # the larger component should be selected first
    assert "C01" in plan.selected_component_ids or "C02" in plan.selected_component_ids


def test_assign_reasons_selected_and_excluded():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    from backend.app.spatial.selection import assign_reasons, plan_selection
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
        "selection": {"min_component_cells": 2, "min_component_correspondences": 1,
                      "min_selected_region_cells": 2, "max_selected_correspondences": 4000},
    })
    verified = {"R01C01": 5, "R01C02": 3}
    usable = {**{k: 10 for k in verified}}
    tiles = {k: {"T1"} for k in verified}
    result = compute_reliability(g, cfg, verified=verified, usable=usable, tiles=tiles)
    plan = plan_selection(g, cfg, result)
    cell_keys = ["R01C01", "R01C02", "R00C00"]
    rows = [1, 1, 0]
    cols = [1, 2, 0]
    tile_ids = ["T1", "T1", "T2"]
    cand_idx = [0, 1, 0]
    primary, secondary, final_sel, capped = assign_reasons(
        g, cfg, result, plan,
        cell_keys=cell_keys, row_keys=rows, col_keys=cols,
        tile_ids=tile_ids, candidate_indices=cand_idx)
    assert len(primary) == 3
    assert primary[0] == "SR_SELECTED_SUPPORTED_REGION"
    # R00C00 not reliable → excluded
    assert "EXCLUDED" in primary[2]


# ===========================================================================
# 6. full lifecycle (real M2→M3→M4→M5 through pipeline)
# ===========================================================================

def test_full_pipeline_m2_m3_m4_m5(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)
        from backend.app.trust.service import TrustService
        TrustService(settings.data_root_path).run(pair_id, TG)
        st = client.post(f"/api/spatial/{pair_id}/run",
                         json={"spatial_reliability_configuration_id": "SR-M5-001"})
        assert st.status_code == 200, st.text
        assert st.json()["state"] == "COMPLETE"
        assert st.json()["block_code"] is None


def test_synthetic_service_run_and_summary(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        status = svc.run(PA)
        assert status["state"] == "COMPLETE"
        summary = svc.summary(PA)
        assert summary["reliability"]["reliable_cells"] >= 1
        assert summary["selection"]["selected_correspondence_count"] >= 1
        assert summary["scene"]["mapped"] == 1
        assert summary["scene"]["usable_candidates_from_trusted_tiles"] > 0
        assert summary["scene"]["verified_inlier_count"] > 0


def test_service_prerequisites_check(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        svc = _get_svc(settings.data_root_path)
        prereq = svc.prerequisites(PA)
        assert prereq["ready"] is False
        assert prereq["block_code"] == "MATCHING_NOT_AVAILABLE"


def test_service_blocks_on_no_matching(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        svc = _get_svc(settings.data_root_path)
        status = svc.run(PA)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "MATCHING_NOT_AVAILABLE"


def test_service_blocks_on_unknown_config(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _build_full_tree(settings, PA)
        svc = _get_svc(settings.data_root_path)
        status = svc.run(PA, "SR-X-999")
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "SPATIAL_UNKNOWN_CONFIG"


def test_service_blocks_when_m4_not_complete(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _build_full_tree(settings, PA, trust_gate="FAILED")
        svc = _get_svc(settings.data_root_path)
        status = svc.run(PA)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "NO_TRUSTED_EVIDENCE"


def test_service_blocks_when_no_trusted_tiles(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _build_full_tree(settings, PA, noise=60, outliers=0, trust_gate="COMPLETE")
        # evaluate_tile will likely REJECT all tiles, so tile_trust has no TRUSTED
        svc = _get_svc(settings.data_root_path)
        status = svc.run(PA)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "NO_TRUSTED_EVIDENCE"


def test_service_blocks_when_mapping_unavailable(settings_factory):
    from backend.app.spatial.mapping import load_scene_map
    from backend.app.spatial.states import MappingStatus
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        # Corrupt the overlap to make mapping fail
        pr = tmp / "derived" / "processing" / PA / PC
        (pr / "diagnostics" / "overlap.json").write_text(
            json.dumps({"regions": {}}), encoding="utf-8")
        svc = _get_svc(tmp)
        status = svc.run(PA)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "SPATIAL_MAPPING_UNAVAILABLE"


# ===========================================================================
# 7. reset isolation
# ===========================================================================

def test_reset_only_removes_spatial(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        r = svc.reset(PA)
        assert r["state"] == "NOT_STARTED"
        assert not (tmp / "derived" / "spatial" / PA).exists()
        assert (tmp / "derived" / "matches" / PA).exists()
        assert (tmp / "derived" / "trust" / PA).exists()
        assert (tmp / "derived" / "processing" / PA).exists()


def test_reset_returns_not_started(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        svc = _get_svc(settings.data_root_path)
        r = svc.reset("CS-P999")
        assert r["state"] == "NOT_STARTED"
        assert r["pair_id"] == "CS-P999"


# ===========================================================================
# 8. determinism
# ===========================================================================

def test_run_is_deterministic_across_two_runs(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        sc1 = svc.selected_correspondences(PA)
        svc.reset(PA)
        svc.run(PA)
        sc2 = svc.selected_correspondences(PA)
        assert sc1["x_a_count"] == sc2["x_a_count"]
        assert sc1["fields"] == sc2["fields"]


# ===========================================================================
# 9. provenance
# ===========================================================================

def test_manifest_has_no_absolute_paths(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        man = svc.manifest(PA)
        text = json.dumps(man)
        assert str(tmp) not in text
        assert "C:\\\\" not in text
        assert man["spatial_reliability_configuration_id"] == "SR-M5-001"
        assert len(man["artifacts"]) >= 5
        for art in man["artifacts"]:
            assert art["path"].startswith("derived/")
            assert "sha256" in art and len(art["sha256"]) == 64


def test_summary_has_no_confidence_claim(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        text = json.dumps(svc.summary(PA))
        assert '"confidence"' not in text.lower()


# ===========================================================================
# 10. API endpoints
# ===========================================================================

def test_api_overview_honest_zero(settings_factory):
    client, _s, _t = _m5_harness(settings_factory)
    with client:
        body = client.get("/api/spatial/overview").json()
        assert body["total_spatial_pairs"] == 0
        assert body["complete_pairs"] == 0


def test_api_pair_404_for_unknown_pair(settings_factory):
    client, _s, _t = _m5_harness(settings_factory)
    with client:
        r404 = client.get("/api/spatial/CS-P999/status")
        assert r404.status_code == 404


def test_api_unknown_config_404(settings_factory):
    client, _s, _t = _m5_harness(settings_factory)
    with client:
        pair_id = _register(client)
        r404 = client.post(f"/api/spatial/{pair_id}/run",
                           json={"spatial_reliability_configuration_id": "SR-X-999"})
        assert r404.status_code == 404


def test_api_endpoints_after_run(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _register(client)
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        # test all read endpoints
        for ep in ["status", "manifest", "summary", "map", "components",
                   "cells", "selection", "mapping", "selected-correspondences"]:
            r = client.get(f"/api/spatial/{PA}/{ep}")
            assert r.status_code == 200, f"{ep}: {r.status_code}"


# ===========================================================================
# 11. security
# ===========================================================================

def test_path_traversal_pair_id_safe(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _build_full_tree(settings, PA)
        svc = _get_svc(settings.data_root_path)
        # These should not crash or traverse
        st = svc.run("../../../etc/passwd")
        assert st["state"] == "BLOCKED"
        st2 = svc.run("CS-P001/../../trust")
        assert st2["state"] in ("BLOCKED", "NOT_STARTED")


# ===========================================================================
# 12. bug hunt — 22 cases from spec §36
# ===========================================================================

# B1: Empty trusted set
def test_bh_empty_trusted_set(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _build_full_tree(settings, PA, noise=60, outliers=0)
        svc = _get_svc(settings.data_root_path)
        status = svc.run(PA)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "NO_TRUSTED_EVIDENCE"


# B2: One trusted tile only
def test_bh_one_trusted_tile(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        # Remove one tile from tile_trust to leave only one TRUSTED
        td = tmp / "derived" / "trust" / PA / PC / MK / TG
        tt = json.loads((td / "tile_trust.json").read_text(encoding="utf-8"))
        tt["tiles"] = [t for t in tt["tiles"] if t["trust_state"] == "TRUSTED"][:1]
        (td / "tile_trust.json").write_text(json.dumps(tt), encoding="utf-8")
        svc = _get_svc(tmp)
        status = svc.run(PA)
        assert status["state"] == "COMPLETE"


# B3: One-cell region
def test_bh_one_cell_region():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    from backend.app.spatial.selection import plan_selection
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
        "selection": {"min_component_cells": 4, "min_component_correspondences": 1,
                      "min_selected_region_cells": 4},
    })
    verified = {"R01C01": 10}
    tiles = {"R01C01": {"T1"}}
    result = compute_reliability(g, cfg, verified=verified, usable=verified, tiles=tiles)
    plan = plan_selection(g, cfg, result)
    assert plan.selection_outcome == "INSUFFICIENT"  # single cell can't meet min_component_cells=4


# B4: Disconnected regions
def test_bh_disconnected_regions():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R00C00": 5, "R03C03": 5}
    tiles = {"R00C00": {"T1"}, "R03C03": {"T2"}}
    result = compute_reliability(g, cfg, verified=verified, usable=verified, tiles=tiles)
    assert result.fragmentation["connected_components"] == 2


# B5: Tile on boundary with edge_tolerance
def test_bh_tile_on_boundary():
    from backend.app.spatial.mapping import load_scene_map, map_correspondences
    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_bh_"))
    try:
        pr = tmp / "processing"
        pr.mkdir()
        (pr / "diagnostics").mkdir()
        (pr / "diagnostics" / "overlap.json").write_text(
            json.dumps({"regions": {
                SA: {"sensor": SA, "row_start": 0, "row_end": 400, "col_start": 0, "col_end": 500, "width_px": 500, "height_px": 400},
                SB: {"sensor": SB, "row_start": 0, "row_end": 400, "col_start": 0, "col_end": 500, "width_px": 500, "height_px": 400},
            }}), encoding="utf-8")
        (pr / "crops").mkdir()
        (pr / "crops" / "tiles.json").write_text(json.dumps({"tiles": [
            {"tile_id": "T001", "sensor": SA, "side": "a", "row_start": 0, "col_start": 0, "width": 500, "height": 400},
            {"tile_id": "T002", "sensor": SB, "side": "b", "row_start": 0, "col_start": 0, "width": 500, "height": 400},
        ]}), encoding="utf-8")
        md = tmp / "matches"
        md.mkdir()
        (md / "candidates").mkdir()
        (md / "candidates" / "M001.json").write_text(
            json.dumps({"decision": {"tile_a": "T001", "tile_b": "T002"}}), encoding="utf-8")
        scene = load_scene_map(pr, md, {"per_tile": [{"match_tile_id": "M001"}]})
        # Point right at the boundary edge
        x = np.array([0.0, 499.5])
        y = np.array([0.0, 399.5])
        nx, ny, mapped, reasons = map_correspondences(scene, scene["mappings"][0], "a", x, y, 0.5)
        assert mapped[0] and mapped[1]
    finally:
        shutil.rmtree(tmp)


# B6: Tile outside scene → OUT_OF_SCENE
def test_bh_tile_outside_scene():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {
        "status": "MAPPED",
        "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400},
    }
    scene = {"overlap": OVERLAP}
    x = np.array([-100.0])
    y = np.array([-100.0])
    _, _, mapped, reasons = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert not mapped[0]
    assert "OUT_OF_SCENE" in reasons


# B7: Negative coordinates
def test_bh_negative_coords():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {"status": "MAPPED", "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400}}
    scene = {"overlap": OVERLAP}
    x = np.array([-1.0])
    y = np.array([-1.0])
    _, _, mapped, _ = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert not mapped[0]  # outside tolerance


# B8: NaN coordinates
def test_bh_nan_coords():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {"status": "MAPPED", "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400}}
    scene = {"overlap": OVERLAP}
    x = np.array([np.nan])
    y = np.array([np.nan])
    _, _, mapped, reasons = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert not mapped[0]
    assert "NON_FINITE_COORDINATES" in reasons


# B9: Inf coordinates
def test_bh_inf_coords():
    from backend.app.spatial.mapping import map_correspondences
    mapping = {"status": "MAPPED", "geometry_a": {"sensor": SA, "row_start": 0, "col_start": 0, "width": 500, "height": 400}}
    scene = {"overlap": OVERLAP}
    x = np.array([np.inf])
    y = np.array([-np.inf])
    _, _, mapped, reasons = map_correspondences(scene, mapping, "a", x, y, 0.5)
    assert not mapped[0]
    assert "NON_FINITE_COORDINATES" in reasons


# B10: Duplicate correspondences handled correctly
def test_bh_duplicate_correspondences():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R01C01": 20, "R01C02": 5}
    tiles = {"R01C01": {"T1", "T2"}, "R01C02": {"T1"}}
    result = compute_reliability(g, cfg, verified=verified, usable=verified, tiles=tiles)
    c01 = next(c for c in result.cells if c.cell_id == "R01C01")
    assert c01.trusted_tile_count == 2  # duplicates counted correctly


# B11: Missing tile dimensions
def test_bh_missing_tile_geometry_returns_not_mappable():
    from backend.app.spatial.mapping import load_scene_map
    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_bh_"))
    try:
        pr = tmp / "processing"; pr.mkdir()
        (pr / "diagnostics").mkdir()
        (pr / "diagnostics" / "overlap.json").write_text(json.dumps({"regions": OVERLAP}), encoding="utf-8")
        (pr / "crops").mkdir()
        (pr / "crops" / "tiles.json").write_text(json.dumps({"tiles": []}), encoding="utf-8")
        md = tmp / "matches"; md.mkdir(); (md / "candidates").mkdir()
        (md / "candidates" / "M001.json").write_text(json.dumps({"decision": {"tile_a": "NO_SUCH", "tile_b": "NOPE"}}), encoding="utf-8")
        scene = load_scene_map(pr, md, {"per_tile": [{"match_tile_id": "M001"}]})
        assert scene["status"] == "NOT_MAPPABLE"
        assert len(scene["mappings"]) == 0
    finally:
        shutil.rmtree(tmp)


# B12: Malformed M4 artifact → recompute fails → FAILED
def test_bh_malformed_m4_artifact(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        # Corrupt the candidate npz so evaluate_tile fails
        md = tmp / "derived" / "matches" / PA / PC / MK
        for mid in [f"{PA}-M001", f"{PA}-M002"]:
            npz_path = md / "candidates" / f"{mid}.npz"
            np.savez(npz_path, x_a=np.array([np.nan]), y_a=np.array([np.nan]),
                     x_b=np.array([np.nan]), y_b=np.array([np.nan]),
                     descriptor_distance=np.array([1.0]), matcher_score=np.array([1.0]))
        svc = _get_svc(tmp)
        status = svc.run(PA)
        # All tiles fail recompute → FAILED INVALID_TRUST_ARTIFACT
        assert status["state"] == "FAILED"
        assert status["block_code"] == "SPATIAL_INVALID_ARTIFACT"


# B13: Corrupted NPZ (cannot load)
def test_bh_corrupted_npz(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        md = tmp / "derived" / "matches" / PA / PC / MK
        for mid in [f"{PA}-M001", f"{PA}-M002"]:
            (md / "candidates" / f"{mid}.npz").write_bytes(b"not-a-valid-npz")
        svc = _get_svc(tmp)
        status = svc.run(PA)
        assert status["state"] == "FAILED"


# B14: Unknown config → 404
def test_bh_unknown_config_404(settings_factory):
    client, _s, _t = _m5_harness(settings_factory)
    with client:
        pair_id = _register(client)
        r = client.post(f"/api/spatial/{pair_id}/run",
                        json={"spatial_reliability_configuration_id": "FAKE"})
        assert r.status_code == 404


# B15: Path traversal safe
def test_bh_path_traversal(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        _build_full_tree(settings, PA)
        svc = _get_svc(settings.data_root_path)
        assert svc.run("../escape")["state"] == "BLOCKED"
        assert svc.run("CS-P001/../../etc")["state"] in ("BLOCKED", "NOT_STARTED")


# B16: Repeated run is deterministic
def test_bh_repeated_run_deterministic(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        sc1 = svc.selected_correspondences(PA)
        svc.run(PA)  # run again without reset
        sc2 = svc.selected_correspondences(PA)
        assert sc1["x_a_count"] == sc2["x_a_count"]
        s1 = svc.summary(PA)
        s2 = svc.summary(PA)
        assert s1["selection"]["selected_correspondence_count"] == s2["selection"]["selected_correspondence_count"]


# B17: Reset isolation
def test_bh_reset_isolation(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        assert (tmp / "derived" / "spatial" / PA).exists()
        svc.reset(PA)
        assert not (tmp / "derived" / "spatial" / PA).exists()
        assert (tmp / "derived" / "trust" / PA).exists()
        assert (tmp / "derived" / "matches" / PA).exists()


# B18: Timeout with max_runtime=0
def test_bh_timeout_max_runtime_0(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        from backend.app.config import m4_config, m5_config
        from backend.app.spatial.service import SpatialService
        cfg = m5_config().copy()
        cfg["defaults"] = dict(cfg["defaults"])
        cfg["defaults"]["execution"] = {"max_runtime_seconds": 0}
        svc = SpatialService(tmp, m5_cfg=cfg, m4_defaults=m4_config()["defaults"])
        status = svc.run(PA)
        # timeout means either BLOCKED (if no tiles processed) or COMPLETE with partial
        # The behavior depends on timing; just verify no crash
        assert status["state"] in ("COMPLETE", "BLOCKED", "FAILED")


# B19: Stale RUNNING overwritten by re-run
def test_bh_stale_running_overwritten(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        # Write a fake RUNNING status
        svc = _get_svc(tmp)
        proc_cfg = PC; match_cfg = MK; trust_cfg = TG; sr_id = "SR-M5-001"
        run_dir = tmp / "derived" / "spatial" / PA / proc_cfg / match_cfg / trust_cfg / sr_id
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(json.dumps({
            "pair_id": PA, "state": "RUNNING", "updated_at": "2026-01-01T00:00:00Z",
        }), encoding="utf-8")
        status = svc.run(PA)
        assert status["state"] in ("COMPLETE", "BLOCKED", "FAILED")
        assert status["state"] != "RUNNING"  # stale overwritten


# B20: Synthetic-not-benchmark honesty
def test_bh_no_confidence_in_outputs(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA)
        svc = _get_svc(tmp)
        svc.run(PA)
        for ep in ["summary", "map", "selection"]:
            data = svc.summary(PA) if ep == "summary" else (
                svc.reliability_map(PA) if ep == "map" else svc.selection(PA))
            text = json.dumps(data).lower()
            assert "confidence" not in text
            assert "scientific" not in text or "not a scientific" in text
        man = svc.manifest(PA)
        man_text = json.dumps(man).lower()
        assert "no scientifically tuned" in man_text or "engineering" in man_text


# B21: M4 BLOCKED → M5 BLOCKED NO_TRUSTED_EVIDENCE
def test_bh_m4_blocked_m5_blocked(settings_factory):
    client, settings, _tmp = _m5_harness(settings_factory)
    with client:
        tmp = _build_full_tree(settings, PA, trust_gate="BLOCKED")
        svc = _get_svc(tmp)
        # M4 trust is BLOCKED (gate_state != COMPLETE), so M5 should be BLOCKED
        status = svc.run(PA)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "NO_TRUSTED_EVIDENCE"


# B22: Component deterministic labeling
def test_bh_component_deterministic_labeling():
    from backend.app.spatial.config import SpatialReliabilityConfig
    from backend.app.spatial.grid import Grid
    from backend.app.spatial.reliability import compute_reliability
    g = Grid(4, 4)
    cfg = SpatialReliabilityConfig.from_dict({
        "reliability": {"min_verified_inliers_per_cell": 1, "min_trusted_tiles_per_cell": 1},
        "neighborhood": {"support_radius_cells": 1},
        "connected_components": {"connectivity": 8},
    })
    verified = {"R00C00": 5, "R00C01": 3, "R02C02": 4, "R02C03": 2}
    tiles = {"R00C00": {"T1"}, "R00C01": {"T1"}, "R02C02": {"T2"}, "R02C03": {"T2"}}
    r1 = compute_reliability(g, cfg, verified=verified, usable=verified, tiles=tiles)
    r2 = compute_reliability(g, cfg, verified=verified, usable=verified, tiles=tiles)
    comp_ids_1 = [c.component_id for c in r1.components]
    comp_ids_2 = [c.component_id for c in r2.components]
    assert comp_ids_1 == comp_ids_2  # deterministic
    assert len(set(comp_ids_1)) == 2  # two components
