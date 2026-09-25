"""M3 real-data tests — classical baseline matching (SIFT · AKAZE · ORB).

The M3 baseline milestone implements a SECOND, explicit matcher contract on
top of the adaptive engine: three classical matchers sharing one candidate
correspondence contract with per-run configuration snapshots, deterministic
reruns, persisted artifacts, honest blocked outcomes (AKAZE is registered but
truthfully reports NOT_AVAILABLE on OpenCV builds without it; un-prepared or
broken input blocks instead of fabricating), and an honest data-gate that
reports REAL_DATA_BLOCKED whenever genuine PRADAN products are absent.

Nothing here claims an accuracy or trust verdict. All fixture data is
synthetic and labelled TEST_FIXTURE; a real-shaped pair is included only to
prove that the shared gates apply to every pair class the same way.
"""

from __future__ import annotations

import copy
import json
import tempfile
import subprocess
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

import fixturegen  # noqa: F401

from auth_helpers import authed_client_for_app, configure_auth

CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M3 baseline software validation only.",
    "products": {
        "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 0.5},
        "tmc2": {"row_offset_m": -2.0, "col_offset_m": -2.0, "gsd_m": 0.5},
    },
}


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _m3b_harness():
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m3b_"))
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
    assert val.status_code == 200, val.text
    assert val.json()["status"] == "VALID"
    return pair_id


def _prepare(client, pair_id):
    resp = client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": CORRELATED_GEOMETRY})
    assert resp.status_code == 200, resp.text
    status = resp.json()
    assert status["state"] == "READY_FOR_MATCHING", status
    assert status["matcher_readiness"]["ready"] is True, status
    return status


def _shifted_images():
    """img_a / img_b are the same scene with a -8 column shift (b is base[:, 8:])."""
    base = fixturegen._synthetic_scene_rows(size=96, cols=160, seed=3)
    img_a = (np.clip(base[:, :-8], 0, 1) * 255).astype(np.uint8)
    img_b = (np.clip(base[:, 8:], 0, 1) * 255).astype(np.uint8)
    return img_a, img_b


def _cfg(matcher: str = "sift", **matching) -> dict:
    from backend.app.config import m3_baseline_config

    cfg = copy.deepcopy(m3_baseline_config())
    cfg["defaults"][matcher]["matching"].update(matching)
    return cfg


def _run(matcher: str, img_a, img_b, **matching):
    from backend.app.matching.baseline import MatcherInput, run_baseline_contract

    cfg = _cfg(matcher, **matching) if matching else None
    inp = MatcherInput(matcher_id=matcher, image_a=img_a, image_b=img_b)
    return run_baseline_contract(inp, cfg=cfg)


def _stable(out) -> dict:
    """asdict minus wall-clock runtime (determinism is about outputs, not timing)."""
    d = asdict(out)
    d.pop("runtime_ms", None)
    return d


# ---------------------------------------------------------------------------
# 1. interface / contract
# ---------------------------------------------------------------------------

def test_m3b_contract_interface_rejects_nd_non_2d_and_serializes():
    from backend.app.matching.baseline import Correspondence, MatcherInput, MatcherOutput

    with pytest.raises(ValueError):
        MatcherInput(matcher_id="sift",
                     image_a=np.zeros((8, 8, 3), dtype=np.uint8),
                     image_b=np.zeros((8, 8), dtype=np.uint8))
    out = MatcherOutput(
        matcher_id="sift", matcher_name="SIFT", matcher_version="probe",
        status="BLOCKED", keypoint_count_a=0, keypoint_count_b=0,
        raw_match_count=0, candidate_match_count=0,
        correspondences=[asdict(Correspondence(1.0, 2.0, 3.0, 4.0, 0.9, 12.0, 0, 1))],
        error_code="ERR", error_detail="detail",
    )
    text = json.dumps(asdict(out), sort_keys=True)
    assert out.status == "BLOCKED"
    assert out.error_code == "ERR"
    assert '"match_index_a": 0' in text and '"x_b": 3.0' in text


# ---------------------------------------------------------------------------
# 2. SIFT
# ---------------------------------------------------------------------------

def test_m3b_sift_produces_candidate_correspondences():
    a, b = _shifted_images()
    out = _run("sift", a, b)
    assert out.status == "SUCCESS", out.error_detail
    assert out.keypoint_count_a >= 2 and out.keypoint_count_b >= 2
    assert out.candidate_match_count > 0
    assert len(out.correspondences) == out.candidate_match_count
    assert out.raw_match_count >= out.candidate_match_count


