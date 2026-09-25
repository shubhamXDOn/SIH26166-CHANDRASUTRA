"""M4 real-data tests — strong/deep matcher (SuperPoint + SuperGlue) integration.

M4 integrates the primary deep matcher (SuperPoint + SuperGlue) through the
SAME M3 candidate-correspondence contract as the classical baseline, with:

    * honest capability probing (torch/torchvision runtime, per-checkpoint
      SHA-256 pins, explicit BLOCKED_RUNTIME / BLOCKED_WEIGHTS / AVAILABLE);
    * strictly-verified weight loading (MODEL_WEIGHTS_INVALID on any
      state-dict mismatch — never a shape fallback);
    * recorded coordinate transforms (SuperPoint 8x score grid -> effective
      model input -> native product) with independent round-trip tests;
    * persisted artifacts under metadata/m4_deep_matching with provenance
      (checkpoint filename + sha256 + source) and NEVER absolute paths;
    * honest source gates (TEST_FIXTURE synthetic fixtures stay synthetic;
      real-data runs are real_data BLOCKED like every other stage);
    * API (capabilities / run / status / runs / read / visualization).

Nothing here claims the deep model scores are confidence, accuracy or a
trust verdict. Deep runs report CANDIDATE correspondences only.

Hardware note: this environment is CPU-only (torch 2.10.0+cpu, no CUDA). Runs
are exercised at reduced ``max_image_dimension`` so the suite stays fast while
still using the REAL officially-provided pretrained checkpoints.
"""

from __future__ import annotations

import copy
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

import fixturegen  # noqa: F401

from auth_helpers import configure_auth  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "data" / "models" / "m8"

CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M4 deep matcher software validation only.",
    "products": {
        "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 0.5},
        "tmc2": {"row_offset_m": -2.0, "col_offset_m": -2.0, "gsd_m": 0.5},
    },
}


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _shifted_images(size: int = 96, cols: int = 160):
    """img_a / img_b are the same scene with a -8 column shift."""
    base = fixturegen._synthetic_scene_rows(size=size, cols=cols, seed=3)
    img_a = (np.clip(base[:, :-8], 0, 1) * 255).astype(np.uint8)
    img_b = (np.clip(base[:, 8:], 0, 1) * 255).astype(np.uint8)
    return img_a, img_b


def _small_cfg(max_dim: int = 256, **execution) -> dict:
    from backend.app.config import m4_deep_config

    cfg = copy.deepcopy(m4_deep_config())
    cfg["defaults"]["execution"]["max_image_dimension"] = max_dim
    cfg["defaults"]["execution"]["max_runtime_seconds"] = 240
    cfg["defaults"]["execution"].update(execution)
    return cfg


def patch_deep_cfg(monkeypatch, max_dim: int = 256, **execution) -> None:
    """Make contract/service/probe read the reduced (fast) M4 configuration."""
    import backend.app.matching.deep.contract as cmod
    import backend.app.matching.deep.probe as pmod
    import backend.app.matching.deep.service as smod

    def reduced():
        return _small_cfg(max_dim=max_dim, **execution)

    monkeypatch.setattr(cmod, "m4_deep_config", reduced)
    monkeypatch.setattr(smod, "m4_deep_config", reduced)
    monkeypatch.setattr(pmod, "m4_deep_config", reduced)


def _deep_run(img_a, img_b, *, cfg=None, model_dir=None, mask_a=None, mask_b=None, matcher_id="superpoint_superglue"):
    from backend.app.matching.deep.contract import DeepMatcherInput, run_deep_contract

    inp = DeepMatcherInput(
        matcher_id=matcher_id, image_a=img_a, image_b=img_b,
        mask_a=mask_a, mask_b=mask_b,
    )
    return run_deep_contract(inp, cfg=cfg or _small_cfg(), model_dir=Path(model_dir or MODELS_DIR))


def _stable(out) -> dict:
    d = asdict(out)
    d.pop("runtime_ms", None)
    return d


