"""M5 CONDITION ESTIMATOR tests — pair-level condition & difficulty
characterization (pre-matcher-selection layer).

The M5 condition estimator evaluates the intrinsic condition of each side
(texture energy, edge density, Laplacian variance, entropy, robust intensity
statistics, invalid-mask coverage) plus the pair relationship (appearance
histogram distance, recorded scale/GSD relationships) from validated M2
products ONLY, and records optional latest-baseline matcher observations in a
SEPARATE, explicitly-labelled section.

Honesty contract under test:
    * reproducible — fixed input + fixed configuration ⇒ identical metrics;
    * deterministic fixed-stride sampling plan recorded in every artifact;
    * NEVER selects, recommends or routes a matcher — no forbidden fields;
    * GSD only from recorded geometry / PDS4 labels; UNKNOWN when absent;
    * blocked outcomes use stable codes (never a faked SUCCESS);
    * all fixture data is synthetic and labelled TEST_FIXTURE.
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

import fixturegen  # noqa: F401
import auth_helpers  # noqa: F401

from auth_helpers import AUTH_TEST_SECRET

CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M5 condition estimator software validation only.",
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


def _cfg(**overrides):
    from backend.app.conditions.config import load_condition_config

    cfg = load_condition_config()
    if overrides:
        params = copy.deepcopy(cfg.parameters)
        _deep_set(params, overrides)
        from backend.app.conditions.config import ConditionConfig

        cfg = ConditionConfig(
            configuration_id=cfg.configuration_id,
            configuration_version=cfg.configuration_version,
            name=cfg.name,
            source_reference=cfg.source_reference,
            derived_rel=cfg.derived_rel,
            scientifically_tuned=cfg.scientifically_tuned,
            parameters=params,
        )
    return cfg


def _deep_set(params, mapping):
    for key, value in mapping.items():
        if isinstance(value, dict):
            node = params.setdefault(key, {})
            _deep_set(node, value)
        else:
            params[key] = value


def _textured(shaped=(512, 512), seed=3):
    rng = np.random.default_rng(seed)
    return (rng.integers(0, 65535, size=shaped, dtype=np.uint16) * 0.5 + 20000).astype(np.uint16)


def _flat(shaped=(512, 512), value=32000):
    return np.full(shaped, value, dtype=np.uint16)


def _pair_run(client, settings, pair_id):
    run = client.post(f"/api/pairs/{pair_id}/conditions/run")
    assert run.status_code == 200, run.text
    body = run.json()
    state_code = (body.get("state") or body.get("status"))
    assert state_code in ("SUCCESS", "BLOCKED", "FAILED"), body
    return body


# ---------------------------------------------------------------------------
# 1. configuration
# ---------------------------------------------------------------------------

def test_m5_condition_config_loaded_registered():
    from backend.app.conditions.config import load_condition_config

    cfg = load_condition_config()
    assert cfg.configuration_id == "CE-M5-001"
    assert cfg.configuration_version == 1
    assert cfg.scientifically_tuned is False
    assert cfg.derived_rel == "metadata/m5_condition"
    assert cfg.window_size_px == 256
    assert cfg.stride_px == 128
    assert cfg.sampling_seed == 20260922
    assert cfg.max_windows == 1024
    assert {"low_lt", "high_ge"} <= set(cfg.classification_key("textural_complexity"))
    assert cfg.p("data_gate", "require_real", default=True) is False


def test_m5_condition_config_rejects_unknown_configuration_id():
    from backend.app.conditions.config import load_condition_config

    with pytest.raises(ValueError):
        load_condition_config("CE-NOT-A-REAL-ID")


def test_m5_documented_error_codes_exist():
    from backend.app.conditions import contract

    for code in (
            "INVALID_INPUT", "PROCESSING_NOT_RUN", "PROCESS_NOT_READY",
            "PRODUCT_MISSING", "PAIR_NOT_AVAILABLE", "REAL_DATA_BLOCKED",
            "CONDITION_ESTIMATION_FAILED", "RESOURCE_LIMIT"):
        assert code in contract.ERROR_CODES


# ---------------------------------------------------------------------------
# 2. contract validation
# ---------------------------------------------------------------------------

def test_m5_contract_rejects_nd_display():
    from backend.app.conditions.metrics import side_condition
    from backend.app.conditions.contract import ConditionInputError

    with pytest.raises(ConditionInputError):
        side_condition(np.zeros((5, 6, 3), dtype=np.uint16), np.zeros((5, 6), dtype=np.uint8), _cfg(), side_id="a")


def test_m5_contract_rejects_shape_mismatch():
    from backend.app.conditions.metrics import side_condition
    from backend.app.conditions.contract import ConditionInputError

    with pytest.raises(ConditionInputError):
        side_condition(np.zeros((10, 10), dtype=np.uint16), np.zeros((11, 10), dtype=np.uint8), _cfg(), side_id="a")


def test_m5_contract_rejects_empty_plane():
    from backend.app.conditions.metrics import side_condition
    from backend.app.conditions.contract import ConditionInputError

    with pytest.raises(ConditionInputError):
        side_condition(np.zeros((0, 10), dtype=np.uint16), np.zeros((0, 10), dtype=np.uint8), _cfg(), side_id="a")


def test_m5_contract_rejects_null_inputs():
    from backend.app.conditions.metrics import side_condition
    from backend.app.conditions.contract import ConditionInputError

    with pytest.raises(ConditionInputError):
        side_condition(None, np.zeros((10, 10), dtype=np.uint8), _cfg(), side_id="a")
    with pytest.raises(ConditionInputError):
        side_condition(np.zeros((10, 10), dtype=np.uint16), None, _cfg(), side_id="a")


# ---------------------------------------------------------------------------
# 3. determinism
# ---------------------------------------------------------------------------

def test_m5_metrics_deterministic():
    from backend.app.conditions.metrics import side_condition

    a = _textured()
    mask = np.zeros_like(a, dtype=np.uint8)
    mask[10, 10] = 2
    c1 = side_condition(a, mask, _cfg(), side_id="a")
    c2 = side_condition(a, mask, _cfg(), side_id="a")
    for key in set(c1) - {"_pooled_values"}:
        assert c1[key] == c2[key], f"non-deterministic field: {key}"
    np.testing.assert_array_equal(c1["_pooled_values"], c2["_pooled_values"])


def test_m5_run_deterministic(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        r1 = _pair_run(client, settings, pair_id)
        r2 = _pair_run(client, settings, pair_id)
        assert r1["status"] == r2["status"] == "SUCCESS"
        assert r1["run_id"] != r2["run_id"]
        for section in ("intrinsic_image_condition", "pair_comparison", "processing"):
            assert r1[section] == r2[section], f"section {section} must be run-deterministic"


# ---------------------------------------------------------------------------
# 4. metrics
# ---------------------------------------------------------------------------

def test_m5_gradient_energy_ordering():
    from backend.app.conditions.metrics import side_condition

    tex = side_condition(_textured(), np.zeros((512, 512), dtype=np.uint8), _cfg(), side_id="a")
    flat = side_condition(_flat(), np.zeros((512, 512), dtype=np.uint8), _cfg(), side_id="a")
    assert tex["texture"]["gradient_energy_mean_mag_sq"] > flat["texture"]["gradient_energy_mean_mag_sq"]


def test_m5_edge_density_flat_vs_edged():
    from backend.app.conditions.metrics import side_condition

    check = np.zeros((256, 256), dtype=np.uint16)
    check[::8, :] = 60000
    check[:, ::8] = 60000
    edged = side_condition(check, np.zeros_like(check, dtype=np.uint8), _cfg(), side_id="a")
    flat = side_condition(_flat((256, 256)), np.zeros((256, 256), dtype=np.uint8), _cfg(), side_id="a")
    assert (edged["texture"]["canny_edge_fraction"] or 0) > (flat["texture"]["canny_edge_fraction"] or 0)


def test_m5_laplacian_variance_ordering():
    from backend.app.conditions.metrics import side_condition

    tex = side_condition(_textured(), np.zeros((512, 512), dtype=np.uint8), _cfg(), side_id="a")
    flat = side_condition(_flat(), np.zeros((512, 512), dtype=np.uint8), _cfg(), side_id="a")
    assert (tex["texture"]["laplacian_variance"] or 0) > (flat["texture"]["laplacian_variance"] or 0)


def test_m5_entropy_flat_is_zero_textured_positive():
    from backend.app.conditions.metrics import side_condition

    flat = side_condition(_flat(), np.zeros((512, 512), dtype=np.uint8), _cfg(), side_id="a")
    tex = side_condition(_textured(), np.zeros((512, 512), dtype=np.uint8), _cfg(), side_id="a")
    assert flat["appearance"]["entropy_bits"] == 0.0
    assert tex["appearance"]["entropy_bits"] > 0.0


def test_m5_constant_image_detected():
    from backend.app.conditions.metrics import side_condition

    const = side_condition(_flat((256, 256), value=50000), np.zeros((256, 256), dtype=np.uint8), _cfg(), side_id="a")
    assert const["appearance"]["is_constant_layout"] is True
    assert const["appearance"]["entropy_bits"] == 0.0


def test_m5_saturation_fraction_detected():
    from backend.app.conditions.metrics import side_condition

    a = _flat()
    mask = np.zeros_like(a, dtype=np.uint8)
    mask[:5, :5] = 2          # MASK_SATURATED
    mask[200, 200] |= 1        # MASK_NAN_INF
    out = side_condition(a, mask, _cfg(), side_id="a")
    flags = out["invalid_mask"]["contributing_flags"]
    assert flags["saturated_pixels"] == 25
    assert flags["nan_inf_pixels"] == 1


def test_m5_nan_inf_fraction_and_negative():
    from backend.app.conditions.metrics import side_condition

    a = _flat()
    mask = np.zeros_like(a, dtype=np.uint8)
    mask[10:12, 10:12] |= 1  # nan/inf
    mask[20, 20] |= 4        # negative
    mask[40:50, 0] |= 8      # unknown
    out = side_condition(a, mask, _cfg(), side_id="a")
    flags = out["invalid_mask"]["contributing_flags"]
    assert flags["nan_inf_pixels"] == 4
    assert flags["negative_pixels"] == 1
    assert flags["unknown_pixels"] == 10


def test_m5_valid_fraction_never_inverted():
    from backend.app.conditions.metrics import side_condition

    a = _flat((100, 100))
    mask = np.zeros_like(a, dtype=np.uint8)
    mask[0, 0] = 99  # one invalid pixel; mask==0 means VALID
    out = side_condition(a, mask, _cfg(), side_id="a")
    total = 100 * 100
    assert out["invalid_mask"]["valid_pixels"] == total - 1
    assert abs(out["invalid_mask"]["valid_fraction"] - (total - 1) / total) < 1e-9


def test_m5_robust_intensity_stats():
    from backend.app.conditions.metrics import side_condition

    values = np.tile(np.arange(1, 101, dtype=np.float32), (64, 64))
    arr = values.astype(np.uint16)
    out = side_condition(arr, np.zeros_like(arr, dtype=np.uint8), _cfg(), side_id="a")
    rob = out["appearance"]["robust_intensity_dn"]
    assert rob["p50"] == 50.5
    assert abs(rob["p5"] - np.percentile(values, 5)) < 1e-6
    assert abs(rob["p95"] - np.percentile(values, 95)) < 1e-6
    assert abs(rob["iqr_dn"] - (np.percentile(values, 75) - np.percentile(values, 25))) < 1e-6


def test_m5_histogram_distance_same_is_zero():
    from backend.app.conditions.metrics import pair_comparison, side_condition

    arr = _textured()
    mask = np.zeros_like(arr, dtype=np.uint8)
    a = side_condition(arr, mask, _cfg(), side_id="a")
    assert pair_comparison(a, a, _cfg(), gsd_a=None, gsd_b=None)["appearance"]["histogram_distance_chi_square"] == 0.0


def test_m5_histogram_distance_different_positive():
    from backend.app.conditions.metrics import pair_comparison, side_condition

    mask = np.zeros((512, 512), dtype=np.uint8)
    a = side_condition(_textured(seed=1), mask, _cfg(), side_id="a")
    b = side_condition((_textured(seed=1) + 30000).astype(np.uint16), mask, _cfg(), side_id="b")
    d = pair_comparison(a, b, _cfg(), gsd_a=None, gsd_b=None)["appearance"]["histogram_distance_chi_square"]
    assert d is not None and d > 0.0


def test_m5_large_image_bounded_sampling():
    from backend.app.conditions.metrics import side_condition

    rng = np.random.default_rng(0)
    big = rng.integers(0, 65535, size=(4096, 4096), dtype=np.uint16)
    mask = np.zeros_like(big, dtype=np.uint8)
    cfg = _cfg(**{"sampling": {"max_windows": 16}})
    out = side_condition(big, mask, cfg, side_id="a")
    plan = out["sampling"]
    assert plan["method"] == "fixed_stride_grid"
    assert plan["windows_total"] <= 16
    assert plan["stride_used_px"] >= cfg.stride_px
    assert 0.0 < plan["sample_fraction"] <= 1.0
    assert "seed_recorded" in plan and "pixels_examined_aggregate" in plan


# ---------------------------------------------------------------------------
# 5. scale / GSD relationships
# ---------------------------------------------------------------------------

def test_m5_gsd_recorded_source(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        assert body["status"] == "SUCCESS"
        scale = body["pair_comparison"]["scale"]
        for side in ("side_a_gsd", "side_b_gsd"):
            assert scale[side]["gsd_m"] == 0.5
            assert scale[side]["gsd_source"] == "RECORDED_GEOMETRY"
            assert scale[side]["gsd_source_detail"] in ("TEST_FIXTURE_OVERRIDE", "NOMINAL")
        assert body["geometry_source"] == "TEST_FIXTURE"
        assert scale["gsd_ratio_relationship"] == 1.0
        assert scale["gsd_ratio_factual_label"] in ("side_a_gsd_over_side_b", "side_b_gsd_over_side_a")


def test_m5_gsd_unknown_when_absent_from_manifest():
    from backend.app.conditions.service import ConditionEstimationService

    tmp = Path(tempfile.mkdtemp(prefix="cs_m5_gsd_"))
    from backend.app.config import Settings

    settings = Settings(data_root=str(tmp), _env_file=None)
    svc = ConditionEstimationService(settings)
    run_dir = tmp / "derived" / "processing" / "CS-P099" / "PC-M2-001"
    run_dir.mkdir(parents=True, exist_ok=True)  # no manifest written here
    ga, gb = svc._gsd_facts(run_dir, "ohrc", "tmc2")
    assert ga["gsd_m"] is None and ga["gsd_source"] == "UNKNOWN"
    assert gb["gsd_m"] is None and gb["gsd_source"] == "UNKNOWN"


def test_m5_native_vs_effective_scale_recorded(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        ia = body["intrinsic_image_condition"]["side_a"]["established_facts"]
        assert ia["native_dimensions"] == ia["effective_processing_dimensions"]
        assert ia["resampling_applied"] is False
        gap = body["pair_comparison"]["scale"]["native_scale_gap"]
        assert gap["absolute_pixel_ratio"] >= 1.0
        assert gap["native_vs_effective"]["resampling_applied"] is False


def test_m5_gsd_fallback_config():
    cfg = _cfg()
    assert cfg.gsd_fallback == "UNKNOWN"
    params = copy.deepcopy(cfg.parameters)
    params["scale"]["gsd"]["fallback"] = "UNKNOWN"
    assert params["scale"]["gsd"]["enabled"] is True


# ---------------------------------------------------------------------------
# 6. reliability & separation
# ---------------------------------------------------------------------------

def test_m5_no_matcher_selection_fields(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        text = json.dumps(body).lower()
        for bad in ("selected_matcher", "recommended_matcher", "best_matcher", "routing_decision", "\"confidence\""):
            assert bad not in text, f"forbidden field leaked: {bad}"
        caps_text = json.dumps(client.get("/api/matching/conditions/capabilities").json()).lower()
        for bad in ("selected_matcher", "recommended_matcher", "best_matcher", "routing_decision"):
            assert bad not in caps_text, f"forbidden field leaked in capabilities: {bad}"


def test_m5_matcher_observations_separate_section(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        before = _pair_run(client, settings, pair_id)
        assert before["matcher_derived_observations"] is None

        bl = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": "sift"})
        assert bl.status_code == 200, bl.text
        assert bl.json()["status"] == "SUCCESS"

        after = _pair_run(client, settings, pair_id)
        obs = after["matcher_derived_observations"]
        assert obs is not None
        assert obs["source"] == "M3_BASELINE_OBSERVATION"
        assert obs["baseline_configuration"] == "MB-M3-001"
        assert obs["latest_baseline_run_id"] == bl.json()["run_id"]
        # intrinsic estimates are untouched by the observation section
        assert after["intrinsic_image_condition"]["side_a"]["texture"]["laplacian_variance"] == before["intrinsic_image_condition"]["side_a"]["texture"]["laplacian_variance"]


def test_m5_classification_explicit_thresholds(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        assert body["estimated"]["scientifically_tuned"] is False
        side = body["intrinsic_image_condition"]["side_a"]
        cls_t = side["classification"]["textural_complexity"]
        assert {"bin", "metric", "thresholds", "value"} <= set(cls_t)
        assert {"low_lt", "high_ge"} <= set(cls_t["thresholds"])
        assert cls_t["bin"] in ("LOW", "MEDIUM", "HIGH", "UNKNOWN")
        assert side["classification"]["note"]


# ---------------------------------------------------------------------------
# 7. gates & blocked outcomes
# ---------------------------------------------------------------------------

def test_m5_processing_not_run(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        body = _pair_run(client, settings, pair_id)
        assert body["status"] == "BLOCKED"
        assert body["error_code"] == "PROCESSING_NOT_RUN"


def test_m5_product_missing(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        from backend.app.processing.service import ProcessingService

        run_dir = ProcessingService(settings).find_run_for_pair(pair_id)
        display = run_dir / "ohrc" / "preprocessed_display_u16.npy"
        assert display.is_file()
        display.unlink()
        body = _pair_run(client, settings, pair_id)
        assert body["status"] == "BLOCKED"
        assert body["error_code"] == "PRODUCT_MISSING"
        assert "OHRC" in body["error_detail"] or "side A" in body["error_detail"]


def test_m5_real_shaped_pair_shares_the_same_gates(tmp_path, authed_client_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app
    from auth_helpers import authed_client_for_app

    fixturegen.write_real_shaped_pair(tmp_path)
    settings = Settings(data_root=str(tmp_path), _env_file=None,
                        auth_secret_key=AUTH_TEST_SECRET,
                        auth_bootstrap_admin_username="test-admin",
                        auth_bootstrap_admin_password="Admin-1234-test!")
    ensure_derived_directories(settings)
    client = authed_client_for_app(create_app(settings=settings))
    with client:
        resp = client.post("/api/pairs/auto-register", json={})
        assert resp.status_code == 200, resp.text
        pair_id = resp.json()["pair_id"]
        run = client.post(f"/api/pairs/{pair_id}/conditions/run")
        assert run.status_code == 200, run.text
        assert run.json()["status"] == "BLOCKED"
        assert run.json()["error_code"] == "PROCESSING_NOT_RUN"


def test_m5_fixture_artifacts_are_labelled_synthetic(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        assert body["status"] == "SUCCESS"
        assert body["synthetically_derived"] is True
        assert body["source_gate"]["data_source_gate"] == "PATH_B_SYNTHETIC_ONLY"
        assert body["source_gate"]["source_class_a"] == "TEST_FIXTURE"
        text = json.dumps(body)
        assert '"REAL_PRADAN"' not in text


# ---------------------------------------------------------------------------
# 8. artifact persistence + provenance
# ---------------------------------------------------------------------------

def test_m5_artifact_persistence_no_absolute_paths(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        art = settings.data_root_path / "metadata" / "m5_condition" / f"{body['run_id']}.json"
        assert art.is_file()
        stored = json.loads(art.read_text(encoding="utf-8"))
        assert stored["run_id"] == body["run_id"]
        assert stored["configuration_id"] == "CE-M5-001"
        assert stored["configuration"]["parameters"]["sampling"]["seed"] == 20260922
        assert stored["environment"]["numpy_version"]
        text = json.dumps(stored)
        assert "C:\\\\" not in text and ":///" not in text
        assert str(settings.data_root_path) not in text
        # relative product references only
        assert str(stored["processing"]["processing_run_rel"]).startswith("derived/processing/")
        assert str(stored["intrinsic_image_condition"]["side_a"]["established_facts"]["product"]["display_rel"]).startswith("derived/")


def test_m5_write_artifact_refuses_overwrite(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    from backend.app.conditions.service import ConditionEstimationService

    svc = ConditionEstimationService(settings)
    safe_payload = {
        "run_id": "ce-tmp",
        "status": "BLOCKED",
        "configuration_id": "CE-M5-001",
        "intrinsic_image_condition": None,
        "pair_comparison": None,
        "matcher_derived_observations": None,
        "estimated": None,
    }
    svc.write_artifact("ce-tmp", safe_payload)
    with pytest.raises(OSError):
        svc.write_artifact("ce-tmp", safe_payload)


# ---------------------------------------------------------------------------
# 9. API surface
# ---------------------------------------------------------------------------

def test_m5_api_capabilities(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        caps = client.get("/api/matching/conditions/capabilities").json()
        assert caps["condition_estimator_configuration_id"] == "CE-M5-001"
        assert caps["data_gate"]["code"] == "REAL_DATA_BLOCKED"
        assert caps["data_gate"]["real_data_available"] is False
        assert "never selects" in caps["note"]


def test_m5_api_run_status_runs_read(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = _pair_run(client, settings, pair_id)
        assert body["status"] == "SUCCESS"

        st = client.get(f"/api/pairs/{pair_id}/conditions/status").json()
        assert st["has_run"] is True
        assert st["latest_run"]["run_id"] == body["run_id"]
        assert st["latest_run"]["levels"]["side_a"]["textural_complexity"] in ("LOW", "MEDIUM", "HIGH", "UNKNOWN")

        runs = client.get(f"/api/pairs/{pair_id}/conditions/runs").json()
        assert runs["runs"][0]["run_id"] == body["run_id"]

        rd = client.get(f"/api/conditions/runs/{body['run_id']}").json()
        assert rd["run_id"] == body["run_id"]
        assert rd["pair_comparison"]["appearance"]["histogram_distance_chi_square"] is not None

        missing = client.get("/api/conditions/runs/ce-does-not-exist")
        assert missing.status_code == 404


def test_m5_api_auth_required(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    from backend.app.config import Settings
    from backend.app.main import create_app
    from fastapi.testclient import TestClient

    settings = Settings(data_root=str(tmp_path), _env_file=None, auth_secret_key=AUTH_TEST_SECRET)
    bare = TestClient(create_app(settings=settings))
    with bare:
        assert bare.get("/api/matching/conditions/capabilities").status_code == 401
        assert bare.post("/api/pairs/CS-P001/conditions/run").status_code == 401
        assert bare.get("/api/pairs/CS-P001/conditions/status").status_code == 401
        assert bare.get("/api/pairs/CS-P001/conditions/runs").status_code == 401
        assert bare.get("/api/conditions/runs/ce-x").status_code == 401


def test_m5_unregistered_pair_404(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        assert client.post("/api/pairs/CS-ZZZ/conditions/run").status_code == 404


def test_m5_blocked_payload_persisted_honestly(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        body = _pair_run(client, settings, pair_id)
        art = settings.data_root_path / "metadata" / "m5_condition" / f"{body['run_id']}.json"
        assert art.is_file()
        assert body["intrinsic_image_condition"] is None
        assert body["pair_comparison"] is None


# ---------------------------------------------------------------------------
# 10. M1 / M2 regression (this milestone must not weaken them)
# ---------------------------------------------------------------------------

def test_m5_regression_raw_files_never_modified(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    raw_a = settings.data_root_path / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    raw_b = settings.data_root_path / "raw" / "tmc2" / "ch2_tmc_ncn_20200207T0716469418_d_img_d18.img"
    before = (raw_a.read_bytes().hex(), raw_b.read_bytes().hex())
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        _pair_run(client, settings, pair_id)
    assert (raw_a.read_bytes().hex(), raw_b.read_bytes().hex()) == before


def test_m5_regression_m2_products_present_after_prepare(authed_client_factory, tmp_path):
    client, settings, _ = _harness(tmp_path, authed_client_factory)
    with client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        from backend.app.processing.service import ProcessingService

        status = ProcessingService(settings).read_status(pair_id)
        assert status["state"] == "READY_FOR_MATCHING"
        assert set(status["products"].keys()) == {"a", "b"}
        for side in ("a", "b"):
            assert status["products"][side]["display_rel"].endswith("preprocessed_display_u16.npy")
            assert status["products"][side]["mask_rel"].endswith("invalid_mask_u8.npy")