def test_m3b_sift_deterministic_rerun_is_identical():
    a, b = _shifted_images()
    o1 = _run("sift", a, b)
    o2 = _run("sift", a, b)
    assert _stable(o1) == _stable(o2)


# ---------------------------------------------------------------------------
# 3. AKAZE (registered; honest availability)
# ---------------------------------------------------------------------------

def test_m3b_akaze_registered_and_truthful_not_available_or_runs():
    from backend.app.matching.baseline import BASELINE_MATCHER_IDS, matcher_available
    from backend.app.matching.baseline import MatcherInput, run_baseline_contract

    assert "akaze" in BASELINE_MATCHER_IDS
    available, reason = matcher_available("akaze")
    a, b = _shifted_images()
    out = run_baseline_contract(MatcherInput(matcher_id="akaze", image_a=a, image_b=b))
    if available:
        assert out.status == "SUCCESS", out.error_detail
        assert out.candidate_match_count > 0
    else:
        assert out.status == "BLOCKED"
        assert out.error_code == "MATCHER_NOT_AVAILABLE"
        assert "AKAZE_create" in out.error_detail
        assert reason and "simulated" in reason.lower() or "not present" in reason.lower()


# ---------------------------------------------------------------------------
# 4. ORB
# ---------------------------------------------------------------------------

def test_m3b_orb_candidates_and_deterministic():
    a, b = _shifted_images()
    o1 = _run("orb", a, b)
    assert o1.status == "SUCCESS", o1.error_detail
    assert o1.candidate_match_count > 0
    o2 = _run("orb", a, b)
    assert _stable(o1) == _stable(o2)


# ---------------------------------------------------------------------------
# 5. schema
# ---------------------------------------------------------------------------

def test_m3b_correspondence_schema_valid():
    a, b = _shifted_images()
    out = _run("sift", a, b)
    needed = {"x_a", "y_a", "x_b", "y_b", "score",
              "descriptor_distance", "match_index_a", "match_index_b"}
    ha, hb = a.shape
    for c in out.correspondences:
        assert needed.issubset(c.keys())
        assert np.isfinite(c["x_a"]) and np.isfinite(c["x_b"])
        assert np.isfinite(c["y_a"]) and np.isfinite(c["y_b"])
        assert 0 <= c["x_a"] < a.shape[1] and 0 <= c["y_a"] < ha
        assert 0 <= c["x_b"] < b.shape[1] and 0 <= c["y_b"] < hb
        assert 0.0 <= c["score"] <= 1.0
        assert isinstance(c["match_index_a"], int)
        assert isinstance(c["match_index_b"], int)
        assert 0 <= c["match_index_a"] < out.keypoint_count_a
        assert 0 <= c["match_index_b"] < out.keypoint_count_b


# ---------------------------------------------------------------------------
# 6. coordinate preservation (A/B meaning verified, not guessed)
# ---------------------------------------------------------------------------

def test_m3b_coordinate_semantics_after_translation():
    a, b = _shifted_images()
    out = _run("sift", a, b)
    assert out.status == "SUCCESS"
    xs = [c["x_a"] - 8 - c["x_b"] for c in out.correspondences]
    ys = [abs(c["y_a"] - c["y_b"]) for c in out.correspondences]
    assert len(xs) == out.candidate_match_count > 0
    assert np.median(xs) < 4.0 and np.median(ys) < 1.5
    assert np.mean([abs(x) < 4.0 for x in xs]) > 0.6


# ---------------------------------------------------------------------------
# 7. distance / score summaries
# ---------------------------------------------------------------------------

def test_m3b_score_and_distance_summaries_valid_and_bounded():
    a, b = _shifted_images()
    out = _run("sift", a, b)
    for key in ("descriptor_distance", "score"):
        summary = out.scores.get(key) or {}
        for stat in ("min", "max", "median", "mean", "p95", "count"):
            assert summary.get(stat) is not None, key
        assert summary["count"] == out.candidate_match_count
    assert out.scores["score"]["max"] <= 1.0
    assert out.scores["score"]["min"] >= 0.0
    assert all(c["descriptor_distance"] <= 350.0 for c in out.correspondences)


# ---------------------------------------------------------------------------
# 8. ratio filter
# ---------------------------------------------------------------------------