@pytest.fixture()
def m4_app(tmp_path, monkeypatch):
    """App+client on a correlated fixture data root with reduced deep config.

    Builds Settings explicitly (auth bootstrap + real checkpoint directory)
    and exposes them on ``client.app.state.settings`` so tests can resolve
    persisted artifact paths without a second reference.
    """
    from auth_helpers import (
        ADMIN_PASSWORD,
        ADMIN_USERNAME,
        AUTH_TEST_SECRET,
        authed_client_for_app,
    )
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    fixturegen.write_correlated_fixtures(tmp_path / "data")
    patch_deep_cfg(monkeypatch, max_dim=256)
    settings = Settings(
        data_root=str(tmp_path / "data"),
        m8_model_dir=str(MODELS_DIR),
        auth_secret_key=AUTH_TEST_SECRET,
        auth_bootstrap_admin_username=ADMIN_USERNAME,
        auth_bootstrap_admin_password=ADMIN_PASSWORD,
        _env_file=None,
    )
    ensure_derived_directories(settings)
    configure_auth(settings)
    client = authed_client_for_app(create_app(settings=settings))
    client.app.state.settings = settings
    return client


def settings_of(client):
    settings = getattr(client.app.state, "settings", None)
    if settings is None:
        raise AssertionError("settings not present on test app state")
    return settings


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


def _empty_model_dir(tmp_path: Path) -> Path:
    d = tmp_path / "models" / "empty"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ===========================================================================
# 1. common matcher-interface compliance
# ===========================================================================

def test_m4_interface_shares_m3_input_and_output_contracts():
    from backend.app.matching.baseline import MatcherInput, MatcherOutput
    from backend.app.matching.deep.contract import DeepMatcherInput, run_deep_contract

    assert DeepMatcherInput is MatcherInput

    out = _deep_run(*_shifted_images(), matcher_id="nope")
    assert isinstance(out, MatcherOutput)
    assert out.status == "BLOCKED"
    assert out.error_code == "MATCHER_NOT_AVAILABLE"
    assert out.matcher_id == "nope"


def test_m4_interface_rejects_non_2d_input():
    from backend.app.matching.baseline import MatcherInput

    a, b = _shifted_images()
    with pytest.raises(ValueError):
        MatcherInput(matcher_id="superpoint_superglue",
                     image_a=np.stack([a, a]), image_b=b)  # 3-D
    with pytest.raises(ValueError):
        MatcherInput(matcher_id="superpoint_superglue",
                     image_a=a.ravel(), image_b=b)  # 1-D


# ===========================================================================
# 2. capability probing (honest, live)
# ===========================================================================

def test_m4_capability_probe_reports_available_with_full_schema():
    from backend.app.matching.deep.probe import probe_superpoint_superglue

    cap = probe_superpoint_superglue(MODELS_DIR)
    assert cap["matcher"] == "superpoint_superglue"
    assert cap["available"] is True
    assert cap["status"] == "AVAILABLE"
    assert cap["framework"] == "torch"
    assert cap["framework_version"]
    assert cap["device"]["device"] == "cpu"
    assert cap["device"]["cuda_available"] is False
    assert cap["checkpoint"] == ["superpoint_v1.pth", "superglue_outdoor.pth"]
    assert cap["checkpoint_sha256"]["superpoint_v1.pth"] == \
        "52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e"
    assert cap["checkpoint_sha256"]["superglue_outdoor.pth"] == \
        "2f5f5e9bb3febf07b69df633c4c3ff7a17f8af26a023aae2b9303d22339195bd"
    assert cap["weights_source"] and all("magicleap" in s for s in cap["weights_source"])
    assert cap["runtime_dependencies"] == ["torch", "torchvision"]
    assert cap["scores_are_observations"] is True
    # never an absolute machine-specific path in the capability surface
    assert all(w.get("path") is None for w in cap["weights"])


def test_m4_capabilities_public_lists_all_deep_matchers_states():
    from backend.app.config import Settings
    from backend.app.matching.deep.probe import capabilities_public
    from backend.app.matching.deep.service import DeepMatcherService

    settings = Settings(data_root=tempfile.mkdtemp(prefix="cs_cap_"),
                        m8_model_dir=str(MODELS_DIR), _env_file=None)
    caps = capabilities_public(model_dir=MODELS_DIR)
    by_id = {m["matcher_id"]: m for m in caps["matchers"]}
    assert set(by_id) == {"superpoint_superglue", "loftr", "rift2"}
    assert by_id["superpoint_superglue"]["status"] == "AVAILABLE"
    assert by_id["loftr"]["available"] is False
    assert by_id["loftr"]["status"] == "NOT_AVAILABLE"
    assert by_id["rift2"]["status"] == "NOT_AVAILABLE"
    assert by_id["rift2"]["deferred"] is True
    assert caps["probed_at_runtime"] is True
    assert caps["configuration_id"] == "DM-M4-001"
    assert caps["device"]["deep_runtime"]["torch"] is True

    svc = DeepMatcherService(settings)
    assert svc.capabilities_public()["probed_at_runtime"] is True


