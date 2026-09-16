"""M4 tests — Trust Gate & independent geometric verification.

Covers the TG-M4-001 configuration, the deterministic RANSAC geometry layer
(linear DLT recovery, inlier/ratio/residual policy, degeneracy rejection), the
spatial support diagnostics, the symmetric transfer cross-check, the per-tile
TrustGateDecision engine, the full TRUST lifecycle over TEST_FIXTURE geometry
(through a real M3 MATCH run), the honest BLOCKED states, reset isolation,
provenance free of absolute paths, gate state determinism, and the guarantee
that M4 never fabricates a scientific result and never truncates M3 data.

All fixtures are synthetic and labelled as such; nothing here is real lunar
data and nothing here claims a scientific result.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fixturegen  # noqa: F401


def _m4_harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m4_"))
    fixturegen.write_correlated_fixtures(tmp)
    settings = Settings(data_root=str(tmp), _env_file=None)
    ensure_derived_directories(settings)
    app = create_app(settings=settings)
    return TestClient(app), settings, tmp


def _register(client) -> str:
    resp = client.post("/api/pairs/register", json={
        "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
        "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
        "overlap_status": "UNKNOWN",
    })
    assert resp.status_code == 200, resp.text
    pair_id = resp.json()["pair_id"]
    val = client.post(f"/api/pairs/{pair_id}/validate")
    assert val.status_code == 200, val.text
    assert val.json()["status"] == "VALID"
    return pair_id


CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M4 software validation only.",
    "products": {
        "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 0.5},
        "tmc2": {"row_offset_m": -2.0, "col_offset_m": -2.0, "gsd_m": 0.5},
    },
}


def _prepare(client, pair_id):
    resp = client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": CORRELATED_GEOMETRY})
    assert resp.status_code == 200, resp.text
    status = resp.json()
    assert status["state"] == "READY_FOR_MATCHING"
    assert status["matcher_readiness"]["ready"] is True
    return status


def _run_m3(client, pair_id) -> None:
    resp = client.post(f"/api/matching/{pair_id}/run", json={"configuration_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "COMPLETE"


def _fake_tile_npz(path: Path, *, n=75, tx=7.5, ty=-4.0, noise=0.5, outliers=15,
                   collinear=False, clustered=False):
    """Write a synthetic accepted-candidate npz (M3 schema) for an M4 tile.

    Inliers follow A -> B = A + (tx, ty) with sub-pixel noise; the rest are
    gross outliers.  `clustered` packs everything into one grid cell so the
    spatial support check must reject; `collinear` trivially fakes a
    degenerate layout.
    """
    rng = np.random.RandomState(20260417)
    xa = rng.uniform(40.0, 640.0, n)
    ya = rng.uniform(60.0, 380.0, n)
    xb = xa + tx
    yb = ya + ty
    xb += rng.normal(0, noise, n)
    yb += rng.normal(0, noise, n)
    n_out = min(outliers, n - 1)
    if n_out:
        xb[:n_out] += rng.uniform(-220, 220, n_out)
        yb[:n_out] += rng.uniform(-180, 300, n_out)
    if collinear:
        ya = 0.5 * xa + 3.0  # pts_a lie on a line
        xb = 2.0 * xa + 9.0
        yb = 0.5 * xb + 3.0
    if clustered:
        # 70% tightly clustered (same spot, no translation), 30% spread
        # so the inlier bounding box is large but >60% of inliers land in one cell
        n_c = int(n * 0.7)
        n_s = n - n_c
        xc = np.full(n_c, 480.0) + rng.uniform(-0.1, 0.1, n_c)
        yc = np.full(n_c, 260.0) + rng.uniform(-0.1, 0.1, n_c)
        xs = rng.uniform(40.0, 640.0, n_s)
        ys = rng.uniform(60.0, 380.0, n_s)
        xa = np.concatenate([xc, xs])
        ya = np.concatenate([yc, ys])
        xb = xa + rng.uniform(-0.1, 0.1, n)
        yb = ya + rng.uniform(-0.1, 0.1, n)
    np.savez(
        path,
        x_a=xa.astype(np.float64), y_a=ya.astype(np.float64),
        x_b=xb.astype(np.float64), y_b=yb.astype(np.float64),
        descriptor_distance=np.linspace(40.0, 90.0, n).astype(np.float64),
        matcher_score=np.linspace(0.95, 0.5, n).astype(np.float64),
    )
    return path


def _fake_m3_tree(match_dir: Path, tiles, proc_cfg="PC-M2-001", matcher_id="MC-M3-001") -> None:
    """Write the real M3 output layout (summary.json + candidates/<id>.npz)."""
    cand_dir = match_dir / "candidates"
    cand_dir.mkdir(parents=True, exist_ok=True)
    per_tile = []
    for t in tiles:
        tid = t["match_tile_id"]
        _fake_tile_npz(cand_dir / f"{tid}.npz", n=t["candidates"])
        per_tile.append({
            "match_tile_id": tid, "outcome": "SUCCESS",
            "candidates": t["candidates"],
            "strategy_used": "sift", "proposed_strategy": "sift",
        })
    summary = {
        "pair_id": match_dir.parent.name,
        "configuration_id": matcher_id,
        "processing_configuration_id": proc_cfg,
        "tiles": len(tiles),
        "outcomes": {"SUCCESS": len(tiles)},
        "strategies_used": {"sift": len(tiles)},
        "total_candidates": sum(t["candidates"] for t in tiles),
        "per_tile": per_tile,
        "note": "synthetic TEST_FIXTURE for M4 unit validation",
    }
    (match_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (match_dir / "matching_status.json").write_text(
        json.dumps({"matching_state": "COMPLETE", "configuration_id": matcher_id}),
        encoding="utf-8")
    (match_dir / "matching_manifest.json").write_text(
        json.dumps({"configuration_id": matcher_id,
                    "processing_configuration_id": proc_cfg}), encoding="utf-8")


def _build_fake_trust_input(settings, pair_id="CS-P001", tiles=None, match_dir=None):
    if tiles is None:
        tiles = [
            {"match_tile_id": f"{pair_id}-M001", "candidates": 75},
            {"match_tile_id": f"{pair_id}-M002", "candidates": 75},
        ]
    if match_dir is None:
        match_dir = (settings.data_root_path / "derived" / "matches" / pair_id
                     / "PC-M2-001" / "MC-M3-001")
    _fake_m3_tree(match_dir, tiles)
    return match_dir, tiles


def _write_tile(result_path: Path, **kwargs):
    return _fake_tile_npz(result_path, **kwargs)


def _engine_result(tmp_path: Path, name="tile", **kwargs):
    from backend.app.trust.config import TG_M4_001
    from backend.app.trust.engine import evaluate_tile

    npz = tmp_path / f"{name}.npz"
    _fake_tile_npz(npz, **kwargs)
    return evaluate_tile(npz, TG_M4_001, tile_id=name)


# ---------------------------------------------------------------------------
# 1. configuration registration
# ---------------------------------------------------------------------------

def test_m4_configuration_registered_and_inspectable():
    from backend.app.config import m4_config

    cfg = m4_config()
    assert cfg["trust_configuration_id"] == "TG-M4-001"
    d = cfg["defaults"]
    assert d["candidate_integrity"]["min_usable_candidates"] == 8
    assert d["geometric_model"]["type"] == "homography"
    assert d["geometric_model"]["ransac"]["seed"] == 42
    assert d["geometric_model"]["ransac"]["max_iterations"] == 2000
    assert d["acceptance"]["min_inliers"] == 8
    assert d["acceptance"]["min_inlier_ratio"] == 0.3
    assert d["acceptance"]["max_residual_mean"] == 10.0
    assert d["spatial"]["grid_cells"] == 4
    assert d["spatial"]["min_occupied_cells"] == 4
    assert d["spatial"]["max_concentration_ratio"] == 0.6
    assert float(d["degeneracy"]["max_condition_number"]) == pytest.approx(1e6)
    assert d["cross_check"]["enabled"] is True
    assert d["cross_check"]["max_symmetric_transfer_px"] == 8.0
    assert d["execution"]["max_runtime_seconds"] == 60


def test_trust_config_loader_from_defaults():
    from backend.app.config import m4_config
    from backend.app.trust.config import TrustConfig

    cfg = TrustConfig.from_dict(m4_config()["defaults"])
    assert cfg.trust_configuration_id == "TG-M4-001"
    assert cfg.execution.max_runtime_seconds == 60
    assert cfg.acceptance.min_inlier_ratio == 0.3
    assert cfg.geometric_model.ransac.seed == 42
    with pytest.raises((TypeError, AttributeError)):
        TrustConfig.from_dict("not-a-dict")


def test_trust_configurations_endpoint(settings_factory):
    client, _s, _t = _m4_harness(settings_factory)
    with client:
        body = client.get("/api/trust/configurations").json()
        assert body["default_trust_configuration_id"] == "TG-M4-001"
        conf = body["configurations"][0]
        assert conf["trust_configuration_id"] == "TG-M4-001"
        assert conf["defaults"]["geometric_model"]["type"] == "homography"
        assert body["valid_trust_configuration_ids"] == ["TG-M4-001"]
        assert "no scientifically tuned thresholds" in body["note"]


# ---------------------------------------------------------------------------
# 2. geometry layer (RANSAC / DLT / affine / degeneracy)
# ---------------------------------------------------------------------------

def _columns(rng, n, spread=(640.0, 380.0), off=(40.0, 60.0), tx=7.5, ty=-4.0, noise=0.5):
    xa = rng.uniform(off[0], spread[0], n)
    ya = rng.uniform(off[1], spread[1], n)
    xb = xa + tx + rng.normal(0, noise, n)
    yb = ya + ty + rng.normal(0, noise, n)
    return xa, ya, xb, yb


def test_geometry_recovers_translation_inliers():
    from backend.app.trust.config import RansacConfig
    from backend.app.trust.geometry import estimate_homography

    rng = np.random.RandomState(1)
    n = 75
    xa, ya, xb, yb = _columns(rng, n)
    xb[:15] += rng.uniform(-220, 220, 15)
    yb[:15] += rng.uniform(-180, 300, 15)
    out = estimate_homography(
        np.column_stack([xa, ya]), np.column_stack([xb, yb]), RansacConfig())
    assert out.matrix is not None
    assert out.inlier_count >= 45
    assert out.inlier_ratio >= 0.6
    t = out.matrix[:2, 2]
    # recovered translation close to truth (homography noise tolerance)
    assert abs(t[0] - 7.5) < 2.5
    assert abs(t[1] + 4.0) < 2.5
    assert out.degeneracy_flags == []


def test_geometry_rejects_random_noise():
    from backend.app.trust.config import RansacConfig
    from backend.app.trust.geometry import estimate_homography

    rng = np.random.RandomState(4)
    n = 60
    out = estimate_homography(
        np.column_stack([rng.uniform(0, 800, n), rng.uniform(0, 600, n)]),
        np.column_stack([rng.uniform(0, 800, n), rng.uniform(0, 600, n)]),
        RansacConfig())
    assert out.matrix is not None or out.inlier_ratio is None
    if out.matrix is not None:
        assert out.inlier_ratio < 0.3


def test_geometry_rejects_degenerate_collinear_points():
    from backend.app.trust.config import RansacConfig
    from backend.app.trust.geometry import estimate_homography

    rng = np.random.RandomState(5)
    n = 50
    x = rng.uniform(0, 500, n)
    y = 0.5 * x + 3.0
    xb = x + 4.0
    yb = 0.5 * xb + 3.0
    out = estimate_homography(
        np.column_stack([x, y]), np.column_stack([xb, yb]), RansacConfig())
    assert out.matrix is None
    assert any("COLLINEAR" in flag for flag in out.degeneracy_flags)


def test_geometry_symmetric_transfer_small_for_consistent_points():
    from backend.app.trust.geometry import compute_symmetric_transfer

    rng = np.random.RandomState(6)
    n = 30
    a = rng.uniform(0, 600, (n, 2))
    b = a + np.array([10.0, -3.0]) + rng.normal(0, 0.01, (n, 2))
    sym = compute_symmetric_transfer(a, b, np.array([[1.0, 0.0, 10.0],
                                                     [0.0, 1.0, -3.0],
                                                     [0.0, 0.0, 1.0]]))
    assert np.max(sym) < 0.5


def test_affine_least_squares_recovers_scale():
    from backend.app.trust.config import RansacConfig
    from backend.app.trust.geometry import estimate_affine

    rng = np.random.RandomState(7)
    n = 40
    xa = rng.uniform(0, 300, n)
    ya = rng.uniform(0, 300, n)
    xb = 0.5 * xa - 0.1 * ya + 12
    yb = 0.1 * xa + 0.5 * ya - 7
    out = estimate_affine(
        np.column_stack([xa, ya]), np.column_stack([xb, yb]), RansacConfig())
    assert out.matrix is not None
    assert abs(out.matrix[0, 0] - 0.5) < 0.1


def test_geometry_is_deterministic_with_seed():
    from backend.app.trust.config import RansacConfig
    from backend.app.trust.geometry import estimate_homography

    rng = np.random.RandomState(9)
    n = 75
    xa, ya, xb, yb = _columns(rng, n)
    pts_a = np.column_stack([xa, ya])
    pts_b = np.column_stack([xb, yb])
    a = estimate_homography(pts_a, pts_b, RansacConfig())
    b = estimate_homography(pts_a, pts_b, RansacConfig())
    assert a.inlier_count == b.inlier_count
    assert a.iterations_used == b.iterations_used


# ---------------------------------------------------------------------------
# 3. spatial support diagnostics
# ---------------------------------------------------------------------------

def test_spatial_diagnostics_partition_and_occupancy():
    from backend.app.trust.spatial import compute_spatial_diagnostics

    rng = np.random.RandomState(10)
    n = 40
    pts = np.column_stack([rng.uniform(0, 800, n), rng.uniform(0, 600, n)])
    diag = compute_spatial_diagnostics(pts, pts, np.ones(n, dtype=bool), grid_cells=4)
    assert diag.grid_cells_occupied >= 4
    assert diag.total_cells == 16
    assert 0.0 <= diag.concentration_ratio <= 1.0


def test_spatial_diagnostics_cluster_fails_support():
    from backend.app.trust.spatial import compute_spatial_diagnostics

    rng = np.random.RandomState(11)
    n = 60
    n_c = int(n * 0.7)
    n_s = n - n_c
    # 70% clustered at (480,260), 30% spread across the image
    xc = np.full(n_c, 480.0) + rng.uniform(-0.1, 0.1, n_c)
    yc = np.full(n_c, 260.0) + rng.uniform(-0.1, 0.1, n_c)
    xs = rng.uniform(40.0, 640.0, n_s)
    ys = rng.uniform(60.0, 380.0, n_s)
    pts_a = np.column_stack([np.concatenate([xc, xs]), np.concatenate([yc, ys])])
    pts_b = pts_a + rng.uniform(-0.1, 0.1, (n, 2))
    diag = compute_spatial_diagnostics(pts_a, pts_b, np.ones(n, dtype=bool), grid_cells=4)
    # >60% of inlier points in one grid cell → must fail concentration threshold
    assert diag.concentration_ratio >= 0.6
    assert diag.grid_cells_occupied < 16


def test_spatial_diagnostics_zero_inliers_safe():
    from backend.app.trust.spatial import compute_spatial_diagnostics

    pts = np.zeros((10, 2))
    diag = compute_spatial_diagnostics(pts, pts, np.zeros(10, dtype=bool), grid_cells=4)
    assert diag.grid_cells_occupied == 0
    assert np.isfinite(diag.concentration_ratio)


# ---------------------------------------------------------------------------
# 4. per-tile engine decisions
# ---------------------------------------------------------------------------

def test_engine_trusts_well_conditioned_tile(tmp_path):
    r = _engine_result(tmp_path, n=75)
    assert r.trust_state.value == "TRUSTED"
    assert r.model_result is not None and r.model_result.matrix is not None
    assert r.model_result.inlier_count >= 45
    assert r.model_result.inlier_ratio >= 0.6
    assert r.spatial_diagnostics is not None
    assert r.spatial_diagnostics.grid_cells_occupied >= 4
    assert all(rc.startswith("TG_PASS") for rc in r.reasons)


def test_engine_rejects_noise_tile(tmp_path):
    r = _engine_result(tmp_path, n=60, noise=60.0, outliers=0)
    assert r.trust_state.value == "REJECTED"
    assert any("INLIER" in rc for rc in r.reasons)


def test_engine_insufficient_few_points(tmp_path):
    r = _engine_result(tmp_path, n=3)
    assert r.trust_state.value == "INSUFFICIENT"
    assert any("USABLE" in rc for rc in r.reasons)


def test_engine_insufficient_nonfinite_points(tmp_path):
    from backend.app.trust.config import TG_M4_001
    from backend.app.trust.engine import evaluate_tile

    npz = tmp_path / "nan.npz"
    n = 30
    np.savez(npz, x_a=np.full(n, np.nan), y_a=np.full(n, np.nan),
             x_b=np.full(n, np.nan), y_b=np.full(n, np.nan),
             descriptor_distance=np.ones(n), matcher_score=np.ones(n))
    r = evaluate_tile(npz, TG_M4_001, tile_id="nan")
    assert r.trust_state.value == "INSUFFICIENT"
    assert any("USABLE" in rc for rc in r.reasons)


def test_engine_rejects_collinear_only_points(tmp_path):
    r = _engine_result(tmp_path, n=50, collinear=True)
    assert r.trust_state.value in ("REJECTED", "INSUFFICIENT")
    assert (r.model_result is None or r.model_result.matrix is None)


def test_engine_rejects_clustered_points_via_spatial_support(tmp_path):
    r = _engine_result(tmp_path, n=60, clustered=True)
    assert r.trust_state.value == "REJECTED"
    assert any("SPATIAL" in rc for rc in r.reasons)


def test_engine_enforces_symmetric_transfer_cross_check(tmp_path):
    from backend.app.trust.config import TG_M4_001
    from backend.app.trust.engine import evaluate_tile

    npz = tmp_path / "cc.npz"
    _fake_tile_npz(npz, n=75)
    cfg = dataclasses.replace(
        TG_M4_001,
        cross_check=dataclasses.replace(TG_M4_001.cross_check,
                                        enabled=True, max_symmetric_transfer_px=0.0))
    r = evaluate_tile(npz, cfg, tile_id="cc")
    assert r.trust_state.value == "REJECTED"
    assert any("CROSS_CHECK" in rc for rc in r.reasons)


def test_engine_enforces_residual_policy(tmp_path):
    from backend.app.trust.config import TG_M4_001
    from backend.app.trust.engine import evaluate_tile

    npz = tmp_path / "resid.npz"
    _fake_tile_npz(npz, n=75)
    cfg = dataclasses.replace(
        TG_M4_001,
        acceptance=dataclasses.replace(TG_M4_001.acceptance,
                                       max_residual_mean=0.0,
                                       max_residual_median=0.0,
                                       max_residual_p95=0.0))
    r = evaluate_tile(npz, cfg, tile_id="resid")
    assert r.trust_state.value == "REJECTED"
    assert any("RESIDUAL" in rc for rc in r.reasons)


def test_engine_is_deterministic(tmp_path):
    a = _engine_result(tmp_path, n=75)
    b = _engine_result(tmp_path, n=75)
    assert a.trust_state.value == b.trust_state.value
    assert a.model_result.inlier_count == b.model_result.inlier_count
    assert a.reasons == b.reasons


# ---------------------------------------------------------------------------
# 5. service + full trust lifecycle through a real M3 run
# ---------------------------------------------------------------------------

def test_trust_overview_honest_zero_and_meta(settings_factory):
    client, _s, _t = _m4_harness(settings_factory)
    with client:
        meta = client.get("/api/meta").json()
        assert meta["milestone"] == "M5"
        assert meta["m4_config"]["trust_configuration_id"] == "TG-M4-001"
        body = client.get("/api/trust/overview").json()
        assert body["total_trust_pairs"] == 0
        assert body["trusted_pairs"] == 0
        assert body["blocked_pairs"] == 0
        assert "blocked" not in body  # M4 overview uses blocked_pairs, not blocked=True


def test_trust_blocks_honestly_when_matching_not_run(settings_factory):
    client, _s, _t = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        st = client.get(f"/api/trust/{pair_id}/status").json()
        assert st["gate_state"] == "NOT_STARTED"
        resp = client.post(f"/api/trust/{pair_id}/run",
                           json={"trust_configuration_id": "TG-M4-001"})
        assert resp.status_code == 200
        status = resp.json()
        assert status["gate_state"] == "BLOCKED"
        assert status["block_code"] == "MATCHING_NOT_AVAILABLE"


def test_full_trust_run_after_real_matching(settings_factory):
    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)

        st = client.get(f"/api/trust/{pair_id}/status").json()
        assert st["gate_state"] == "NOT_STARTED"
        assert st["block_code"] is None

        resp = client.post(f"/api/trust/{pair_id}/run",
                           json={"trust_configuration_id": "TG-M4-001"})
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["gate_state"] == "COMPLETE"

        run = (settings.data_root_path / "derived" / "trust" / pair_id
               / "PC-M2-001" / "MC-M3-001" / "TG-M4-001")
        assert (run / "trust_status.json").is_file()
        assert (run / "summary.json").is_file()
        assert (run / "tile_trust.json").is_file()

        s = client.get(f"/api/trust/{pair_id}/summary").json()["summary"]
        assert s["gate_state"] == "COMPLETE"
        assert s["trusted_tiles"] >= 1
        assert s["tiles_processed"] == len(client.get(f"/api/trust/{pair_id}/tiles").json()["tiles"])

        tiles = client.get(f"/api/trust/{pair_id}/tiles").json()["tiles"]
        assert tiles
        assert any(t["trust_state"] == "TRUSTED" for t in tiles)
        some_trusted = next(t for t in tiles if t["trust_state"] == "TRUSTED")
        assert some_trusted["model"]["inlier_count"] >= 8
        assert some_trusted["reasons"][0].startswith("TG_PASS")

        man = client.get(f"/api/trust/{pair_id}/manifest").json()["manifest"]
        assert man["trust_configuration_id"] == "TG-M4-001"
        assert man["processing_configuration_id"] == "PC-M2-001"
        assert man["matcher_configuration_id"] == "MC-M3-001"

        overview = client.get("/api/trust/overview").json()
        assert overview["total_trust_pairs"] == 1
        assert overview["trusted_pairs"] == 1


def test_fake_scene_service_run_and_reset_isolation(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)

        svc = TrustService(settings.data_root_path)
        st = svc.run(pair_id, "TG-M4-001")
        assert st["gate_state"] == "COMPLETE"
        summary = svc.summary(pair_id)
        assert summary["trusted_tiles"] == 2

        run = (settings.data_root_path / "derived" / "trust" / pair_id
               / "PC-M2-001" / "MC-M3-001" / "TG-M4-001")
        with np.load(run / "trusted_correspondences.npz") as z:
            assert len(z["x_a"]) == len(z["y_a"]) == len(z["x_b"]) == len(z["y_b"])
            assert len(z["x_a"]) >= 90  # 2 tiles x >=45 inliers

        r = svc.reset(pair_id)
        assert r["gate_state"] == "NOT_STARTED"
        assert not (settings.data_root_path / "derived" / "trust" / pair_id).exists()
        assert (settings.data_root_path / "derived" / "matches" / pair_id).exists()
        assert (settings.data_root_path / "raw").exists()
        assert (settings.data_root_path / "derived" / "processing" / pair_id).exists()


def test_service_blocks_on_unregistered_pair(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        svc = TrustService(settings.data_root_path)
        st = svc.run("CS-P999", "TG-M4-001")
        assert st["gate_state"] == "BLOCKED"
        assert st["block_code"] == "MATCHING_NOT_AVAILABLE"


def test_service_blocks_on_unknown_trust_config(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)
        svc = TrustService(settings.data_root_path)
        st = svc.run(pair_id, "TG-X-999")
        assert st["gate_state"] == "BLOCKED"
        assert st["block_code"] == "TRUST_UNKNOWN_CONFIG"


def test_trust_manifest_has_no_absolute_paths_or_fake_claims(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)
        svc = TrustService(settings.data_root_path)
        svc.run(pair_id, "TG-M4-001")
        run = (settings.data_root_path / "derived" / "trust" / pair_id
               / "PC-M2-001" / "MC-M3-001" / "TG-M4-001")
        manifest = json.loads((run / "trust_manifest.json").read_text(encoding="utf-8"))
        text = json.dumps(manifest)
        assert "C:\\\\" not in text and ":///" not in text
        assert str(settings.data_root_path) not in text
        assert manifest["trust_configuration_id"] == "TG-M4-001"
        assert manifest["processing_summary"]["trusted_tiles"] == 2
        summary_text = (run / "summary.json").read_text(encoding="utf-8")
        assert '"confidence"' not in summary_text
        status_text = (run / "trust_status.json").read_text(encoding="utf-8")
        assert '"confidence"' not in status_text


# ---------------------------------------------------------------------------
# 6. failure + edge cases
# ---------------------------------------------------------------------------

def test_trust_unknown_pair_and_config_404(settings_factory):
    client, _s, _t = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        r404 = client.get("/api/trust/CS-P999/status")
        assert r404.status_code == 404
        assert r404.json()["error"]["code"] == "NOT_FOUND"
        r404b = client.post(f"/api/trust/{pair_id}/run",
                            json={"trust_configuration_id": "TG-X-999"})
        assert r404b.status_code == 404
        assert r404b.json()["error"]["code"] == "NOT_FOUND"


def test_trust_gate_fails_when_all_tiles_rejected(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        match_dir = (settings.data_root_path / "derived" / "matches" / pair_id
                     / "PC-M2-001" / "MC-M3-001")
        _fake_m3_tree(match_dir, [
            {"match_tile_id": f"{pair_id}-M001", "candidates": 60},
            {"match_tile_id": f"{pair_id}-M002", "candidates": 60},
        ])
        # overwrite to pure noise so no inlier majority can form
        for tid in (f"{pair_id}-M001", f"{pair_id}-M002"):
            _fake_tile_npz(match_dir / "candidates" / f"{tid}.npz",
                           n=60, noise=60.0, outliers=0, tx=300.0, ty=200.0)
        svc = TrustService(settings.data_root_path)
        st = svc.run(pair_id, "TG-M4-001")
        assert st["gate_state"] == "FAILED"
        assert svc.summary(pair_id)["trusted_tiles"] == 0


def test_trust_reset_only_removes_trust_artifacts_api(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)
        TrustService(settings.data_root_path).run(pair_id, "TG-M4-001")
        r = client.post(f"/api/trust/{pair_id}/reset").json()
        assert r["reset"] is True
        assert r["status"]["gate_state"] == "NOT_STARTED"
        assert not (settings.data_root_path / "derived" / "trust" / pair_id).exists()
        assert (settings.data_root_path / "derived" / "matches" / pair_id).exists()
        assert (settings.data_root_path / "raw").exists()


def test_trust_tile_path_traversal_safe(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)
        svc = TrustService(settings.data_root_path)
        svc.run(pair_id, "TG-M4-001")
        assert "error" in svc.tile_trust(pair_id, "..")
        assert "error" in svc.tile_trust(pair_id, "CS-P001-M001/../../trust_status")


def test_runtime_timeout_marks_all_tiles_failed(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)
        svc = TrustService(settings.data_root_path,
                           m4_cfg={"defaults": {"execution": {"max_runtime_seconds": 0.0}}})
        st = svc.run(pair_id, "TG-M4-001")
        assert st["gate_state"] == "FAILED"
        run = svc.find_run_for_pair(pair_id)
        index = json.loads((run / "tile_trust.json").read_text(encoding="utf-8"))
        assert all(t["block_code"] == "TIMEOUT" for t in index["tiles"])
        assert all(t["trust_state"] == "FAILED" for t in index["tiles"])


def test_trust_run_is_deterministic_across_two_runs(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m4_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _build_fake_trust_input(settings, pair_id=pair_id)
        svc = TrustService(settings.data_root_path)
        svc.run(pair_id, "TG-M4-001")
        first = svc.tile_trust(pair_id, f"{pair_id}-M001")
        svc.reset(pair_id)
        svc.run(pair_id, "TG-M4-001")
        second = svc.tile_trust(pair_id, f"{pair_id}-M001")
        assert first["trust_state"] == second["trust_state"]
        assert first["model"]["inlier_count"] == second["model"]["inlier_count"]
        assert first["reasons"] == second["reasons"]