def test_m3b_ratio_filter_is_explicit_and_sharpens():
    a, b = _shifted_images()
    loose = _run("sift", a, b, ratio_threshold=0.99, cross_check=False, max_distance=1000.0)
    strict = _run("sift", a, b, ratio_threshold=0.3, cross_check=False, max_distance=1000.0)
    assert loose.status == "SUCCESS" and strict.status == "SUCCESS"
    assert strict.candidate_match_count <= loose.candidate_match_count
    assert loose.filters["ratio_test"]["applied"] and strict.filters["ratio_test"]["applied"]
    assert strict.filters["ratio_test"]["rejected"] >= loose.filters["ratio_test"]["rejected"]
    assert loose.filters["funnel"]["after_ratio"] - strict.filters["funnel"]["after_ratio"] > 0


# ---------------------------------------------------------------------------
# 9. cross-check
# ---------------------------------------------------------------------------

def test_m3b_cross_check_never_increases_candidates():
    a, b = _shifted_images()
    cc = _run("sift", a, b, cross_check=True, ratio_threshold=0.8, max_distance=1000.0)
    noc = _run("sift", a, b, cross_check=False, ratio_threshold=0.8, max_distance=1000.0)
    assert cc.status == "SUCCESS" and noc.status == "SUCCESS"
    assert cc.candidate_match_count <= noc.candidate_match_count
    assert cc.filters["cross_check"]["applied"] is True
    assert noc.filters["cross_check"]["applied"] is False


def test_m3b_cross_check_pairs_are_mutually_nearest():
    """Independent verification (brute-force) that cross-checked pairs are symmetric NN."""
    import cv2

    a, b = _shifted_images()
    out = _run("sift", a, b, cross_check=True, ratio_threshold=0.8, max_distance=1000.0)
    assert out.candidate_match_count > 0
    sift = cv2.SIFT_create()
    da = sift.compute(a, sift.detect(a))[1]
    db = sift.compute(b, sift.detect(b))[1]
    for c in out.correspondences:
        ia, ib = c["match_index_a"], c["match_index_b"]
        fa = np.linalg.norm(da[ia, None, :] - db, axis=1)
        fb = np.linalg.norm(db[ib, None, :] - da, axis=1)
        assert int(np.argmin(fa)) == ib
        assert int(np.argmin(fb)) == ia


# ---------------------------------------------------------------------------
# 10. empty keypoints, low texture, incompatible, tiny input
# ---------------------------------------------------------------------------

def test_m3b_empty_keypoints_blocks_honestly():
    out = _run("sift",
               np.zeros((64, 64), dtype=np.uint8),
               np.zeros((64, 64), dtype=np.uint8))
    assert out.status == "BLOCKED"
    assert out.error_code == "INVALID_INPUT"
    assert "Not enough features" in out.error_detail


def test_m3b_tiny_window_blocks_honestly():
    out = _run("sift", np.ones((4, 4), dtype=np.uint8), np.ones((4, 4), dtype=np.uint8))
    assert out.status == "BLOCKED"
    assert out.error_code == "INVALID_INPUT"
    assert "8x8" in out.error_detail


def test_m3b_low_texture_never_fabricates_candidates():
    rng = np.random.default_rng(7)
    low = np.clip(128 + 2 * rng.normal(size=(128, 128)), 0, 255).astype(np.uint8)
    out = _run("sift", low, low.copy())
    assert out.status in ("SUCCESS", "BLOCKED")
    if out.status == "SUCCESS":
        assert 0 <= out.candidate_match_count <= min(out.keypoint_count_a, out.keypoint_count_b)
        assert out.candidate_match_count < 60
        assert out.filters["funnel"]["candidates"] == out.candidate_match_count


def test_m3b_incompatible_scenes_never_crash_nor_claim():
    rng = np.random.default_rng(11)
    a = (rng.integers(0, 256, size=(112, 128)).astype(np.uint8))
    b = (rng.integers(0, 256, size=(128, 96)).astype(np.uint8))
    out = _run("sift", a, b)
    assert out.status in ("SUCCESS", "BLOCKED", "FAILED")
    text = json.dumps(asdict(out))
    assert "final_confidence" not in text
    for c in out.correspondences:
        assert all(np.isfinite(c[k]) for k in ("x_a", "y_a", "x_b", "y_b", "score", "descriptor_distance"))
        assert 0.0 <= c["score"] <= 1.0
    assert out.candidate_match_count <= out.raw_match_count