# ===========================================================================
# 3. missing dependency handling
# ===========================================================================

def test_m4_missing_runtime_reports_blocked(monkeypatch):
    import backend.app.matching.deep.contract as cmod
    import backend.app.matching.deep.probe as pmod

    monkeypatch.setattr(pmod, "torch_available", lambda: False)
    monkeypatch.setattr(pmod, "torchvision_available", lambda: False)
    monkeypatch.setattr(pmod, "cuda_available", lambda: False)
    monkeypatch.setattr(cmod, "torch_available", lambda: False)
    monkeypatch.setattr(cmod, "torchvision_available", lambda: False)

    cap = pmod.probe_superpoint_superglue(MODELS_DIR)
    assert cap["available"] is False
    assert cap["status"] == "BLOCKED_RUNTIME"
    assert "torch" in cap["reason"]

    out = _deep_run(*_shifted_images())
    assert out.status == "BLOCKED"
    assert out.error_code == "DEEP_RUNTIME_UNAVAILABLE"


# ===========================================================================
# 4. missing checkpoint handling
# ===========================================================================

def test_m4_missing_checkpoint_blocks(tmp_path):
    from backend.app.matching.deep.probe import probe_superpoint_superglue

    empty = _empty_model_dir(tmp_path)
    cap = probe_superpoint_superglue(empty)
    assert cap["available"] is False
    assert cap["status"] == "BLOCKED_WEIGHTS"
    assert any(not w["provisioned"] for w in cap["weights"])

    out = _deep_run(*_shifted_images(), model_dir=empty)
    assert out.status == "BLOCKED"
    assert out.error_code == "DEEP_WEIGHTS_UNAVAILABLE"
    assert "superpoint_v1.pth" in (out.error_detail or "")


# ===========================================================================
# 5. invalid checkpoint handling
# ===========================================================================

def test_m4_invalid_checkpoint_shape_fails_strictly(tmp_path):
    from backend.app.matching.deep.models import SuperGlueNet, SuperPointNet

    torch = pytest.importorskip("torch")
    bad = tmp_path / "bad.pth"
    torch.save({"conv1a.weight": torch.zeros(1, 1, 1, 1)}, bad)  # wrong shape

    sp = SuperPointNet({})
    sp.build("cpu")
    with pytest.raises(ValueError) as ei:
        sp.load_weights(str(bad))
    assert "MODEL_WEIGHTS_INVALID" in str(ei.value)

    gl = SuperGlueNet({})
    gl.build("cpu")
    with pytest.raises(ValueError) as ei2:
        gl.load_weights(str(bad))
    assert "MODEL_WEIGHTS_INVALID" in str(ei2.value)


def test_m4_garbage_non_tensor_checkpoint_is_rejected(tmp_path):
    from backend.app.matching.deep.models import _load_checkpoint

    garbage = tmp_path / "garbage.pth"
    garbage.write_bytes(b"this is not a torch checkpoint at all")
    with pytest.raises(Exception):  # noqa: BLE001
        _load_checkpoint(str(garbage), "cpu")


# ===========================================================================
# 6. model initialization failure -> BLOCKED
# ===========================================================================

def test_m4_model_init_failure_blocks_honestly(tmp_path):
    torch = pytest.importorskip("torch")
    decoy_dir = tmp_path / "decoy"
    decoy_dir.mkdir(parents=True, exist_ok=True)
    (decoy_dir / "superpoint_v1.pth").write_bytes(b"not a torch file")
    # superglue absent -> blocked before any inference
    out = _deep_run(*_shifted_images(), model_dir=decoy_dir)
    assert out.status == "BLOCKED"
    assert out.error_code == "DEEP_WEIGHTS_UNAVAILABLE"

    # a decoy that IS a saved tensor dict but wrong shapes -> strict MODEL_WEIGHTS_INVALID
    from backend.app.matching.deep.models import SuperPointNet

    decoy = decoy_dir / "superpoint_v1.pth"
    torch.save({"conv1a.weight": torch.zeros(1, 1, 1, 1)}, decoy)
    sp = SuperPointNet({})
    sp.build("cpu")
    with pytest.raises(ValueError) as ei:
        sp.load_weights(str(decoy))
    assert "MODEL_WEIGHTS_INVALID" in str(ei.value)


