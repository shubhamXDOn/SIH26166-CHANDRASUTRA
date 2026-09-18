"""M8 tests — deep matcher benchmarking, adaptive expansion & trustworthy
matcher selection.

Covers: configuration registration, honest capability probing (deep matchers
truthfully REPORT RUNTIME_UNAVAILABLE when torch is absent — never fake),
the unified correspondence contract validation, categorical adaptive routing,
the full EXPAND lifecycle over TEST_FIXTURE geometry (using the correlated
synthetic scene), benchmark mode with per-matcher rows and categorical
downstream columns (NOT_RUN, never fabricated), M8/M3 read-path isolation
(M3 and M4 must never pick up ``m8`` run dirs), provenance without absolute
paths, deterministic EXP- experiment identity and the honesty guarantees
(no winner, no accuracy, no fabricated AI output).
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

PA = "CH2-20211228T2209_20200207T0716-TEST"


def _m8_harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m8_"))
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
    "reference": "Synthetic correlated scene for M8 software validation only.",
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
    return status


def _run_m3(client, pair_id):
    resp = client.post(f"/api/matching/{pair_id}/run", json={})
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "COMPLETE"


# ---------------------------------------------------------------------------
# 1. configuration registration + loader
# ---------------------------------------------------------------------------

def test_m8_configuration_registered_and_inspectable():
    from backend.app.config import m8_config
    from backend.app.matching.m8.config import DeepMatcherConfig, load_deep_matcher_config

    cfg = m8_config()
    assert cfg["configuration_id"] == "DM-M8-001"
    d = cfg["defaults"]
    assert d["preferred_matcher"] == "auto"
    assert d["classical"]["enabled"] is True
    assert d["deep"]["enabled"] is True
    assert d["benchmark"]["reference_dataset"] == "NOT_AVAILABLE"
    assert d["classical"]["strategies"] == ["sift", "orb"]
    assert "superpoint_superglue" in d["deep"]["strategies"]

    dm = load_deep_matcher_config()
    assert isinstance(dm, DeepMatcherConfig)
    assert dm.configuration_id == "DM-M8-001"
    assert dm.max_correspondences == 4000
    assert dm.require_finite is True
    assert dm.allow_deep is True
    assert dm.reference_dataset == "NOT_AVAILABLE"
    with pytest.raises(ValueError):
        load_deep_matcher_config("DM-X-999")


def test_meta_exposes_m8_config(settings_factory):
    client, _s, _t = _m8_harness(settings_factory)
    with client:
        meta = client.get("/api/meta").json()
        assert meta["m8_config"]["configuration_id"] == "DM-M8-001"
        assert meta["milestone"] == "M10"


# ---------------------------------------------------------------------------
# 2. honest capability probing
# ---------------------------------------------------------------------------

def test_capabilities_endpoint_honest():
    from backend.app.matching.m8.deep.adapter import SuperPointSuperGlueAdapter
    from backend.app.matching.m8.deep.loftr import LoFTRAdapter

    sp = SuperPointSuperGlueAdapter(model_dir="/nonexistent/models", device="auto")
    # torch/torchvision are NOT installed in the test env -> honest report.
    assert sp.is_available() is False
    assert sp.reason_if_unavailable() in ("RUNTIME_UNAVAILABLE", "MODEL_WEIGHTS_NOT_CONFIGURED")

    lt = LoFTRAdapter(model_dir="/nonexistent/models")
    assert lt.is_available() is False
    assert lt.reason_if_unavailable() == "RUNTIME_UNAVAILABLE"


def test_capabilities_api_reports_deep_unavailable(settings_factory):
    client, _s, _t = _m8_harness(settings_factory)
    with client:
        body = client.get("/api/matching/capabilities").json()
        by_id = {m["matcher_id"]: m for m in body["matchers"]}
        assert {"sift", "orb"} <= set(by_id)
        assert "superpoint_superglue" in by_id
        assert "loftr" in by_id
        # classical matchers genuinely available
        assert by_id["sift"]["available"] is True
        assert by_id["orb"]["available"] is True
        # deep matchers never report available unless provisioned (no torch here)
        assert by_id["superpoint_superglue"]["available"] is False
        assert by_id["loftr"]["available"] is False
        for mid in ("superpoint_superglue", "loftr"):
            assert by_id[mid]["reason_if_unavailable"]
        # device payload present; CPU always usable
        assert body["device"]["cpu"]["available"] is True
        assert body["configurations"][0]["configuration_id"] == "DM-M8-001"


# ---------------------------------------------------------------------------
# 3. unified correspondence contract
# ---------------------------------------------------------------------------

def _adapter_output(xa, ya, xb, yb, dist=None, conf=None):
    from backend.app.matching.m8.base import M8AdapterOutput

    return M8AdapterOutput(matcher_id="sift", matcher_family="classical",
                           x_a=np.asarray(xa, dtype=float), y_a=np.asarray(ya, dtype=float),
                           x_b=np.asarray(xb, dtype=float), y_b=np.asarray(yb, dtype=float),
                           descriptor_distance=np.asarray(dist, dtype=float) if dist is not None else None,
                           matcher_confidence=np.asarray(conf, dtype=float) if conf is not None else None)


def test_contract_rejects_nonfinite_bounds_mask_and_duplicates():
    from backend.app.matching.m8.contract import validate_and_normalize

    w = 64
    mask = np.zeros((w, w), dtype=np.uint8)
    mask[45:55, 45:55] = 1  # invalid region covering the (50,50) correspondence
    out = _adapter_output(
        xa=[10.0, 50.0, 10.0, np.nan, 10.0],
        ya=[10.0, 50.0, 10.0, 10.0, 10.0],
        xb=[11.0, 51.0, 11.0, 11.0, 11.0],
        yb=[11.0, 51.0, 11.0, 11.0, 11.0],
        dist=[0.2, 0.3, 0.4, 0.5, 0.2],
    )
    c = validate_and_normalize(out, tile_id="T-1", width_a=w, height_a=w, width_b=w, height_b=w,
                               mask_a=mask, mask_b=mask, max_correspondences=100)
    # coords (50,50) are inside the masked-off region -> mask_rejected >= 1
    assert c.funnel["nonfinite_rejected"] == 1
    assert c.funnel["mask_rejected"] >= 1
    assert c.funnel["duplicates_rejected"] >= 1  # two identical (10,10)->(11,11)
    assert c.count > 0
    assert c.outcome == "CANDIDATES"

    # deterministic ordering: ascending descriptor distance
    dists = [float(v) for v in c.descriptor_distance]
    assert dists == sorted(dists)


def test_contract_bounds_and_cap_and_no_confidence_needed():
    from backend.app.matching.m8.contract import validate_and_normalize

    w = 64
    out = _adapter_output(xa=[0.0, 10.0], ya=[0.0, 10.0], xb=[2.0, 11.0], yb=[8.0, 9.0],
                          dist=[0.1, 0.2])
    # x=0 with margin 4 -> out of bounds
    c = validate_and_normalize(out, tile_id="T-2", width_a=w, height_a=w, width_b=w, height_b=w,
                               mask_a=None, mask_b=None, max_correspondences=1)
    assert c.funnel["bounds_rejected"] >= 1
    assert c.count == 1  # capped at 1
    # absent confidence must not trigger non-finite rejection
    assert c.funnel["nonfinite_rejected"] == 0
    assert (c.to_canonical()[0]["matcher_observations"]["descriptor_distance"]) == round(0.2, 6)


# ---------------------------------------------------------------------------
# 4. categorical adaptive routing
# ---------------------------------------------------------------------------

def test_routing_modes_categorical_and_honest():
    from backend.app.matching.m8.routing import route_tile

    args = dict(tile_id="T-1", m3_decision={"selected_strategy": "sift"},
                condition_view={"valid_fraction_a": 0.9, "valid_fraction_b": 0.9},
                available_classical=["sift", "orb"], available_deep=[],
                preferred_matcher="auto", mode="AUTO", allow_classical=True,
                allow_deep=True, fallback_to_classical=True)
    r = route_tile(**args)
    assert r.strategy_order == ["sift", "orb"]
    assert r.reason == "CLASSICAL_ADAPTIVE"
    assert r.to_dict()["requested_strategy"] == "sift"

    scar = route_tile(**{**args, "condition_view": {"valid_fraction_a": 0.10, "valid_fraction_b": 0.2},
                         "available_deep": ["superpoint_superglue"]})
    assert scar.strategy_order[0] == "superpoint_superglue"
    assert scar.reason == "FEATURE_SCARCITY"

    classical_only = route_tile(**{**args, "mode": "CLASSICAL_ONLY", "available_deep": ["superpoint_superglue"]})
    assert classical_only.strategy_order == ["sift", "orb"]
    assert classical_only.reason == "CLASSICAL_MANDATED"

    deep_only = route_tile(**{**args, "mode": "DEEP_ONLY", "available_deep": ["superpoint_superglue"],
                              "allow_classical": True})
    assert deep_only.strategy_order == ["superpoint_superglue", "sift", "orb"]  # classical fallback appended
    assert deep_only.reason == "DEEP_MANDATED"

    none_eligible = route_tile(**{**args, "mode": "DEEP_ONLY", "available_deep": []})
    assert none_eligible.reason == "NO_ELIGIBLE_MATCHER"
    assert none_eligible.strategy_order == []

    # routing payloads never carry a fabricated numeric confidence/winner/accuracy
    text = json.dumps(r.to_dict())
    assert "final_confidence" not in text and "winner" not in text.lower() and "accuracy" not in text.lower()


# ---------------------------------------------------------------------------
# 5. full EXPAND lifecycle (API)
# ---------------------------------------------------------------------------

def test_full_m8_run_produces_candidates_and_artifacts(settings_factory):
    client, settings, _tmp = _m8_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)

        st = client.get(f"/api/matching/{pair_id}/m8/status").json()
        assert st["state"] in ("NOT_STARTED", "BLOCKED")

        resp = client.post(f"/api/matching/{pair_id}/m8/run", json={})
        assert resp.status_code == 200, resp.text
        status = resp.json()
        assert status["state"] in ("COMPLETE", "INSUFFICIENT"), status.get("error")
        summary = status["summary"]
        assert summary["tiles"] >= 1

        run = (settings.data_root_path / "derived" / "matches" / pair_id
               / "PC-M2-001" / "m8" / "DM-M8-001")
        assert (run / "m8_status.json").is_file()
        assert (run / "m8_manifest.json").is_file()
        assert (run / "routing" / "routing.json").is_file()
        assert (run / "candidates" / "candidates.json").is_file()
        assert (run / "summary.json").is_file()

        routing = client.get(f"/api/matching/{pair_id}/m8/routing").json()["routing"]
        assert routing["rows"]
        assert {"strategy_order", "reason", "requested_strategy"} <= set(routing["rows"][0])

        idx = client.get(f"/api/matching/{pair_id}/m8/candidates").json()["index"]
        assert idx["total_candidates"] == summary["total_candidates"]

        # manifest: no absolute paths, hashes present, honest note
        man = client.get(f"/api/matching/{pair_id}/m8/manifest").json()["manifest"]
        text = json.dumps(man)
        assert "C:\\\\" not in text and str(settings.data_root_path) not in text
        assert "sha256" in text
        assert "never a truth" in text or "verdict" in text

        # provenance node exists and is M8
        prov = client.get(f"/api/matching/{pair_id}/m8/provenance").json()["provenance"]
        assert prov["milestone"] == "M8"

        # deterministic experiment identity
        exp1 = client.get(f"/api/matching/{pair_id}/m8/experiment").json()["experiment"]
        exp2 = client.get(f"/api/matching/{pair_id}/m8/experiment").json()["experiment"]
        assert exp1["experiment_id"] == exp2["experiment_id"]
        assert exp1["experiment_id"].startswith("EXP-")
        assert exp1["seed"]["experiment_policy"]["reference_dataset"] == "NOT_AVAILABLE"


def test_m8_run_does_not_perturb_m3_and_m4_read_paths(settings_factory):
    from backend.app.trust.service import TrustService

    client, settings, _tmp = _m8_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)
        client.post(f"/api/matching/{pair_id}/m8/run", json={})

        # M3 read paths still resolve to the M3 run (MC-M3-001), not m8/DM-M8-001
        m = client.get(f"/api/matching/{pair_id}/status").json()
        assert m["configuration_id"] == "MC-M3-001"
        man = client.get(f"/api/matching/{pair_id}/manifest").json()["manifest"]
        assert man["configuration"]["configuration_id"] == "MC-M3-001"

        # M4 _match_run_dir must NOT select the m8 run even though it has a summary.json
        trust = TrustService(settings.data_root_path, {})
        match_dir = trust._match_run_dir(pair_id)
        assert match_dir is not None
        assert not any(part == "m8" for part in match_dir.parts)
        assert (match_dir / "summary.json").is_file()

        # M8 runs endpoint lists the DM-M8-001 run
        runs = client.get(f"/api/matching/{pair_id}/m8/runs").json()["runs"]
        assert runs and runs[0]["configuration_id"] == "DM-M8-001"


def test_m8_blocked_for_unprocessed_pair(settings_factory):
    client, _s, _t = _m8_harness(settings_factory)
    with client:
        pair_id = _register(client)
        st = client.get(f"/api/matching/{pair_id}/m8/status").json()
        assert st["state"] == "BLOCKED"
        assert st["blocked"]["code"] in ("PROCESSING_NOT_RUN", "PROCESS_NOT_READY")
        # running it produces the same truth
        resp = client.post(f"/api/matching/{pair_id}/m8/run", json={})
        assert resp.json()["state"] == "BLOCKED"


# ---------------------------------------------------------------------------
# 6. benchmark mode
# ---------------------------------------------------------------------------

def test_benchmark_mode_rows_categorical_no_winner_no_accuracy(settings_factory):
    client, settings, _tmp = _m8_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)

        resp = client.post(f"/api/matching/{pair_id}/m8/run", json={"mode": "AUTO", "benchmark": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["state"] in ("COMPLETE", "INSUFFICIENT")

        bench = client.get(f"/api/matching/{pair_id}/m8/benchmark").json()["benchmark"]
        assert bench["reference_dataset"] == "NOT_AVAILABLE"
        rows = bench["rows"]
        assert rows
        mids = {r["matcher_id"] for r in rows}
        assert "sift" in mids
        assert rows[0]["m4_trusted"] in ("NOT_RUN", "COMPLETE", "RUNNING", "BLOCKED")
        assert rows[0]["m5_supported"] in ("NOT_RUN", "COMPLETE", "RUNNING", "BLOCKED")
        assert rows[0]["m6_registration_reachable"] in ("NOT_RUN", "COMPLETE", "RUNNING", "BLOCKED")

        # honesty: no fabricated winner/accuracy column is ever produced
        text = json.dumps(bench)
        assert '"winner":' not in text
        assert '"accuracy":' not in text
        assert '"ce90":' not in text
        assert "rated_" not in text

        # column set exactly as specified
        expected = {"tile_id", "matcher_id", "matcher_family", "runtime", "runtime_ms",
                    "candidate_count", "finite_count", "mask_valid_count", "duplicate_count",
                    "usable_count", "outcome", "m4_trusted", "m5_supported",
                    "m6_registration_reachable", "synthetically_derived", "note"}
        assert expected <= set(rows[0])


def test_benchmark_classical_only_mode_skips_deep(settings_factory):
    client, settings, _tmp = _m8_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)
        resp = client.post(f"/api/matching/{pair_id}/m8/run",
                           json={"mode": "CLASSICAL_ONLY", "benchmark": True})
        assert resp.status_code == 200, resp.text
        bench = client.get(f"/api/matching/{pair_id}/m8/benchmark").json()["benchmark"]
        assert {r["matcher_family"] for r in bench["rows"]} <= {"classical"}


# ---------------------------------------------------------------------------
# 7. reset
# ---------------------------------------------------------------------------

def test_m8_reset_removes_only_m8_artifacts(settings_factory):
    client, settings, _tmp = _m8_harness(settings_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _run_m3(client, pair_id)
        client.post(f"/api/matching/{pair_id}/m8/run", json={})
        m8_root = settings.data_root_path / "derived" / "matches" / pair_id / "PC-M2-001" / "m8"
        assert m8_root.is_dir()
        resp = client.post(f"/api/matching/{pair_id}/m8/reset", json={})
        assert resp.status_code == 200, resp.text
        assert not m8_root.exists()
        # M3 run untouched
        m3_status = client.get(f"/api/matching/{pair_id}/status").json()
        assert m3_status["state"] == "COMPLETE"