# ---------------------------------------------------------------------------
# 11. preprocessing mismatch / missing products
# ---------------------------------------------------------------------------

def test_m3b_preprocessed_products_missing_blocks_product_missing():
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        proc = settings.data_root_path / "derived" / "processing" / pair_id / "PC-M2-001"
        for npy in proc.glob("**/preprocessed_display_u16.npy"):
            npy.unlink()
        resp = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "BLOCKED"
        assert body["error_code"] == "PRODUCT_MISSING"
        art = settings.data_root_path / "metadata" / "m3_matching" / f"{body['run_id']}.json"
        assert art.is_file()


def test_m3b_unprepared_pair_blocks_processing_not_run(settings_factory):
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        resp = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "BLOCKED"
        assert body["error_code"] == "PROCESSING_NOT_RUN"
        st = client.get(f"/api/matching/{pair_id}/baseline/status").json()
        assert st["has_run"] is True
        assert st["latest_run"]["error_code"] == "PROCESSING_NOT_RUN"


# ---------------------------------------------------------------------------
# 12. invalid pair / unknown matcher
# ---------------------------------------------------------------------------

def test_m3b_invalid_pair_and_unknown_matcher_rejected(settings_factory):
    client, _s, _tmp = _m3b_harness()
    with client:
        assert client.get("/api/matching/CS-P999/baseline/status").status_code == 404
        assert client.post("/api/matching/CS-P999/baseline/run", json={"matcher": "sift"}).status_code == 404
        pair_id = _register(client)
        _prepare(client, pair_id)
        r422 = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "bogus"})
        assert r422.status_code == 422
        assert r422.json()["error"]["code"] == "VALIDATION_ERROR"


# ---------------------------------------------------------------------------
# 13. real-data gate (honest machine-readable block)
# ---------------------------------------------------------------------------

def test_m3b_real_data_gate_fixture_only_blocked(settings_factory):
    client, _s, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        st = client.get(f"/api/matching/{pair_id}/baseline/status").json()
        gate = st["data_gate"]
        assert gate["real_data_available"] is False
        assert gate["code"] == "REAL_DATA_BLOCKED"
        caps = client.get("/api/matching/baseline/capabilities").json()
        assert caps["m3_baseline_configuration_id"] == "MB-M3-001"


def test_m3b_real_shaped_pair_shares_the_same_gates():
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m3b_real_"))
    fixturegen.write_real_shaped_pair(tmp)
    settings = Settings(data_root=str(tmp), _env_file=None)
    ensure_derived_directories(settings)
    configure_auth(settings)
    client = authed_client_for_app(create_app(settings=settings))
    with client:
        resp = client.post("/api/pairs/auto-register", json={})
        assert resp.status_code == 200, resp.text
        pair_id = resp.json()["pair_id"]
        val = client.post(f"/api/pairs/{pair_id}/validate")
        assert val.status_code == 200, val.text
        # baseline honors the same gates as any pair class
        run = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"})
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "BLOCKED"
        assert run.json()["error_code"] == "PROCESSING_NOT_RUN"


# ---------------------------------------------------------------------------
# 14. synthetic separation
# ---------------------------------------------------------------------------

def test_m3b_fixture_artifacts_are_labelled_synthetic_not_real(settings_factory):
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"}).json()
        assert body["status"] == "SUCCESS"
        assert body["synthetically_derived"] is True
        assert body["source_gate"]["data_source_gate"] == "PATH_B_SYNTHETIC_ONLY"
        assert body["source_gate"]["source_class_a"] == "TEST_FIXTURE"
        text = json.dumps(body)
        assert '"REAL_PRADAN"' not in text
        assert "scientific accuracy or trust verdict" in body["license"]


# ---------------------------------------------------------------------------
# 15. artifact persistence + provenance
# ---------------------------------------------------------------------------

def test_m3b_artifact_persistence_unique_run_ids_and_provenance(settings_factory):
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        r1 = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"}).json()
        r2 = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "orb"}).json()
        assert r1["run_id"] != r2["run_id"]
        for body in (r1, r2):
            art = settings.data_root_path / "metadata" / "m3_matching" / f"{body['run_id']}.json"
            assert art.is_file()
            stored = json.loads(art.read_text(encoding="utf-8"))
            assert stored["run_id"] == body["run_id"]
            assert stored["configuration_id"] == "MB-M3-001"
            assert stored["configuration"]["matching"]["cross_check"] is True
            assert stored["environment"]["opencv_version"]
            assert stored["input"]["image_a"]["original_dimensions"]["height"] > 0
            assert stored["matcher"]["candidate_match_count"] > 0
            text = json.dumps(stored)
            # no absolute filesystem paths leak into persisted artifacts
            assert "C:\\\\" not in text and ":///" not in text
            assert str(settings.data_root_path) not in text