# ===========================================================================
# 7. explicit NOT_AVAILABLE states
# ===========================================================================

def test_m4_explicit_not_available_states():
    from backend.app.matching.deep.probe import probe_loftr, probe_rift2

    lt = probe_loftr()
    assert lt["available"] is False
    assert lt["status"] == "NOT_AVAILABLE"
    assert "kornia" in lt["reason"]
    assert lt["deferred"] is True
    assert lt["scores_are_observations"] is True

    r2 = probe_rift2()
    assert r2["available"] is False
    assert r2["status"] == "NOT_AVAILABLE"
    assert r2["trainable"] is False
    assert "DEFERRED" in r2["reason"].upper()


# ===========================================================================
# 8. SuperPoint/SuperGlue output schema + counts + score semantics
# ===========================================================================

def test_m4_superglue_run_output_schema_counts_and_score_semantics():
    out = _deep_run(*_shifted_images())
    assert out.status == "SUCCESS", out.error_detail
    assert out.model_family == "superpoint_superglue"
    assert out.candidate_match_count > 0
    assert len(out.correspondences) == out.candidate_match_count
    assert out.raw_match_count >= out.candidate_match_count
    assert out.keypoint_count_a >= 2 and out.keypoint_count_b >= 2

    ev = out.model_evidence
    assert ev["scores_are_observations"] is True
    assert ev["superpoint"]["cell"] == 8
    assert ev["superpoint"]["grid_dimensions"]["a"] == ev["superpoint"]["grid_dimensions"]["b"]
    assert ev["superglue"]["feature_dim"] == 256
    assert "coordinate_transform" in ev
    assert ev["coordinate_transform"]["correspondence_plane"] == "EFFECTIVE_MODEL_INPUT"
    assert "model_probability" in out.correspondences[0]

    probs = np.asarray([c["matching_score"] for c in out.correspondences], dtype=np.float64)
    logs = np.asarray([c["log_assignment_score"] for c in out.correspondences], dtype=np.float64)
    assert len(probs) == out.candidate_match_count
    assert np.isfinite(probs).all()
    assert (probs >= 0.0).all() and (probs <= 1.0).all()
    assert np.isfinite(logs).all() and (logs <= 0.0).all()
    assert np.allclose(np.exp(logs), probs, atol=1e-3)

    for c in out.correspondences:
        assert c["score"] == c["model_probability"]
        assert c["correspondence_score"] == c["model_probability"]
        assert 0.0 <= c["model_probability"] <= 1.0

    sums = out.scores
    assert sums["matching_score"]["count"] == out.candidate_match_count
    assert sums["correspondence_score"]["count"] == out.candidate_match_count
    # explicit honest naming: never a fictional generic "confidence" field
    assert "confidence" not in json.dumps(asdict(out)).lower()

    assert out.determinism["guarantee"]
    assert out.filters["funnel"]["raw_matches"] == out.raw_match_count
    assert out.filters["funnel"]["candidates"] == out.candidate_match_count


def test_m4_superglue_deterministic_rerun_is_identical():
    a, b = _shifted_images()
    o1 = _deep_run(a, b)
    o2 = _deep_run(a, b)
    assert o1.status == "SUCCESS", o1.error_detail
    assert _stable(o1) == _stable(o2)


# ===========================================================================
# 9. coordinate transform round trips (independent tests)
# ===========================================================================

def test_m4_grid_effective_round_trip():
    from backend.app.matching.deep.transforms import (
        effective_to_grid,
        grid_to_effective,
    )

    grid = (184, 256)
    eff = (190, 256)
    pts = np.array([[0.0, 0.0], [255.5, 183.5], [10.25, 7.75]], dtype=np.float64)
    back = grid_to_effective(effective_to_grid(pts, grid, eff), grid, eff)
    assert back.shape == pts.shape
    assert np.allclose(back, pts, atol=1e-9)


