"""M2 tests — trustworthy preprocessing & lunar scene conditioning.

Software-validation fixtures only. TEST_FIXTURE geometry explicitly labelled
synthetic exercises the full PREPARE path; the no-geometry path proves that
REAL data (no documented ground geometry) blocks honestly.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fixturegen  # noqa: F401


def _harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m2_"))
    fixturegen.write_standard_fixtures(tmp)
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


FIXTURE_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic uniform ground frame injected for software validation only — NOT real orbital geometry.",
    "products": {
        "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 1.0},
        "tmc2": {"row_offset_m": 80.0, "col_offset_m": 60.0, "gsd_m": 1.0},
    },
}


# --------------------------------------------------------------------------
# 1. configuration registration
# --------------------------------------------------------------------------

def test_m2_configuration_registered_and_inspectable():
    from backend.app.config import m2_config

    cfg = m2_config()
    assert cfg["configuration_id"] == "PC-M2-001"
    assert cfg["defaults"]["crops"]["size_px"] == 512
    assert "condition" in cfg["defaults"]
    assert isinstance(cfg["defaults"]["matcher_readiness"]["required"], list)


def test_processing_config_loader_and_rejection():
    from backend.app.processing.config import load_processing_config

    cfg = load_processing_config()
    assert cfg.configuration_id == "PC-M2-001"
    assert cfg.crop_size_px == 512
    assert cfg.min_overlap_px == 64
    with pytest.raises(ValueError):
        load_processing_config("PC-M9-999")


def test_configurations_endpoint(settings_factory):
    client, _s, _t = _harness(settings_factory)
    with client:
        body = client.get("/api/processing/configurations").json()
        assert body["default_configuration_id"] == "PC-M2-001"
        assert body["configurations"][0]["configuration_id"] == "PC-M2-001"
        assert "radiometric" in body["configurations"][0]["display_only"]


# --------------------------------------------------------------------------
# 2. happy path: full PREPARE on TEST_FIXTURE geometry
# --------------------------------------------------------------------------

def test_full_prepare_ready_for_matching(settings_factory):
    client, settings, _tmp = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        resp = client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": FIXTURE_GEOMETRY})
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["state"] == "READY_FOR_MATCHING"
        assert status["geometry_source"] == "TEST_FIXTURE"
        assert status["matcher_readiness"]["ready"] is True
        assert status["matcher_readiness"]["level"] in ("READY", "CONDITIONAL")
        required = {r["id"] for r in status["matcher_readiness"]["requirements"]}
        assert {"raw_integrity_ok", "preprocess_ok", "overlap_valid", "tiles_generated", "tiles_usable", "condition_evaluated"}.issubset(required)
        assert status["tiles"]["count"] >= 2
        assert all(v > 0 for v in status["tiles"]["usable"].values())

        # derived layout under derived/processing/<pair>/<config>/
        run = settings.data_root_path / "derived" / "processing" / pair_id / "PC-M2-001"
        assert (run / "processing_status.json").is_file()
        assert (run / "processing_manifest.json").is_file()
        assert (run / "ohrc" / "preprocessed_display_u16.npy").is_file()
        assert (run / "ohrc" / "invalid_mask_u8.npy").is_file()
        assert (run / "tmc2" / "preprocessed_display_u16.npy").is_file()
        assert (run / "diagnostics" / "overlap.json").is_file()
        assert (run / "diagnostics" / "conditions.json").is_file()
        assert (run / "crops" / "tiles.json").is_file()


def test_full_prepare_keeps_raw_bytes_identical(settings_factory):
    import hashlib

    client, settings, tmp = _harness(settings_factory)
    a = tmp / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    b = tmp / "raw" / "tmc2" / "ch2_tmc_ncn_20200207T0716469418_d_img_d18.img"
    dig_a = hashlib.sha256(a.read_bytes()).hexdigest()
    dig_b = hashlib.sha256(b.read_bytes()).hexdigest()
    with client:
        pair_id = _register(client)
        client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": FIXTURE_GEOMETRY})
    assert hashlib.sha256(a.read_bytes()).hexdigest() == dig_a
    assert hashlib.sha256(b.read_bytes()).hexdigest() == dig_b


def test_manifest_provenance_relative_paths_and_hashes(settings_factory):
    client, settings, _tmp = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": FIXTURE_GEOMETRY})
        body = client.get(f"/api/processing/{pair_id}/manifest").json()
        manifest = body["manifest"]
        assert manifest["configuration"]["configuration_id"] == "PC-M2-001"
        assert len(manifest["products"]) == 2
        assert all(p["raw_sha256"] for p in manifest["products"])
        assert manifest["overlap"]["status"] == "CONFIRMED_OVERLAP"
        assert manifest["geometry"]["source"] == "TEST_FIXTURE"
        steps = manifest["steps"]
        assert {s["id"] for s in steps} >= {"reading", "preprocessing", "preparing_overlap", "generating_crops", "analyzing_condition"}
        text = json.dumps(manifest)
        assert str(settings.data_root_path).replace("\\", "/") not in text
        for step in steps:
            for out in step.get("outputs", []):
                assert out["sha256"], "every derived artifact must be hashed in the manifest"
                assert not Path(out["rel_path"]).is_absolute()


def test_tiles_and_conditions_endpoints(settings_factory):
    client, _settings, _tmp = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": FIXTURE_GEOMETRY})
        tiles = client.get(f"/api/processing/{pair_id}/tiles").json()["tiles"]
        assert tiles["count"] >= 2
        ids = [t["tile_id"] for t in tiles["tiles"]]
        first = ids[0]
        assert first.startswith(pair_id + "-T")
        det = client.get(f"/api/processing/{pair_id}/tiles/{first}").json()["tile"]
        assert det["tile_id"] == first
        assert "preview_url" in det

        cond = client.get(f"/api/processing/{pair_id}/conditions").json()["conditions"]
        assert cond["summary"]["tiles"] == tiles["count"]
        assert cond["summary"]["assessed"] == tiles["count"]
        for t in cond["tiles"]:
            ind = t["indicators"]
            assert {"valid_coverage", "illumination_range", "brightness_mean", "texture", "saturation"} == set(ind)
            assert all(set(i) == {"value", "status", "quality", "reason"} for i in ind.values())

        preview = client.get(f"/api/processing/{pair_id}/tiles/{first}/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"].startswith("image/png")


def test_reset_removes_derived_only(settings_factory):
    client, settings, tmp = _harness(settings_factory)
    a = tmp / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    with client:
        pair_id = _register(client)
        client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": FIXTURE_GEOMETRY})
        run = settings.data_root_path / "derived" / "processing" / pair_id
        assert run.is_dir()
        resp = client.post(f"/api/processing/{pair_id}/reset")
        assert resp.status_code == 200
        assert not run.exists()
        assert a.is_file(), "raw must never be removed"


# --------------------------------------------------------------------------
# 3. honest blocking paths
# --------------------------------------------------------------------------

def test_real_pair_without_geometry_blocks_no_geometry(settings_factory):
    client, settings, _tmp = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        resp = client.post(f"/api/processing/{pair_id}/prepare", json={})
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["state"] == "BLOCKED"
        assert status["blocked"]["code"] == "NO_GEOMETRY"
        assert status["blocked"]["stage"] == "preparing_overlap"
        assert status["error"] is None
        assert status["matcher_readiness"] is None
        # preprocessing still happened before the honest block
        run = settings.data_root_path / "derived" / "processing" / pair_id / "PC-M2-001"
        assert (run / "ohrc" / "preprocessed_display_u16.npy").is_file()
        assert client.get(f"/api/processing/{pair_id}/tiles").status_code == 404
        assert client.get(f"/api/processing/{pair_id}/conditions").status_code == 404
        assert client.get(f"/api/processing/{pair_id}/manifest").status_code == 200  # partial manifest traces the block


def test_no_overlap_geometry_blocks(settings_factory):
    client, _s, _t = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        far = {
            "source": "TEST_FIXTURE",
            "reference": "Non-overlapping synthetic footprints.",
            "products": {
                "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 1.0},
                "tmc2": {"row_offset_m": 20000.0, "col_offset_m": 20000.0, "gsd_m": 1.0},
            },
        }
        status = client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": far}).json()
        assert status["state"] == "BLOCKED"
        assert status["blocked"]["code"] == "NO_OVERLAP"


def test_pair_not_valid_blocks(settings_factory):
    from pathlib import Path

    client, _settings, tmp = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        img_b = tmp / "raw" / "tmc2" / "ch2_tmc_ncn_20200207T0716469418_d_img_d18.img"
        data = img_b.read_bytes()
        img_b.write_bytes(data[: len(data) // 2])  # truncate -> smaller than label geometry
        status = client.post(f"/api/processing/{pair_id}/prepare", json={}).json()
        assert status["state"] == "BLOCKED"
        assert status["blocked"]["code"] == "PAIR_NOT_VALID"


def test_unknown_configuration_and_pair_errors(settings_factory):
    client, _s, _t = _harness(settings_factory)
    with client:
        pair_id = _register(client)
        r = client.post(f"/api/processing/{pair_id}/prepare", json={"configuration_id": "PC-M9-999"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"

        for path in (
            f"/api/processing/CS-P999/status",
            f"/api/processing/CS-P999/manifest",
            f"/api/processing/CS-P999/conditions",
            f"/api/processing/CS-P999/tiles",
        ):
            assert client.get(path).status_code == 404, path
        assert client.post("/api/processing/CS-P999/prepare", json={}).status_code == 404
        assert client.post("/api/processing/CS-P999/reset").status_code == 404


# --------------------------------------------------------------------------
# 4. data-level units: masking, normalization, conditions
# --------------------------------------------------------------------------

def test_mask_builds_explicit_bitflags():
    from backend.app.processing.masking import build_invalid_mask, flag_names

    arr = np.array([[1.0, np.nan], [65535.0, -3.0]])
    mask, stats = build_invalid_mask(arr, {"nan_inf": True, "saturated": True, "saturation_dn": 65535, "negative": True})
    assert mask[0, 0] == 0                       # valid
    assert mask[0, 1] & 1                        # NAN_INF
    assert mask[1, 0] & 2                        # SATURATED
    assert mask[1, 1] & 4                        # NEGATIVE
    assert stats["valid"] == 1 and stats["invalid"] == 3
    assert flag_names(3) == ["NAN_INF", "SATURATED"]


def test_display_normalize_masks_and_window():
    from backend.app.processing.normalize import display_normalize

    arr = np.array([[0, 100, 200], [1000, 5000, 20000]], dtype=np.uint16)
    mask = np.zeros(arr.shape, dtype=np.uint8)
    mask[0, 0] = 1
    out, stats = display_normalize(arr, mask, 1.0, 99.0)
    assert out.dtype == np.uint16
    assert out[0, 0] == 0  # masked -> 0
    assert out[1, 2] == 65535  # max lands at 65535
    assert stats["note"] and "radimetric" not in stats["note"]


def test_conditions_deterministic_and_blocking():
    from backend.app.processing.conditions import analyze_tile
    from backend.app.processing.config import load_processing_config

    cfg = load_processing_config()
    mask = np.zeros((16, 16), dtype=np.uint8)

    flat = np.full((16, 16), 4000, dtype=np.uint16)
    r_flat = analyze_tile(flat, mask, tile_id="T", sensor="ohrc", cfg=cfg)
    assert r_flat["classification"]["level"] == "LOW_TEXTURE"
    assert analyze_tile(flat, mask, tile_id="T", sensor="ohrc", cfg=cfg) == r_flat  # deterministic

    noisy = (np.arange(256, dtype=np.uint16).reshape(16, 16) * 250)
    r_noisy = analyze_tile(noisy, mask, tile_id="T", sensor="ohrc", cfg=cfg)
    assert r_noisy["classification"]["level"] == "HIGH_TEXTURE"

    empty_mask = np.ones((16, 16), dtype=np.uint8)
    r_empty = analyze_tile(flat, empty_mask, tile_id="T", sensor="ohrc", cfg=cfg)
    assert r_empty["classification"]["level"] == "UNKNOWN"
    assert r_empty["indicators"]["texture"]["quality"] == "N/A"


def test_overlap_pixel_slicing_matches_ground_frame():
    from backend.app.processing.geometry import FootprintBox
    from backend.app.processing.overlap import compute_overlap
    from backend.app.processing.geometry import GeometryPlan, ProductGeom, GEOMETRY_SOURCE_FIXTURE

    plan = GeometryPlan(
        source=GEOMETRY_SOURCE_FIXTURE,
        reference="test",
        products={
            "ohrc": ProductGeom("ohrc", 200, 256, 1.0, 0.0, 0.0, "TEST_FIXTURE_OVERRIDE"),
            "tmc2": ProductGeom("tmc2", 300, 384, 1.0, 80.0, 60.0, "TEST_FIXTURE_OVERRIDE"),
        },
    )
    overlap = compute_overlap(plan, "ohrc", "tmc2")
    assert overlap.status == "CONFIRMED_OVERLAP"
    env = overlap.envelope
    assert env.width_m == 196.0 and env.height_m == 120.0
    assert overlap.regions["ohrc"].width_px == 196
    assert overlap.regions["tmc2"].width_px == 196


# --------------------------------------------------------------------------
# 5. overview + route wiring
# --------------------------------------------------------------------------

def test_overview_honest_zero_no_pairs(settings_factory):
    client, _settings, _tmp = _harness(settings_factory)
    with client:
        body = client.get("/api/processing/overview").json()
        assert body["pairs"] == []
        assert body["blocked"] is True
        assert "BLOCKED" in body["reason"]


def test_processing_routes_declared_under_api():
    from backend.app.main import create_app

    application = create_app()
    expected = {
        "list_configurations": "/api/processing/configurations",
        "overview": "/api/processing/overview",
    }
    for name, path in expected.items():
        assert application.url_path_for(name) == path
    pair_routes = {
        "pair_status": "/api/processing/P001/status",
        "run_prepare": "/api/processing/P001/prepare",
        "reset_pair": "/api/processing/P001/reset",
        "pair_manifest": "/api/processing/P001/manifest",
        "pair_conditions": "/api/processing/P001/conditions",
        "pair_tiles": "/api/processing/P001/tiles",
    }
    for name, path in pair_routes.items():
        assert application.url_path_for(name, pair_id="P001") == path