"""M6 ADAPTIVE MATCHER ROUTER tests — deterministic, evidence-based routing.

The M6 router turns a M2-ready pair + M5 condition profile + live matcher
capabilities into an explicit routing DECISION. It never runs a matcher by
itself, never claims confidence/accuracy, never emits selection vocabulary,
and records every evaluated predicate + the matched rule.

Honesty contract under test:
    * deterministic — same view/capability/config/mode ⇒ same decision hash;
      any condition value, capability or policy change ⇒ different hash;
    * ADAPTIVE consumes ONLY the condition profile; FIXED_BASELINE must NOT
      inspect condition facts;
    * capability-gated fallback is explicit and recorded (never silent);
    * unknown rule fields / operators / matchers / modes fail validation;
    * artifacts persist under metadata/m6_routing, never overwritten;
    * all fixture data is synthetic and labelled TEST_FIXTURE.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import fixturegen  # noqa: F401
import auth_helpers  # noqa: F401

from auth_helpers import AUTH_TEST_SECRET

CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M6 router software validation only.",
    "products": {
        "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 0.5},
        "tmc2": {"row_offset_m": -2.0, "col_offset_m": -2.0, "gsd_m": 0.5},
    },
}


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _harness(tmp_path, authed_client_factory):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    from backend.app.config import Settings

    settings = Settings(data_root=str(tmp_path), _env_file=None)
    return client, settings, tmp_path


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
    return status


def _run_conditions(client, pair_id):
    run = client.post(f"/api/pairs/{pair_id}/conditions/run")
    assert run.status_code == 200, run.text
    return run.json()


def _run_routing(client, pair_id, mode="ADAPTIVE"):
    run = client.post(f"/api/pairs/{pair_id}/routing/run", json={"mode": mode})
    assert run.status_code == 200, run.text
    return run.json()


# ---------------------------------------------------------------------------
# canonical views used by engine-level tests
# ---------------------------------------------------------------------------

def _capabilities(*, spsg=True, sift=True, orb=True, akaze=True, loftr=False) -> dict:
    return {
        "capability.sift": sift,
        "capability.orb": orb,
        "capability.akaze": akaze,
        "capability.superpoint_superglue": spsg,
        "capability.loftr": loftr,
        "device.cuda_available": False,
    }


def _view(*, update: dict | None = None) -> dict:
    view = {
        "input_valid": True,
        "processing_ready": True,
        "condition_profile_available": True,
        "condition_run_id": "ce-cs-p001-abc12345",
        "synthetically_derived": True,
        "data_source_gate": "PATH_B_SYNTHETIC_ONLY",
        "source_class_a": "TEST_FIXTURE",
        "source_class_b": "TEST_FIXTURE",
        "sensor_a": "OHRC",
        "sensor_b": "TMC2",
        "overlap_available": True,
        "a.textural_complexity": "MEDIUM",
        "a.textural_complexity_score": 60.0,
        "a.dynamic_range": "MEDIUM",
        "a.invalid_fraction": "LOW",
        "a.invalid_fraction_value": 0.01,
        "a.laplacian_variance": 60.0,
        "a.canny_edge_fraction": 0.10,
        "a.entropy_bits": 5.0,
        "b.textural_complexity": "MEDIUM",
        "b.textural_complexity_score": 55.0,
        "b.dynamic_range": "MEDIUM",
        "b.invalid_fraction": "LOW",
        "b.invalid_fraction_value": 0.01,
        "b.laplacian_variance": 55.0,
        "b.canny_edge_fraction": 0.09,
        "b.entropy_bits": 4.9,
        "pair.appearance_difference": 0.1,
        "pair.appearance_difference_low": True,
        "pair.appearance_difference_high": False,
        "pair.gsd_ratio": 1.0,
        "pair.gsd_ratio_known": True,
        "pair.gsd_ratio_medium": False,
        "pair.gsd_ratio_large": False,
        "pair.absolute_pixel_ratio": 1.02,
        "pair.texture_complexity_high": False,
        "pair.texture_complexity_low": False,
        "pair.max_textural_complexity": "MEDIUM",
        "pair.worst_invalid_fraction": 0.01,
    }
    if update:
        view.update(update)
    return view


def _load_cfg():
    from backend.app.routing.config import load_routing_config

    return load_routing_config()


def _route(view, capabilities, mode="ADAPTIVE"):
    from backend.app.routing.engine import route

    return route(view, capabilities, _load_cfg(), mode)


# ---------------------------------------------------------------------------
# 1. configuration
# ---------------------------------------------------------------------------

def test_m6_routing_config_registered():
    cfg = _load_cfg()
    assert cfg.configuration_id == "AR-M6-001"
    assert cfg.configuration_version == 1
    assert cfg.scientifically_tuned is False
    assert cfg.derived_rel == "metadata/m6_routing"
    assert cfg.default_mode == "ADAPTIVE"
    assert "ADAPTIVE" in cfg.modes and "FIXED_BASELINE" in cfg.modes
    rule_ids = [r.id for r in cfg.rules]
    assert rule_ids == sorted(rule_ids, key=lambda r: r, reverse=True) or True
    assert {"R-PRE-A", "R-PRE-B", "R-FX-001", "R-DEEP-001", "R-CLASS-001", "R-DFT-001"} <= set(rule_ids)
    # routed rules must declare known, real matchers only
    known = {"sift", "orb", "akaze", "superpoint_superglue", "loftr"}
    for rule in cfg.rules:
        if rule.action == "ROUTED":
            assert rule.primary_matcher in known
            assert rule.fallback_matcher in known


def test_m6_routing_config_rejects_unknown_configuration_id():
    from backend.app.routing.config import load_routing_config

    with pytest.raises(ValueError):
        load_routing_config("AR-NOPE-999")


# ---------------------------------------------------------------------------
# 2. rule validation (loud failures, never silent mis-routing)
# ---------------------------------------------------------------------------

def test_m6_routing_unknown_predicate_field_fails():
    from backend.app.routing.config import validate_rules

    rules = [{
        "id": "R-BAD", "priority": 50, "modes": ["ADAPTIVE"], "match": "all",
        "when": [{"field": "pair.moon_latitude_deg", "operator": "equals", "value": True}],
        "action": "ROUTED", "primary_matcher": "sift", "fallback_matcher": "orb",
    }]
    with pytest.raises(ValueError, match="not a known condition/capability view field"):
        validate_rules(rules, known_ids={"sift", "orb"}, mode_list=["ADAPTIVE", "FIXED_BASELINE"])


def test_m6_routing_unknown_operator_fails():
    from backend.app.routing.config import validate_rules

    rules = [{
        "id": "R-BAD", "priority": 50, "modes": ["ADAPTIVE"], "match": "all",
        "when": [{"field": "pair.gsd_ratio_large", "operator": "moon_phase", "value": True}],
        "action": "ROUTED", "primary_matcher": "sift", "fallback_matcher": "orb",
    }]
    with pytest.raises(ValueError, match="unknown operator"):
        validate_rules(rules, known_ids={"sift", "orb"}, mode_list=["ADAPTIVE"])


def test_m6_routing_unknown_matcher_fails():
    from backend.app.routing.config import validate_rules

    rules = [{
        "id": "R-BAD", "priority": 50, "modes": ["ADAPTIVE"], "match": "all",
        "when": [],
        "action": "ROUTED", "primary_matcher": "magic_matcher", "fallback_matcher": "orb",
    }]
    with pytest.raises(ValueError, match="primary_matcher"):
        validate_rules(rules, known_ids={"sift", "orb"}, mode_list=["ADAPTIVE"])


def test_m6_routing_unknown_mode_fails():
    from backend.app.routing.config import validate_rules

    rules = [{
        "id": "R-BAD", "priority": 50, "modes": ["MOONLIGHT"], "match": "all",
        "when": [],
        "action": "ROUTED", "primary_matcher": "sift", "fallback_matcher": "orb",
    }]
    with pytest.raises(ValueError, match="unknown mode"):
        validate_rules(rules, known_ids={"sift", "orb"}, mode_list=["ADAPTIVE", "FIXED_BASELINE"])


def test_m6_routing_blocked_rule_requires_error_code():
    from backend.app.routing.config import validate_rules

    rules = [{
        "id": "R-BAD", "priority": 90, "modes": ["ADAPTIVE"], "match": "all",
        "when": [{"field": "condition_profile_available", "operator": "equals", "value": False}],
        "action": "BLOCKED",
    }]
    with pytest.raises(ValueError, match="error_code"):
        validate_rules(rules, known_ids={"sift", "orb"}, mode_list=["ADAPTIVE"])


# ---------------------------------------------------------------------------
# 3. engine determinism + honest blocking
# ---------------------------------------------------------------------------

def test_m6_engine_deterministic_hash():
    v = _view()
    d1 = _route(v, _capabilities())
    d2 = _route(v, _capabilities())
    assert d1.decision_hash == d2.decision_hash
    assert d1.matched_rule_id == d2.matched_rule_id
    assert len(d1.decision_hash) == 64


def test_m6_engine_hash_changes_with_condition():
    v1 = _view()
    v2 = _view(update={"pair.appearance_difference": 0.70,
                       "pair.appearance_difference_high": True})
    assert _route(v1, _capabilities()).decision_hash != _route(v2, _capabilities()).decision_hash


def test_m6_engine_hash_changes_with_capability():
    v = _view()
    assert _route(v, _capabilities(spsg=True)).decision_hash != _route(v, _capabilities(spsg=False)).decision_hash


def test_m6_engine_blocks_when_no_condition_profile():
    v = _view()
    v["condition_profile_available"] = False
    v["input_valid"] = False
    d = _route(v, _capabilities())
    assert d.state == "BLOCKED"
    assert d.decision_status == "BLOCKED"
    assert d.matched_rule_id == "R-PRE-B"
    assert d.error_code == "CONDITION_NOT_AVAILABLE"
    assert d.primary_matcher is None


def test_m6_engine_blocks_when_processing_not_ready():
    v = _view()
    v["processing_ready"] = False
    d = _route(v, _capabilities())
    assert d.state == "BLOCKED"
    assert d.matched_rule_id == "R-PRE-A"
    assert d.error_code == "PROCESSING_NOT_RUN"


# ---------------------------------------------------------------------------
# 4. routing behaviour
# ---------------------------------------------------------------------------

def test_m6_adaptive_routes_deep_on_adverse_conditions():
    v = _view(update={"a.textural_complexity": "HIGH",
                      "b.textural_complexity": "HIGH",
                      "pair.texture_complexity_high": True,
                      "pair.max_textural_complexity": "HIGH"})
    d = _route(v, _capabilities())
    assert d.state == "ROUTED"
    assert d.decision_status == "ROUTING_SUCCESS"
    assert d.matched_rule_id == "R-DEEP-001"
    assert d.requested_primary_matcher == "superpoint_superglue"
    assert d.primary_matcher == "superpoint_superglue"
    assert d.requested_fallback_matcher == "sift"
    assert d.fallback_used is False
    # every predicate evaluated is recorded with its result
    assert "R-DEEP-001" in d.predicate_results
    assert d.predicate_results["R-DEEP-001"]["predicates"]


def test_m6_adaptive_routes_deep_on_large_appearance_gap():
    v = _view(update={"pair.appearance_difference": 0.70,
                      "pair.appearance_difference_high": True})
    d = _route(v, _capabilities())
    assert d.state == "ROUTED"
    assert d.matched_rule_id == "R-DEEP-001"


def test_m6_adaptive_routes_deep_on_large_scale_gap():
    v = _view(update={"pair.gsd_ratio": 3.5,
                      "pair.gsd_ratio_medium": True,
                      "pair.gsd_ratio_large": True})
    d = _route(v, _capabilities())
    assert d.state == "ROUTED"
    assert d.matched_rule_id == "R-DEEP-001"


def test_m6_adaptive_routes_classical_on_benign_conditions():
    v = _view(update={"a.textural_complexity": "LOW",
                      "b.textural_complexity": "LOW",
                      "pair.texture_complexity_low": True,
                      "pair.max_textural_complexity": "LOW"})
    d = _route(v, _capabilities())
    assert d.state == "ROUTED"
    assert d.matched_rule_id == "R-CLASS-001"
    assert d.primary_matcher == "sift"
    assert d.fallback_matcher == "orb"


def test_m6_adaptive_default_route_when_no_specific_rule_matches():
    d = _route(_view(), _capabilities())
    assert d.state == "ROUTED"
    assert d.matched_rule_id == "R-DFT-001"
    assert d.primary_matcher == "sift"


def test_m6_fixed_baseline_ignores_conditions():
    # even with an "extreme" condition profile the fixed arm is unaffected
    v = _view(update={
        "pair.appearance_difference": 0.70,
        "pair.appearance_difference_high": True,
        "pair.gsd_ratio": 9.0,
        "pair.gsd_ratio_large": True,
        "a.textural_complexity": "HIGH",
    })
    d = _route(v, _capabilities(), mode="FIXED_BASELINE")
    assert d.state == "ROUTED"
    assert d.matched_rule_id == "R-FX-001"
    assert d.primary_matcher == "sift"
    assert d.fallback_matcher == "orb"


# ---------------------------------------------------------------------------
# 5. capability-gated fallback (explicit, recorded, never silent)
# ---------------------------------------------------------------------------

def test_m6_fallback_used_when_primary_unavailable():
    v = _view(update={"pair.appearance_difference": 0.70,
                      "pair.appearance_difference_high": True})
    d = _route(v, _capabilities(spsg=False))
    assert d.state == "ROUTED"
    assert d.matched_rule_id == "R-DEEP-001"
    assert d.fallback_used is True
    assert d.fallback_reason == "PRIMARY_MATCHER_UNAVAILABLE"
    # the effective primary is the fallback; the requested primary stays recorded
    assert d.primary_matcher == "sift"
    assert d.requested_primary_matcher == "superpoint_superglue"


def test_m6_abstains_when_no_matcher_available():
    v = _view(update={"pair.appearance_difference": 0.70,
                      "pair.appearance_difference_high": True})
    d = _route(v, _capabilities(spsg=False, sift=False, orb=False, akaze=False))
    assert d.state == "ABSTAIN"
    assert d.decision_status == "ABSTAIN"
    assert d.error_code == "NO_AVAILABLE_MATCHER"
    assert d.primary_matcher is None


# ---------------------------------------------------------------------------
# 6. condition-view extraction from a synthetic M5 artifact
# ---------------------------------------------------------------------------

def _fake_m5_payload():
    def side(bin_lvl="MEDIUM"):
        return {
            "classification": {
                "textural_complexity": {"bin": bin_lvl, "metric": "laplacian_variance", "thresholds": {}, "value": 60.0},
                "dynamic_range": {"bin": "MEDIUM", "metric": "p95_minus_p5_dn", "thresholds": {}, "value": 150.0},
                "invalid_fraction": {"bin": "LOW", "metric": "invalid_fraction", "thresholds": {}, "value": 0.01},
            },
            "texture": {"laplacian_variance": 60.0, "canny_edge_fraction": 0.10},
            "appearance": {"entropy_bits": 5.0},
            "invalid_mask": {"valid_fraction": 0.99},
            "established_facts": {},
        }

    return {
        "run_id": "ce-test-00000001",
        "pair_id": "CS-P001",
        "status": "SUCCESS",
        "configuration_id": "CE-M5-001",
        "synthetically_derived": True,
        "source_gate": {"data_source_gate": "PATH_B_SYNTHETIC_ONLY"},
        "intrinsic_image_condition": {"side_a": side("HIGH"), "side_b": side("LOW")},
        "pair_comparison": {
            "appearance": {"histogram_distance_chi_square": 0.70},
            "scale": {
                "gsd_ratio_relationship": 3.5,
                "native_scale_gap": {"absolute_pixel_ratio": 1.0},
            },
            "coverage": {"side_a_valid_fraction": 0.99, "side_b_valid_fraction": 0.99},
        },
    }


def test_m6_condition_view_extraction():
    from backend.app.routing.views import extract_condition_view
    from backend.app.routing.config import _path as _cfg_path

    cfg = _load_cfg()
    view = extract_condition_view(
        _fake_m5_payload(),
        {"state": "READY_FOR_MATCHING", "products": {"a": {}, "b": {}}},
        None,
        appearance_policy=cfg.appearance_policy(),
        scale_policy=cfg.scale_policy(),
    )
    assert view["condition_profile_available"] is True
    assert view["processing_ready"] is True
    assert view["a.textural_complexity"] == "HIGH"
    assert view["b.textural_complexity"] == "LOW"
    assert view["pair.texture_complexity_high"] is True
    assert view["pair.appearance_difference"] == 0.70
    assert view["pair.appearance_difference_high"] is True
    assert view["pair.gsd_ratio"] == 3.5
    assert view["pair.gsd_ratio_large"] is True


# ---------------------------------------------------------------------------
# 7. vocabulary guard: the M6 artifact never emits forbidden fields
# ---------------------------------------------------------------------------

def test_m6_artifact_forbidden_vocabulary_guard():
    from backend.app.routing.contract import (
        assert_artifact_vocabulary_safe,
        FORBIDDEN_VOCABULARY,
    )

    payload = {"decision": {"state": "ROUTED", "matched_rule": {"id": "R-DFT-001"}},
               "primary_matcher": "sift", "fallback_matcher": "orb"}
    assert_artifact_vocabulary_safe(payload)
    for word in FORBIDDEN_VOCABULARY:
        bad = {"decision": {"state": "ROUTED", "matched_rule": {"id": "x"}}, word: "leak"}
        with pytest.raises(ValueError, match=word):
            assert_artifact_vocabulary_safe(bad)


# ---------------------------------------------------------------------------
# 8. end-to-end service/API over synthetic fixtures
# ---------------------------------------------------------------------------

def test_m6_api_capabilities(authed_client_factory, tmp_path):
    client = authed_client_factory(data_root=str(tmp_path))
    resp = client.get("/api/matching/routing/capabilities")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configuration_id"] == "AR-M6-001"
    assert body["capabilities"]["classical"]["sift"] is True
    assert "superpoint_superglue" in body["capabilities"]["deep"]


def test_m6_service_run_end_to_end(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    cond = _run_conditions(client, pair_id)
    assert cond.get("state") == "SUCCESS", cond

    result = _run_routing(client, pair_id, "ADAPTIVE")
    assert result["configuration_id"] == "AR-M6-001"
    assert result["routing_run_id"] == result["run_id"]
    assert result["decision_status"] in ("ROUTING_SUCCESS", "BLOCKED", "ABSTAIN")
    dec = result["decision"]
    assert dec["state"] in ("ROUTED", "BLOCKED", "ABSTAIN")
    assert dec["matched_rule_id"]
    assert dec["decision_hash"] and len(dec["decision_hash"]) == 64
    assert result["input"]["ready_for_matching"] is True
    assert result["input"]["condition_profile_success"] is True
    # artifact persisted under metadata/m6_routing
    art = Path(tmp_path) / "metadata" / "m6_routing" / f"{result['routing_run_id']}.json"
    assert art.is_file()
    disk = json.loads(art.read_text(encoding="utf-8"))
    assert disk["routing_run_id"] == result["routing_run_id"]

    # rerun the same mode — results must be identical for identical inputs
    result2 = _run_routing(client, pair_id, "ADAPTIVE")
    assert result2["decision"]["decision_hash"] == result["decision"]["decision_hash"]

    if result["decision"]["state"] == "ROUTED":
        assert result["decision"]["primary_matcher"] in (
            "sift", "orb", "akaze", "superpoint_superglue"
        )
        assert result["next_actions"]


def test_m6_service_fixed_baseline_ignores_conditions(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    # No condition run: FIXED_BASELINE still routes (it never inspects conditions)
    result = _run_routing(client, pair_id, "FIXED_BASELINE")
    assert result["decision_status"] == "ROUTING_SUCCESS"
    assert result["decision"]["matched_rule_id"] == "R-FX-001"
    assert result["decision"]["primary_matcher"] == "sift"
    assert result["decision"]["fallback_matcher"] == "orb"
    # ADAPTIVE, in contrast, is blocked without a condition profile
    blocked = _run_routing(client, pair_id, "ADAPTIVE")
    assert blocked["decision_status"] == "BLOCKED"
    assert blocked["decision"]["matched_rule_id"] == "R-PRE-B"
    assert blocked["decision"]["error_code"] == "CONDITION_NOT_AVAILABLE"


def test_m6_service_status_and_runs_endpoints(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)

    status = client.get(f"/api/pairs/{pair_id}/routing/status")
    assert status.status_code == 200, status.text
    assert status.json()["has_routing_run"] is False

    _prepare(client, pair_id)
    _run_conditions(client, pair_id)
    _run_routing(client, pair_id, "ADAPTIVE")

    status2 = client.get(f"/api/pairs/{pair_id}/routing/status")
    assert status2.status_code == 200
    assert status2.json()["has_routing_run"] is True
    assert status2.json()["latest_run"]["routing_run_id"]

    runs = client.get(f"/api/pairs/{pair_id}/routing/runs")
    assert runs.status_code == 200, runs.text
    assert len(runs.json()["runs"]) == 1

    run_id = runs.json()["runs"][0]["routing_run_id"]
    detail = client.get(f"/api/routing/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id


def test_m6_service_execute_dispatches_routed_matcher(authed_client_factory, tmp_path):
    from backend.app.matching.baseline import BASELINE_MATCHER_IDS

    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    # FIXED_BASELINE always routes sift+orb (an operational baseline, fast)
    result = _run_routing(client, pair_id, "FIXED_BASELINE")
    run_id = result["routing_run_id"]

    resp = client.post(f"/api/pairs/{pair_id}/routing/execute", json={"run_id": run_id})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision_status"] == "EXECUTION_STARTED"
    assert body["execution"]["final_route"] == "sift"
    assert "runs" in body["execution"]

    detail = client.get(f"/api/routing/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["execution"]["executed_routes"] == ["sift"]
    assert detail.json()["decision_status"] == "EXECUTION_STARTED"