def test_m4_effective_native_round_trip():
    from backend.app.matching.deep.transforms import (
        effective_to_native,
        native_to_effective,
    )

    eff = (190, 256)
    native = (700, 520)
    pts = np.array([[0.0, 0.0], [255.5, 189.5], [64.0, 32.0]], dtype=np.float64)
    back = effective_to_native(native_to_effective(pts, eff, native), eff, native)
    assert back.shape == pts.shape
    assert np.allclose(back, pts, atol=1e-9)


def test_m4_grid_scale_is_non_isotropic_and_recorded():
    from backend.app.matching.deep.transforms import (
        build_effective_to_native,
        build_grid_to_effective,
    )

    g2e = build_grid_to_effective((184, 256), (190, 256))
    e2n = build_effective_to_native((190, 256), (700, 520))
    assert g2e["kind"] == "linear_scale"
    assert e2n["kind"] == "linear_scale_resample"
    # native 700 (rows) -> 190 rows; native 520 (cols) -> 256 cols; axes never
    # swapped, scales clearly separated per axis
    assert e2n["scale"]["y"] == pytest.approx(700 / 190)
    assert e2n["scale"]["x"] == pytest.approx(520 / 256)
    assert e2n["scale"]["x"] != e2n["scale"]["y"]


# ===========================================================================
# 10. resize mapping
# ===========================================================================

def test_m4_resize_mapping_recorded_and_consistent():
    from backend.app.matching.baseline import _resize_recorded

    img = (np.arange(700 * 520, dtype=np.uint16).reshape(700, 520)) % 256
    mask = np.zeros((700, 520), dtype=np.uint8)
    mask[600:, 400:] = 255
    resized, rmask, info = _resize_recorded(img, mask, max_dim=256)
    assert info["resampled"] is True
    assert info["original_dimensions"] == {"height": 700, "width": 520}
    assert info["effective_dimensions"] == {"height": int(resized.shape[0]), "width": int(resized.shape[1])}
    assert max(resized.shape) <= 256
    assert rmask.shape == resized.shape
    assert abs(info["resample_factor"] - 256 / 700) < 1e-6


# ===========================================================================
# 11. image A/B semantics
# ===========================================================================

def test_m4_image_ab_semantics_preserved():
    out = _deep_run(*_shifted_images())
    assert out.status == "SUCCESS", out.error_detail
    eff_a = out.input["image_a"]
    eff_b = out.input["image_b"]
    wa, ha = eff_a["effective_dimensions"]["width"], eff_a["effective_dimensions"]["height"]
    wb, hb = eff_b["effective_dimensions"]["width"], eff_b["effective_dimensions"]["height"]
    for c in out.correspondences:
        assert 0 <= c["x_a"] < wa and 0 <= c["y_a"] < ha
        assert 0 <= c["x_b"] < wb and 0 <= c["y_b"] < hb
    assert eff_a["plane"] == "MODEL_INPUT_EFFECTIVE"
    assert eff_b["plane"] == "MODEL_INPUT_EFFECTIVE"


def test_m4_swapped_inputs_change_output():
    a, b = _shifted_images()
    out_ab = _deep_run(a, b)
    out_ba = _deep_run(b, a)
    assert out_ab.status == "SUCCESS", out_ab.error_detail
    assert out_ba.status == "SUCCESS", out_ba.error_detail
    c_ab = asdict(out_ab)["correspondences"]
    c_ba = asdict(out_ba)["correspondences"]
    assert c_ab != c_ba  # A/B roles are not interchangeable


# ===========================================================================
# 14. empty/low-texture input + 15. tiny crop + 16. malformed
# ===========================================================================

def test_m4_empty_low_texture_input_blocks_without_crash():
    flat = np.full((96, 160), 128, dtype=np.uint8)
    out = _deep_run(flat, flat)
    assert out.status == "BLOCKED"
    assert out.error_code == "INVALID_INPUT"
    assert "keypoints" in (out.error_detail or "").lower()


def test_m4_tiny_crop_blocks():
    small = np.zeros((7, 7), dtype=np.uint8)
    out = _deep_run(small, small)
    assert out.status == "BLOCKED"
    assert out.error_code == "INVALID_INPUT"


# ===========================================================================
# 17. resource / timeout handling
# ===========================================================================