# ---------------------------------------------------------------------------
# 16. API: success flow
# ---------------------------------------------------------------------------

def test_m3b_api_success_flow(settings_factory):
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"}).json()
        assert body["status"] == "SUCCESS"
        assert body["state"] == "SUCCESS"
        nc = body["matcher"]["candidate_match_count"]
        assert nc > 0

        st = client.get(f"/api/matching/{pair_id}/baseline/status").json()
        assert st["has_run"] is True
        assert st["latest_run"]["counts"]["candidates"] == nc
        assert st["latest_run"]["counts"]["keypoints_a"] == body["matcher"]["keypoint_count_a"]

        rund = client.get(f"/api/matching/runs/{body['run_id']}").json()
        assert rund["run_id"] == body["run_id"]
        assert rund["matcher_id"] == "sift"

        v = client.get(f"/api/matching/runs/{body['run_id']}/visualization")
        assert v.status_code == 200
        assert v.headers["content-type"] == "image/png"

        runs = client.get(f"/api/matching/{pair_id}/baseline/runs").json()
        assert {r["matcher_id"] for r in runs["runs"]} == {"sift"}

        pm = client.get(f"/api/pairs/{pair_id}/matches").json()
        assert pm["candidates"] == nc
        assert "verification" in pm["note"]


def test_m3b_api_blocked_akaze_recorded_honestly(settings_factory):
    from backend.app.matching.baseline import matcher_available

    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        available, _reason = matcher_available("akaze")
        resp = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "akaze"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if available:
            assert body["status"] == "SUCCESS"
        else:
            assert body["status"] == "BLOCKED"
            assert body["error_code"] == "MATCHER_NOT_AVAILABLE"
            art = settings.data_root_path / "metadata" / "m3_matching" / f"{body['run_id']}.json"
            assert art.is_file()
            assert body["matcher"]["matcher_id"] == "akaze"
            assert body["matcher"]["status"] == "BLOCKED"


# ---------------------------------------------------------------------------
# 17. M1 / M2 regression (this milestone must not weaken them)
# ---------------------------------------------------------------------------

def test_m3b_regression_raw_files_never_modified(settings_factory):
    client, settings, _tmp = _m3b_harness()
    raw_a = settings.data_root_path / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    raw_b = settings.data_root_path / "raw" / "tmc2" / "ch2_tmc_ncn_20200207T0716469418_d_img_d18.img"
    before = (raw_a.read_bytes().hex(), raw_b.read_bytes().hex())
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"})
    assert (raw_a.read_bytes().hex(), raw_b.read_bytes().hex()) == before


def test_m3b_regression_m2_products_present_after_prepare(settings_factory):
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        proc = settings.data_root_path / "derived" / "processing" / pair_id / "PC-M2-001"
        assert (proc / "preprocessing_ops.json").is_file()
        for sensor in ("ohrc", "tmc2"):
            assert (proc / sensor / "preprocessed_display_u16.npy").is_file()
            assert (proc / sensor / "invalid_mask_u8.npy").is_file()
        assert (settings.data_root_path / "raw" / "ohrc").exists()


def test_m3b_regression_m13_honesty_structure_of_artifacts(settings_factory):
    client, settings, _tmp = _m3b_harness()
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"}).json()
        art = settings.data_root_path / "metadata" / "m3_matching" / f"{body['run_id']}.json"
        text = art.read_text(encoding="utf-8")
        assert "final_confidence" not in text
        assert "confidence" not in text.lower()
        assert "trust gate" in text.lower() or "verdict" in text.lower()


# ---------------------------------------------------------------------------
# 18. frontend build
# ---------------------------------------------------------------------------

def test_m3b_frontend_build_succeeds_with_new_workspace():
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not (frontend / "package.json").is_file() or not npm:
        pytest.skip("frontend/npm unavailable in this environment")
    run = subprocess.run(
        [npm, "run", "build"], cwd=str(frontend),
        capture_output=True, text=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr[-2000:]
    assert (frontend / "dist" / "index.html").is_file()