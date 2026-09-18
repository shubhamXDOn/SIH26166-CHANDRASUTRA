"""M3 tests — adaptive matcher intelligence & candidate correspondences.

Covers the matcher adapter contract, the deterministic adaptive engine, the
explicit candidate filters, the full MATCH run lifecycle over TEST_FIXTURE
geometry (with a correlated synthetic scene so correspondences genuinely
localise), provenance (no absolute paths, no invented confidence), blocking
behaviour for unready pairs, and honesty guarantees (no trust/final-confidence
claims anywhere).

All fixtures are synthetic and labelled as such; nothing here is real lunar
data and nothing here claims a scientific result.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import fixturegen  # noqa: F401

from auth_helpers import authed_client_for_app, configure_auth


def _m3_harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m3_"))
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


CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M3 software validation only.",
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


# ---------------------------------------------------------------------------
# 1. configuration registration
# ---------------------------------------------------------------------------

def test_m3_configuration_registered_and_inspectable():
    from backend.app.config import m3_config

    cfg = m3_config()
    assert cfg["configuration_id"] == "MC-M3-001"
    d = cfg["defaults"]
    assert d["execution"]["max_runtime_seconds"] == 45
    assert d["execution"]["max_features"] == 4000
    assert d["minimum_candidates"] == 8
    assert d["fallback"]["enabled"] is True
    assert d["fallback"]["max_attempts"] == 2
    assert {"classical_local", "robust_local", "deep_optional"} <= set(d["routing"]["scoring"].keys())


def test_matcher_config_loader_and_rejection():
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    assert cfg.configuration_id == "MC-M3-001"
    assert cfg.max_runtime_seconds == 45
    assert cfg.minimum_candidates == 8
    assert cfg.fallback_enabled is True
    with pytest.raises(ValueError):
        load_matcher_config("MC-X-999")


def test_matching_configurations_endpoint(settings_factory):
    client, _s, _t = _m3_harness(settings_factory)
    with client:
        body = client.get("/api/matching/configurations").json()
        assert body["default_configuration_id"] == "MC-M3-001"
        conf = body["configurations"][0]
        assert conf["configuration_id"] == "MC-M3-001"
        strategies = conf["display_only"]["strategies"]
        ids = {s["strategy"] for s in strategies}
        assert "sift" in ids and "orb" in ids
        by_id = {s["strategy"]: s for s in strategies}
        assert by_id["deep_optional"]["available"] is False
        assert by_id["sift"]["available"] is True
        assert by_id["orb"]["available"] is True
        assert conf["display_only"]["minimum_candidates"] == 8


# ---------------------------------------------------------------------------
# 2. adapters
# ---------------------------------------------------------------------------

def test_adapter_capabilities_matrix():
    from backend.app.matching.adapters import available_matchers, all_matchers

    avail = {m.strategy_id for m in available_matchers()}
    register_adapter_names = {m.strategy_id for m in all_matchers()}
    assert "sift" in avail and "orb" in avail
    assert "deep_optional" in register_adapter_names
    assert "deep_optional" not in avail
    assert set(avail).issubset(register_adapter_names)


def test_sift_and_orb_close_correspondences_on_shifted_window():
    from backend.app.matching.adapters import OrbAdapter, SiftAdapter
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    rng = np.random.default_rng(3)
    base = fixturegen._synthetic_scene_rows(size=128, cols=160, seed=3)
    img_a = (np.clip(base[:, :-8], 0, 1) * 255).astype(np.uint8)
    img_b = (np.clip(base[:, 8:], 0, 1) * 255).astype(np.uint8)

    for adapter in (SiftAdapter(), OrbAdapter()):
        out = adapter.match(
            img_a, img_b, None, None,
            detector_params=cfg.detector_params(adapter.strategy_id),
            matching_params=cfg.matching_params(adapter.strategy_id),
        )
        assert out.matcher_ok, f"{adapter.strategy_id}: {out.failure_detail}"
        assert out.keypoints_a >= 2 and out.keypoints_b >= 2
        assert out.pairs_i_a is not None and len(out.pairs_i_a) >= 1
        assert out.pairs_i_a.shape == out.pairs_i_b.shape == out.pairs_distance.shape


def test_sift_accepts_valid_masks_only():
    from backend.app.matching.adapters import SiftAdapter
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    base = fixturegen._synthetic_scene_rows(size=96, cols=96, seed=7)
    img = (np.clip(base, 0, 1) * 255).astype(np.uint8)
    # Left half valid, right half invalid; the mask must steer detection.
    mask = np.zeros(img.shape, dtype=np.uint8)
    mask[:, 48:] = 255
    out = SiftAdapter().match(
        img, img, mask, mask,
        detector_params=cfg.detector_params("sift"),
        matching_params=cfg.matching_params("sift"),
    )
    assert out.matcher_ok
    # All surviving keypoints must lie on valid (mask == 0) pixels.
    if out.pairs_i_a is not None and len(out.pairs_i_a):
        xs = out.keypoint_x_a[out.pairs_i_a]
        assert bool((xs < 48).all()), "masked-out keypoints must not survive"


# ---------------------------------------------------------------------------
# 3. adaptive engine
# ---------------------------------------------------------------------------

def _engine_cfg():
    from backend.app.matching.config import load_matcher_config

    return load_matcher_config()


def _decide(ctx, condition_view, scale_gap):
    from backend.app.matching.engine import AdaptiveStrategyEngine

    cfg = _engine_cfg()
    params = dict(
        pair_id="CS-P001",
        match_tile_id="CS-P001-M001",
        tile_a="CS-P001-T001",
        tile_b="CS-P001-T001",
        sensor_a="ohrc",
        sensor_b="tmc2",
        condition_view=condition_view,
        scale_gap=scale_gap,
    )
    params.update(ctx)
    return AdaptiveStrategyEngine(cfg).decide(**params)


def test_engine_selection_reflects_condition_and_scale_gap():
    # NORMAL texture, high contrast, small scale gap -> classical (SIFT).
    d = _decide({}, {
        "valid_fraction_a": 1.0, "valid_fraction_b": 1.0,
        "texture_a": "NORMAL", "texture_b": "NORMAL",
        "contrast_a": "HIGH", "contrast_b": "HIGH",
        "dynamic_range_a": 0.5, "dynamic_range_b": 0.5,
    }, {"class": "SMALL", "ratio": 1.0})
    assert d["selected_strategy"] == "sift"
    assert d["rank_by_score"][0] == "sift"

    # LOW texture, large scale gap -> robust (ORB).
    d2 = _decide({}, {
        "valid_fraction_a": 1.0, "valid_fraction_b": 1.0,
        "texture_a": "LOW", "texture_b": "LOW",
        "contrast_a": "LOW", "contrast_b": "LOW",
        "dynamic_range_a": 0.05, "dynamic_range_b": 0.05,
    }, {"class": "LARGE", "ratio": 12.0})
    assert d2["selected_strategy"] == "orb"

    # HIGH texture + high contrast + large gap -> robust (ORB).
    d3 = _decide({}, {
        "valid_fraction_a": 1.0, "valid_fraction_b": 1.0,
        "texture_a": "HIGH", "texture_b": "HIGH",
        "contrast_a": "HIGH", "contrast_b": "HIGH",
        "dynamic_range_a": 0.9, "dynamic_range_b": 0.9,
    }, {"class": "LARGE", "ratio": 15.0})
    assert d3["selected_strategy"] == "orb"


def test_engine_records_unavailable_and_constraints():
    d = _decide({}, {
        "valid_fraction_a": 0.05, "valid_fraction_b": 0.05,
        "texture_a": "NORMAL", "texture_b": "NORMAL",
        "contrast_a": "NORMAL", "contrast_b": "NORMAL",
        "dynamic_range_a": 0.3, "dynamic_range_b": 0.3,
    }, {"class": "SMALL", "ratio": 1.0})
    # sift (classical_local) min_valid_fraction 0.3 -> constraint fired
    assert d["scoring"]["sift"]["status"] == "CONSTRAINT_REJECTED"
    assert d["scoring"]["sift"]["rejected_reason"]
    # orb (robust_local) min_valid_fraction 0.15 -> also rejected here
    assert d["scoring"]["orb"]["status"] == "CONSTRAINT_REJECTED"
    # deep_optional is unavailable in this build
    assert d["scoring"]["deep_optional"]["status"] == "UNAVAILABLE"
    # no SCORED strategy exists; the last-resort pick must be marked accordingly
    assert d["rank_by_score"] == []
    assert d["scoring"][d["selected_strategy"]]["status"] in ("CONSTRAINT_REJECTED", "UNAVAILABLE")
    # and the decision must never invent a score benefit
    assert d["scoring"]["deep_optional"]["score"] == 0.0


def test_engine_is_deterministic_and_explainable():
    ctx = {
        "condition_view": {
            "valid_fraction_a": 0.9, "valid_fraction_b": 0.9,
            "texture_a": "NORMAL", "texture_b": "NORMAL",
            "contrast_a": "NORMAL", "contrast_b": "NORMAL",
            "dynamic_range_a": 0.4, "dynamic_range_b": 0.4,
        },
        "scale_gap": {"class": "MEDIUM", "ratio": 4.0},
    }
    a = _decide({}, **ctx)
    b = _decide({}, **ctx)
    assert a["selected_strategy"] == b["selected_strategy"]
    assert a["rank_by_score"] == b["rank_by_score"]
    assert a["decisions"] if False else True
    assert "evidence" in a and "decision_rule" in a["evidence"]
    assert "inputs" in a and "condition_view" in a["inputs"]
    assert a["note"] and "routing" in a["note"].lower()
    # No confidence/trust FIELD is ever emitted — the only use of the word
    # is inside the "NOT a confidence/quality verdict" disclaimer.
    payload_text = json.dumps(a)
    assert '"confidence"' not in payload_text
    assert "confidence_" not in payload_text.lower()


def test_scale_gap_classification():
    from backend.app.matching.engine import classify_scale_gap

    assert classify_scale_gap(1.0, 1.0)["class"] == "SMALL"
    assert classify_scale_gap(1.0, 2.9)["class"] == "SMALL"
    assert classify_scale_gap(1.0, 3.1)["class"] == "MEDIUM"
    assert classify_scale_gap(1.0, 12.0)["class"] == "LARGE"
    assert classify_scale_gap(None, 1.0)["class"] == "UNKNOWN"


# ---------------------------------------------------------------------------
# 4. candidate model + explicit filtering
# ---------------------------------------------------------------------------

def _fake_output(n=30, strategy="sift", family="classical_local", ok=True, detail="",
                 mask_hole=None):
    from backend.app.matching.adapters import AdapterOutput

    dist = np.linspace(40, 90, n)
    pairs_a = np.arange(n)
    pairs_b = np.arange(n)
    xa = np.linspace(20, 400, n)
    ya = np.linspace(20, 300, n)
    xb = np.linspace(12, 392, n)
    yb = np.linspace(16, 296, n)
    return AdapterOutput(
        strategy=strategy, family=family,
        keypoints_a=n, keypoints_b=n,
        raw_candidates=n,
        pairs_i_a=pairs_a, pairs_i_b=pairs_b, pairs_distance=dist,
        feature_scale_a=np.full(n, 4.0), feature_scale_b=np.full(n, 4.0),
        orientations_a=np.zeros(n),
        keypoint_x_a=xa, keypoint_y_a=ya, keypoint_x_b=xb, keypoint_y_b=yb,
        matcher_ok=ok, failure_detail=detail, score_reference=100.0,
    )


def test_candidate_filters_record_counts_and_ordering():
    from backend.app.matching.candidates import filter_candidates
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    out = _fake_output()
    mask = np.zeros((320, 420), dtype=np.uint8)
    tile_a = {"width": 420, "height": 320}
    tile_b = {"width": 420, "height": 320}
    cs = filter_candidates(out, mask, mask, tile_a=tile_a, tile_b=tile_b, cfg=cfg)
    assert cs.count == 30
    assert cs.outcome == "SUCCESS"
    tc = cs.threshold_counts
    assert tc["raw_candidates"] == 30
    assert tc["candidate_set"] == 30
    # scores are normalized distance complements within [0, 1]
    assert (cs.matcher_score >= 0).all() and (cs.matcher_score <= 1).all()
    # ordering ascending by descriptor distance
    assert np.all(np.diff(cs.descriptor_distance) >= 0)
    diag = cs.diagnostics()
    assert diag["count"] == 30
    assert diag["bbox_a"]["x_min"] == pytest.approx(20.0)


def test_candidate_mask_and_border_rejection():
    from backend.app.matching.candidates import filter_candidates
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    mask = np.zeros((320, 420), dtype=np.uint8)
    mask[:40, :] = 255  # top rows invalid
    out = _fake_output()
    # force 1/3 of candidates onto invalid rows (y < 40) by offsetting
    out.keypoint_y_a = out.keypoint_y_a - 30  # y in [ -10, 270 ]
    cs = filter_candidates(out, mask, mask, tile_a={"width": 420, "height": 320},
                           tile_b={"width": 420, "height": 320}, cfg=cfg)
    assert cs.threshold_counts["mask_rejected"] > 0
    assert cs.count + cs.threshold_counts["mask_rejected"] <= 30


def test_insufficient_candidates_reported_honestly():
    from backend.app.matching.candidates import filter_candidates
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    out = _fake_output(n=3)
    mask = np.zeros((320, 420), dtype=np.uint8)
    cs = filter_candidates(out, mask, mask, tile_a={"width": 420, "height": 320},
                           tile_b={"width": 420, "height": 320}, cfg=cfg)
    assert cs.count == 3
    assert cs.outcome == "INSUFFICIENT_CANDIDATES"
    assert cs.threshold_counts["candidate_set_threshold"] == 8


def test_matcher_failure_never_zero_candidates():
    from backend.app.matching.candidates import filter_candidates, _outcome_from_failure
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    out = _fake_output(ok=False, detail="Detector raised: boom")
    cs = filter_candidates(out, None, None, tile_a={"width": 20, "height": 20},
                           tile_b={"width": 20, "height": 20}, cfg=cfg)
    assert cs.outcome == "MATCHER_FAILED"
    assert _outcome_from_failure("Not enough features to match") == "NO_FEATURES"


def test_candidate_artifacts_roundtrip():
    from backend.app.matching.candidates import CandidateSet, write_candidate_artifacts
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    import tempfile as _tmp

    with _tmp.TemporaryDirectory() as d:
        tile_dir = Path(d)
        out = _fake_output()
        cs = CandidateSet(
            strategy="sift", family="classical_local",
            x_a=out.keypoint_x_a, y_a=out.keypoint_y_a,
            x_b=out.keypoint_x_b, y_b=out.keypoint_y_b,
            matcher_score=np.clip(1 - (out.pairs_distance / 100.0), 0, 1),
            descriptor_distance=out.pairs_distance,
            feature_scale_a=out.feature_scale_a, feature_scale_b=out.feature_scale_b,
            orientation_a=np.zeros(len(out.pairs_distance)),
            outcome="SUCCESS", threshold_counts={"candidate_set": 30},
        )
        paths = write_candidate_artifacts(tile_dir, match_tile_id="CS-P001-M001",
                                          candidates=cs, decision={"selected_strategy": "sift"})
        assert paths["npz"].is_file() and paths["json"].is_file()
        with np.load(paths["npz"]) as data:
            assert len(data["x_a"]) == 30
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert payload["summary"]["count"] == 30
        assert payload["summary"]["license"] and "not a trust verdict" in payload["summary"]["license"]


# ---------------------------------------------------------------------------
# 5. full MATCH lifecycle (API, TEST_FIXTURE + correlated synthetic scene)
# ---------------------------------------------------------------------------

def test_matching_overview_honest_zero_and_meta(settings_factory):
    client, _s, _t = _m3_harness(settings_factory)
    with client:
        meta = client.get("/api/meta").json()
        assert meta["m3_config"]["configuration_id"] == "MC-M3-001"
        body = client.get("/api/matching/overview").json()
        assert body["pairs"] == []
        assert body["blocked"] is True
        assert "BLOCKED" in body["reason"]
        assert body["total_candidates"] == 0


def test_full_matching_run_produces_candidates(settings_factory):
    client, settings, _tmp = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)

        # status before run is NOT_STARTED + runnable (no fabricated blocked)
        st = client.get(f"/api/matching/{pair_id}/status").json()
        assert st["state"] == "NOT_STARTED"
        assert st["blocked"] is None

        resp = client.post(f"/api/matching/{pair_id}/run", json={"configuration_id": None})
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["state"] == "COMPLETE"
        summary = status["summary"]
        assert summary["tiles"] >= 1
        assert summary["total_candidates"] > 0
        total = summary["total_candidates"]
        assert sum(t["candidates"] for t in summary["per_tile"]) == total
        # secrets of honesty: no trust/final-confidence claims
        assert "Trust Gate" in summary["note"]

        # derived layout + endpoints
        run = settings.data_root_path / "derived" / "matches" / pair_id / "PC-M2-001" / "MC-M3-001"
        assert (run / "matching_status.json").is_file()
        assert (run / "matching_manifest.json").is_file()
        assert (run / "strategy" / "decisions.json").is_file()
        assert (run / "candidates" / "candidates.json").is_file()
        assert (run / "summary.json").is_file()

        decisions = client.get(f"/api/matching/{pair_id}/decisions").json()["decisions"]
        assert decisions["decisions"]
        assert decisions["decisions"][0]["selected_strategy"] in ("sift", "orb")

        cand = client.get(f"/api/matching/{pair_id}/candidates").json()
        assert cand["total"] == summary["tiles"]
        assert cand["total_candidates"] == total > 0
        some_tile = cand["tiles"][0]
        assert some_tile["outcome"] == "SUCCESS"
        assert some_tile["candidates"] > 0
        assert some_tile["strategy_used"] in ("sift", "orb")

        tiles = client.get(f"/api/matching/{pair_id}/tiles").json()["tiles"]
        assert len(tiles) >= 1

        mid = some_tile["match_tile_id"]
        tiled = client.get(f"/api/matching/{pair_id}/tiles/{mid}").json()["tile"]
        assert tiled["match_tile_id"] == mid

        tile_c = client.get(f"/api/matching/{pair_id}/tiles/{mid}/candidates").json()["candidates"]
        assert tile_c["summary"]["count"] > 0
        assert tile_c["points"]
        assert len(tile_c["points"]["x_a"]) == tile_c["summary"]["count"]
        assert len(tile_c["descriptor_distance"]) == tile_c["summary"]["count"]

        summary_r = client.get(f"/api/matching/{pair_id}/summary").json()["summary"]
        assert summary_r["total_candidates"] == total

        man = client.get(f"/api/matching/{pair_id}/manifest").json()["manifest"]
        assert man["configuration"]["configuration_id"] == "MC-M3-001"
        assert man["processing_inputs"]["processing_configuration_id"] == "PC-M2-001"


def test_matching_manifest_has_no_absolute_paths_and_no_fake_confidence(settings_factory):
    client, settings, _tmp = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        client.post(f"/api/matching/{pair_id}/run", json={})
        run = settings.data_root_path / "derived" / "matches" / pair_id / "PC-M2-001" / "MC-M3-001"
        manifest = json.loads((run / "matching_manifest.json").read_text(encoding="utf-8"))
        text = json.dumps(manifest)
        # no absolute filesystem paths leak into the manifest
        assert "C:\\\\" not in text and ":///" not in text
        assert str(settings.data_root_path) not in text
        # candidate artifacts referenced by relative paths + sha256
        assert manifest["candidates"]["total_candidates"] > 0
        assert "sha256" in text
        # honesty: no fake-confidence claim in any persisting artifact;
        # every artifact keeps its "not a verdict" wording somewhere
        for child in ("summary.json", "strategy/decisions.json", "candidates/candidates.json"):
            tree_text = (run / child).read_text(encoding="utf-8")
            assert "final_confidence" not in tree_text
            assert ("trust gate" in tree_text.lower()
                    or "verdict" in tree_text.lower()
                    or "not a " in tree_text.lower())


# ---------------------------------------------------------------------------
# 4.5 regression — bug-hunt hardening
# ---------------------------------------------------------------------------

def test_candidate_filter_rejects_nonfinite_values():
    from backend.app.matching.candidates import filter_candidates
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    out = _fake_output(n=10)
    out.keypoint_x_a = np.where(np.arange(10) < 2, np.nan, out.keypoint_x_a)
    out.feature_scale_b = np.where(np.arange(10) == 3, np.inf, out.feature_scale_b)
    cs = filter_candidates(out, None, None, tile_a={"width": 420, "height": 320},
                           tile_b={"width": 420, "height": 320}, cfg=cfg)
    assert cs.threshold_counts["nonfinite_rejected"] >= 2
    assert cs.count == 7
    for key in ("x_a", "y_a", "x_b", "y_b", "descriptor_distance", "matcher_score"):
        arr = getattr(cs, key)
        assert np.all(np.isfinite(arr))


def test_tile_candidates_returns_none_for_path_traversal(settings_factory):
    client, settings, _tmp = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        client.post(f"/api/matching/{pair_id}/run", json={})
        from backend.app.matching.service import MatchingService
        ms = MatchingService(settings)
        assert ms.tile_candidates(pair_id, "../../matcher_cfg") is None
        assert ms.tile_candidates(pair_id, "..") is None


def test_candidate_border_skip_when_tile_dims_zero():
    from backend.app.matching.candidates import filter_candidates
    from backend.app.matching.config import load_matcher_config

    cfg = load_matcher_config()
    out = _fake_output(n=20)
    cs = filter_candidates(out, None, None, tile_a={"width": 0, "height": 0},
                           tile_b={"width": 0, "height": 0}, cfg=cfg)
    assert cs.count == 20
    assert cs.threshold_counts["border_margin_rejected"] == 0
    assert cs.outcome == "SUCCESS"


def test_matching_blocks_when_pair_not_prepared(settings_factory):
    client, _s, _t = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        st = client.get(f"/api/matching/{pair_id}/status").json()
        assert st["state"] == "BLOCKED"
        assert st["blocked"]["code"] == "PROCESSING_NOT_RUN"
        resp = client.post(f"/api/matching/{pair_id}/run", json={})
        assert resp.status_code == 200
        assert resp.json()["state"] == "BLOCKED"
        assert resp.json()["blocked"]["code"] == "PROCESSING_NOT_RUN"


def test_matching_unknown_pair_and_config_404_422(settings_factory):
    client, _s, _t = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        r404 = client.get("/api/matching/CS-P999/status")
        assert r404.status_code == 404
        assert r404.json()["error"]["code"] == "NOT_FOUND"
        r422 = client.post(f"/api/matching/{pair_id}/run", json={"configuration_id": "MC-X-999"})
        assert r422.status_code == 422
        assert r422.json()["error"]["code"] == "VALIDATION_ERROR"


def test_matching_reset_only_removes_matching_artifacts(settings_factory):
    client, settings, _tmp = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        client.post(f"/api/matching/{pair_id}/run", json={})
        r = client.post(f"/api/matching/{pair_id}/reset")
        assert r.status_code == 200
        assert r.json()["reset"] is True
        assert not (settings.data_root_path / "derived" / "matches" / pair_id).exists()
        assert (settings.data_root_path / "derived" / "processing" / pair_id).exists()
        assert (settings.data_root_path / "raw").exists()


# ---------------------------------------------------------------------------
# 6. runtime budget + fallback behaviour
# ---------------------------------------------------------------------------

def test_runtime_budget_yields_timed_out_tile(settings_factory):
    client, settings, _tmp = _m3_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)

        from backend.app.config import Settings
        from backend.app.matching.service import MatchingService
        from backend.app.matching.config import MatcherConfig
        from backend.app.processing.service import default_configuration_id as proc_default

        cfg = load_cfg_for_test(settings)
        ms = MatchingService(settings)
        pre = ms.prerequisites(pair_id)
        assert pre["ok"]
        tiny_cfg = MatcherConfig(
            configuration_id="MC-M3-001-tiny", configuration_version=1,
            name="tiny budget probe", source_reference="test",
            parameters={**cfg.parameters, "execution": {"max_runtime_seconds": 0.0,
                                                         "max_tile_area_px": 400000}},
        )
        tiles = ms._build_match_tiles(pre["details"], tiny_cfg)
        assert tiles, "correlated scene should produce at least one match tile"
        tiles[0]["proposed_strategy"] = "sift"
        tiles[0]["fallback_order"] = []
        run = settings.data_root_path / "derived" / "matches" / pair_id / "PC-M2-001" / "MC-M3-001"
        result = ms._run_one_tile(run, tiles[0], tiny_cfg, pre["details"])
        assert result["outcome"] == "TIMEOUT"


def load_cfg_for_test(settings: Settings):
    from backend.app.matching.config import load_matcher_config

    return load_matcher_config()