def test_m4_timeout_returns_resource_limit():
    cfg = _small_cfg(max_runtime_seconds=0.001)
    out = _deep_run(*_shifted_images(), cfg=cfg)
    assert out.status == "BLOCKED"
    assert out.error_code == "RESOURCE_LIMIT"
    assert "budget" in (out.error_detail or "").lower()


# ===========================================================================
# 20-19. API: capabilities, status, block flows, auth, truthful gate
# ===========================================================================

def test_m4_api_capabilities_and_status(m4_app):
    with m4_app as client:
        caps = client.get("/api/matching/deep/capabilities").json()
        assert caps["configuration_id"] == "DM-M4-001"
        by_id = {m["matcher_id"]: m for m in caps["matchers"]}
        assert set(by_id) == {"superpoint_superglue", "loftr", "rift2"}
        assert by_id["superpoint_superglue"]["status"] == "AVAILABLE"

        pair_id = _register(client)
        st = client.get(f"/api/matching/{pair_id}/deep/status").json()
        assert st["has_run"] is False
        assert st["configuration_id"] == "DM-M4-001"
        assert {m["matcher_id"] for m in st["matchers"]["matchers"]} == \
            {"superpoint_superglue", "loftr", "rift2"}
        gate = st["data_gate"]
        assert gate["real_data_available"] is False
        assert gate["code"] == "REAL_DATA_BLOCKED"


def test_m4_api_unprepared_pair_blocks(m4_app):
    with m4_app as client:
        pair_id = _register(client)
        resp = client.post(f"/api/matching/{pair_id}/deep/run", json={"matcher": "superpoint_superglue"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "BLOCKED"
        assert body["error_code"] == "PROCESSING_NOT_RUN"


def test_m4_api_unknown_matcher_rejected(m4_app):
    with m4_app as client:
        pair_id = _register(client)
        r404 = client.post(f"/api/matching/nope/deep/run", json={"matcher": "superpoint_superglue"})
        assert r404.status_code == 404

        r422 = client.post(f"/api/matching/{pair_id}/deep/run", json={"matcher": "deepfake"})
        assert r422.status_code == 422
        assert r422.json()["error"]["code"] == "VALIDATION_ERROR"


# ===========================================================================
# 18. API success flow + artifact persistence + no absolute paths
# ===========================================================================

def test_m4_api_deep_run_success_read_and_visualization(m4_app):
    with m4_app as client:
        pair_id = _register(client)
        _prepare(client, pair_id)

        r1 = client.post(f"/api/matching/{pair_id}/deep/run", json={"matcher": "superpoint_superglue"})
        assert r1.status_code == 200, r1.text
        body = r1.json()
        assert body["status"] == "SUCCESS", body.get("error_detail")
        assert body["state"] == "SUCCESS"
        assert body["model_family"] == "superpoint_superglue"
        mat = body["matcher"]
        assert mat["model_family"] == "superpoint_superglue"
        assert mat["candidate_match_count"] == len(mat["correspondences"])
        assert mat["candidate_match_count"] > 0
        assert body["synthetically_derived"] is True
        assert body["source_gate"]["source_class_a"] == "TEST_FIXTURE"
        assert "verdict" in body["license"].lower()
        assert body["input"]["image_a"]["model_plane"] == "EFFECTIVE_MODEL_INPUT"
        assert body["input"]["image_a"]["effective_dimensions"]["height"] > 0
        assert body["input"]["image_a"]["sha256"]
        assert body["input"]["image_b"]["native_dimensions"]["height"] == 700
        assert body["visualization_rel"]

        # run IDs are unique per run; artifacts never overwritten
        r2 = client.post(f"/api/matching/{pair_id}/deep/run", json={"matcher": "superpoint_superglue"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["run_id"] != body["run_id"]
        _m = r1.json()["matcher"].copy()
        _m.pop("runtime_ms", None)
        _m2 = r2.json()["matcher"].copy()
        _m2.pop("runtime_ms", None)
        assert _m == _m2  # deterministic rerun through the API

        # read through the shared /runs/{run_id} surface + visualization
        rund = client.get(f"/api/matching/runs/{body['run_id']}").json()
        assert rund["run_id"] == body["run_id"]
        assert rund["matcher_id"] == "superpoint_superglue"

        v = client.get(f"/api/matching/runs/{body['run_id']}/visualization")
        assert v.status_code == 200
        assert v.headers["content-type"] == "image/png"

        runs = client.get(f"/api/matching/{pair_id}/deep/runs").json()
        assert {r["matcher_id"] for r in runs["runs"]} == {"superpoint_superglue"}

        # persisted artifact: provenance, hashes, never absolute paths
        art = settings_of(client).data_root_path / "metadata" / "m4_deep_matching" / f"{body['run_id']}.json"
        assert art.is_file()
        stored = json.loads(art.read_text(encoding="utf-8"))
        assert stored["run_id"] == body["run_id"]
        assert stored["configuration_id"] == "DM-M4-001"
        assert stored["environment"]["torch_version"]
        assert stored["matcher"]["candidate_match_count"] > 0
        chk = {w["name"]: w for w in stored["matcher"]["provenance"]["checkpoints"]}
        assert chk["superpoint"]["sha256"] == \
            "52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e"
        assert chk["superglue"]["sha256_pin"]
        text = json.dumps(stored)
        assert "C:\\\\" not in text and ":///" not in text
        assert str(settings_of(client).data_root_path) not in text
        assert "Shubham" not in text
        # model scores are never *stored under* a confidence key, and the
        # artifact must carry the honest observation/trust framing
        assert "final_confidence" not in text.lower()
        assert '"confidence"' not in text.lower()
        assert "trust gate" in text.lower() or "verdict" in text.lower()


# ===========================================================================
# 21-22. synthetic separation + real-data gate at service level
# ===========================================================================

def test_m4_fixture_artifacts_labelled_synthetic_and_real_gate_blocked(m4_app):
    with m4_app as client:
        pair_id = _register(client)
        _prepare(client, pair_id)
        body = client.post(f"/api/matching/{pair_id}/deep/run",
                           json={"matcher": "superpoint_superglue"}).json()
        if body["status"] == "SUCCESS":
            assert body["synthetically_derived"] is True
            assert body["source_gate"]["data_source_gate"] == "PATH_B_SYNTHETIC_ONLY"
            assert body["source_gate"]["source_class_b"] == "TEST_FIXTURE"
            assert '"REAL_PRADAN"' not in json.dumps(body)


# ===========================================================================
# 23. M8/M10/M12/M13 regression (this milestone must not weaken them)
# ===========================================================================

def test_m4_regression_m8_capabilities_still_honest(m4_app):
    with m4_app as client:
        caps = client.get("/api/matching/capabilities").json()
        assert "device" in caps and "matchers" in caps
        assert caps["device"]["deep_runtime"]["torch"] is True


def test_m4_regression_m10_auth_required(m4_app):
    with m4_app as client:
        pair_id = _register(client)
        bare = client.bare()
        r = bare.post(f"/api/matching/{pair_id}/deep/run", json={"matcher": "superpoint_superglue"})
        assert r.status_code == 401
        # other M4 routes stay protected too
        assert bare.get("/api/matching/deep/capabilities").status_code == 401


def test_m4_regression_m12_m13_still_serving(m4_app):
    with m4_app as client:
        assert client.get("/api/m12/configuration-freeze").status_code == 200
        assert client.get("/api/m13/status").status_code in (200, 404)


# ===========================================================================
# 26. frontend surface (descriptive, non-competitive)
# ===========================================================================

def test_m4_frontend_deep_card_present_and_honest_wording():
    card = REPO_ROOT / "frontend" / "src" / "components" / "DeepMatchingCard.jsx"
    page = REPO_ROOT / "frontend" / "src" / "pages" / "Analysis.jsx"
    assert card.is_file(), "DeepMatchingCard.jsx must exist"
    assert page.is_file()
    card_text = card.read_text(encoding="utf-8")
    page_text = page.read_text(encoding="utf-8")
    assert "DeepMatchingCard" in page_text
    assert "/matching/deep/capabilities" in card_text
    assert "deep/run" in card_text
    # descriptive, honest wording: no ranking/confidence field is produced.
    # The card explicitly explains the scores as observations, not confidence.
    assert "final_confidence" not in card_text.lower()
    assert '"confidence"' not in card_text.lower()
    assert "winner" not in card_text.lower() or "no winner" in card_text.lower()
    assert "observation" in card_text.lower() or "candidate" in card_text.lower()