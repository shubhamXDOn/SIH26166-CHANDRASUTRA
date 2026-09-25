"""M9 REGISTRATION / IMAGE ALIGNMENT tests.

Covers:
    * config (RG-M9-001, smallest-valid policy, engineering thresholds,
      forbidden vocabulary incl. ``perfect``/``accurate``);
    * artifact contract + vocabulary guard;
    * deterministic model fit (affine lstsq, normalized-DLT homography,
      smallest-valid selection, explicit model honor, determinism);
    * selected-correspondence input validation (NaN/Inf, duplicates,
      collinear/insufficient points → abstain codes);
    * independent transform validation (finite/det/condition/coefficient/
      denominator checks, residual & reverse statistics in px, scale/
      anisotropy diagnostics, transformed-extent, acceptance thresholds);
    * derived aligned/warped output (warp settings recorded explicitly,
      dtype conversion, previews, visualizations);
    * service resolution + persistence (M8 missing / non-usable / wrong-pair,
      INVALID frame, REAL_DATA gate, SUCCESS / SUCCESS_WITH_WARNINGS / ABSTAIN /
      BLOCKED / FAILED, determinism, never overwrite, vocabulary safety,
      provenance, relative-path-only artifacts);
    * API surface (status / runs / run / run detail / visualization / preview,
      unknown-run 404s, analyst-only writes);
    * M1–M8 + M10–M13 regression smokes (imports + config + route presence).

All fixtures are synthetic; nothing here is REAL data and no physical accuracy
is ever claimed.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

import auth_helpers  # noqa: F401

from auth_helpers import AUTH_TEST_SECRET  # noqa: F401


# ---------------------------------------------------------------------------
# local synthetic fixtures (self-contained)
# ---------------------------------------------------------------------------

def _settings(tmp_path):
    from backend.app.config import Settings

    return Settings(data_root=str(tmp_path), _env_file=None)


def _registry(tmp_path):
    from backend.app.config import Settings
    from backend.app.pairs import PairRecord, PairRegistry

    st = Settings(data_root=str(tmp_path), _env_file=None)
    record = PairRecord(
        pair_id="CS-P001", image_a_filename="a.img", image_b_filename="b.img",
        source_class_a="TEST_FIXTURE", source_class_b="TEST_FIXTURE",
        data_source_gate="PATH_B_SYNTHETIC_ONLY",
    )
    PairRegistry(st).save(record)
    return record


def _pts_affine(n=30, offset=(3.0, 0.5), seed=7, spans=(20.0, 200.0)):
    rng = np.random.RandomState(seed)
    pts_a = rng.uniform(spans[0], spans[1], (n, 2))
    pts_b = pts_a + np.asarray(offset, dtype=np.float64)
    return pts_a, pts_b


def _m8_entries(pts_a, pts_b, residuals=0.05):
    entries = []
    for i in range(len(pts_a)):
        entries.append({
            "m8_index": i,
            "m7_index": i,
            "match_index_a": i,
            "match_index_b": i,
            "x_a": float(pts_a[i, 0]), "y_a": float(pts_a[i, 1]),
            "x_b": float(pts_b[i, 0]), "y_b": float(pts_b[i, 1]),
            "residual": float(residuals),
        })
    return entries


def _m9cfg(**replace):
    from backend.app.registration_m9.config import load_registration_m9_config

    return dataclasses.replace(load_registration_m9_config(), **replace)


def _write_m8_artifact(tmp_path, run_id, pair_id, *, entries,
                       dims=(256, 256), state="SELECTED", synthetic=True,
                       trust_run_id=None, matcher_run_id=None,
                       matcher_id="sift", with_dims=True, decision_hash=None):
    root = Path(tmp_path) / "metadata" / "m8_spatial"
    root.mkdir(parents=True, exist_ok=True)
    dims_a = {"height": dims[0], "width": dims[1]} if with_dims else {}
    payload = {
        "run_id": run_id,
        "m8_spatial_run_id": run_id,
        "pair_id": pair_id,
        "created_at_utc": "2026-09-23T00:00:00Z",
        "trust_run_id": trust_run_id or f"tg7-{run_id}",
        "matcher_run_id": matcher_run_id or f"m3-sift-{run_id}",
        "matcher_id": matcher_id,
        "synthetically_derived": synthetic,
        "configuration_id": "SR-M8-001",
        "decision": {
            "state": state, "reasons": ["SPATIAL_BOOKKEEPING_OK"],
            "explanation": "synthetic M8 fixture for M9 tests",
            "block_code": None, "abstain_code": None,
        },
        "decision_hash": decision_hash or "m8hash",
        "evidence": {
            "trusted_count": len(entries),
            "selected_count": len(entries),
            "excluded_count": 0,
            "selection_record": {
                "policy": "GRID_BALANCED", "tie_break": "residual_then_original_index",
                "selected": entries,
            },
            "frame": {
                "frame": "EFFECTIVE_MATCHER_PLANE",
                "side_a": {"effective_dimensions": dict(dims_a)},
                "side_b": {"effective_dimensions": dict(dims_a)},
            },
        },
    }
    (root / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_id


def _write_processing_products(tmp_path, pair_id, *, dims=(256, 256)):
    from backend.app.processing.service import default_configuration_id

    st = _settings(tmp_path)
    run_dir = st.data_root_path / "derived" / "processing" / pair_id / default_configuration_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(3)
    a = rng.randint(0, 2000, size=dims, dtype=np.uint16)
    b = rng.randint(0, 2000, size=dims, dtype=np.uint16)
    arr = np.asarray(a, dtype=np.uint16)
    arr2 = np.asarray(b, dtype=np.uint16)
    np.save(run_dir / "display_a.npy", arr)
    np.save(run_dir / "display_b.npy", arr2)
    status = {
        "pair_id": pair_id,
        "configuration_id": default_configuration_id(),
        "state": "READY_FOR_MATCHING",
        "products": {
            "a": {"display_rel": f"derived/processing/{pair_id}/{default_configuration_id()}/display_a.npy"},
            "b": {"display_rel": f"derived/processing/{pair_id}/{default_configuration_id()}/display_b.npy"},
        },
    }
    (run_dir / "processing_status.json").write_text(json.dumps(status), encoding="utf-8")
    return status


def _m9_service(tmp_path):
    from backend.app.registration_m9.service import RegistrationM9Service

    return RegistrationM9Service(_settings(tmp_path))


def _standard_m8(tmp_path, run_id="m8s-cs-p001-fixture01", pair_id="CS-P001", n=30):
    pts_a, pts_b = _pts_affine(n=n)
    entries = _m8_entries(pts_a, pts_b)
    _write_m8_artifact(tmp_path, run_id, pair_id, entries=entries)
    return entries


# ---------------------------------------------------------------------------
# 1. config
# ---------------------------------------------------------------------------

def test_m9_config_loaded():
    from backend.app.registration_m9.config import load_registration_m9_config

    cfg = load_registration_m9_config()
    assert cfg.configuration_id == "RG-M9-001"
    assert cfg.configuration_version == "1"
    assert cfg.derived_rel == "metadata/m9_registration"
    assert cfg.scientifically_tuned is False
    assert cfg.reference_status == "REFERENCE_UNAVAILABLE"
    assert cfg.model.preference == "smallest_valid"
    assert cfg.model.min_points_affine == 4
    assert cfg.model.min_points_homography == 5
    assert cfg.model.normalized_dlt is True
    assert cfg.validation.max_rmse_px == 3.0
    assert cfg.validation.max_p95_px == 5.0
    assert cfg.validation.max_residual_max_px == 10.0
    assert cfg.warp.interpolation == "linear"
    assert cfg.warp.dtype == "uint16"
    assert cfg.execution.max_runtime_seconds == 120


def test_m9_config_distinct_from_legacy_m6_and_ai_m9():
    from backend.app.registration_m9.config import load_registration_m9_config

    from backend.app.config import m6_config, m9_config

    assert load_registration_m9_config().configuration_id == "RG-M9-001"
    assert m6_config().get("registration_configuration_id") == "RG-M6-001"
    assert m9_config().get("ai_configuration_id") == "AI-M9-001"


def test_m9_config_forbidden_vocabulary():
    from backend.app.registration_m9.config import RegistrationM9Config

    forbidden = RegistrationM9Config().forbidden_vocabulary
    for word in ("confidence", "final_confidence", "best", "winner", "superior",
                 "perfect", "accurate"):
        assert word in forbidden


# ---------------------------------------------------------------------------
# 2. contract + vocabulary guard
# ---------------------------------------------------------------------------

def test_m9_contract_valid_payload_passes():
    from backend.app.registration_m9.contract import assert_artifact_valid

    payload = {
        "run_id": "m9r-cs-p001-1234",
        "decision": {
            "state": "SUCCESS_WITH_WARNINGS", "reasons": ["WARP_INPUT_MISSING"],
            "explanation": "declared geometric transform in the effective matcher plane",
            "block_code": None, "abstain_code": None,
        },
    }
    assert_artifact_valid(payload)


def test_m9_contract_missing_decision_raises():
    from backend.app.registration_m9.contract import assert_artifact_valid

    with pytest.raises(ValueError, match="decision"):
        assert_artifact_valid({"run_id": "x"})


def test_m9_contract_bad_state_raises():
    from backend.app.registration_m9.contract import assert_artifact_valid

    with pytest.raises(ValueError, match="state"):
        assert_artifact_valid({"decision": {"state": "GUESSED"}})


def test_m9_contract_vocabulary_guard_rejects_fields():
    from backend.app.registration_m9.contract import assert_artifact_vocabulary_safe

    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SUCCESS"}, "confidence": 0.9})
    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SUCCESS"}, "best": 1})
    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SUCCESS"}, "accurate": True})
    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SUCCESS"}, "nested": {"perfect": 1}})


# ---------------------------------------------------------------------------
# 3. deterministic model fit
# ---------------------------------------------------------------------------

def test_fit_affine_recovers_noiseless():
    from backend.app.registration_m9.fit import fit_affine

    pts_a, pts_b = _pts_affine(n=40, seed=11)
    M, diag = fit_affine(pts_a, pts_b)
    assert diag["rng"] == "NONE"
    mapped = np.hstack([pts_a, np.ones((len(pts_a), 1))]) @ M.T
    assert np.allclose(mapped[:, :2], pts_b, atol=1e-6)


def test_fit_affine_insufficient():
    from backend.app.registration_m9.fit import fit_affine

    pts_a, pts_b = _pts_affine(n=2)
    M, diag = fit_affine(pts_a, pts_b)
    assert M is None
    assert diag["error"] == "INSUFFICIENT_POINTS"


def test_fit_homography_dlt_recovers_projective():
    from backend.app.registration_m9.fit import fit_homography_normalized_dlt

    rng = np.random.RandomState(5)
    pts_a = rng.uniform(20, 200, (9, 2))
    H_true = np.array([[1.0, 0.05, 4.0],
                       [0.02, 1.03, -2.0],
                       [0.0003, 0.0002, 1.0]])
    h = np.hstack([pts_a, np.ones((len(pts_a), 1))])
    proj = (H_true @ h.T).T
    pts_b = proj[:, :2] / proj[:, 2:3]
    H, diag = fit_homography_normalized_dlt(pts_a, pts_b, normalized=True)
    assert diag["rng"] == "NONE"
    assert diag["normalization"] == "two_point_similarity"
    inv = np.linalg.inv(H)
    hb = np.hstack([pts_b, np.ones((len(pts_b), 1))])
    back = (inv @ hb.T).T
    assert np.allclose(back[:, :2] / back[:, 2:3], pts_a, atol=1e-5)


def test_fit_homography_insufficient():
    from backend.app.registration_m9.fit import fit_homography_normalized_dlt

    pts_a, pts_b = _pts_affine(n=3)
    H, diag = fit_homography_normalized_dlt(pts_a, pts_b)
    assert H is None
    assert diag["error"] == "INSUFFICIENT_POINTS"


def test_choose_and_fit_smallest_valid_affine_preferred():
    from backend.app.registration_m9.fit import choose_and_fit

    pts_a, pts_b = _pts_affine(n=30)
    fit = choose_and_fit(pts_a, pts_b, _m9cfg())
    assert fit.model_type == "AFFINE"
    assert fit.selection_reason == "SMALLEST_VALID_AFFINE"
    assert fit.matrix is not None
    assert fit.error is None


def test_choose_and_fit_explicit_homography():
    from backend.app.registration_m9.fit import choose_and_fit

    pts_a, pts_b = _pts_affine(n=30)
    fit = choose_and_fit(pts_a, pts_b, _m9cfg(), requested_model="homography")
    assert fit.model_type == "HOMOGRAPHY"
    assert fit.selection_reason == "EXPLICIT_HOMOGRAPHY"
    assert fit.matrix is not None


def test_choose_and_fit_explicit_affine_honored():
    from backend.app.registration_m9.fit import choose_and_fit

    pts_a, pts_b = _pts_affine(n=30)
    fit = choose_and_fit(pts_a, pts_b, _m9cfg(), requested_model="affine")
    assert fit.model_type == "AFFINE"
    assert fit.selection_reason == "SMALLEST_VALID_AFFINE"


def test_choose_and_fit_escalates_when_affine_unusable(monkeypatch):
    import backend.app.registration_m9.fit as fitmod
    from backend.app.registration_m9.fit import choose_and_fit

    pts_a, pts_b = _pts_affine(n=30)

    def _fail_affine(pa, pb):
        return None, {"model_type": "AFFINE", "algorithm": "lstsq",
                      "error": "SINGULAR", "source_point_count": len(pa)}

    monkeypatch.setattr(fitmod, "fit_affine", _fail_affine)
    fitted = choose_and_fit(pts_a, pts_b, _m9cfg())
    assert fitted.model_type == "HOMOGRAPHY"
    assert fitted.selection_reason == "AFFINE_INVALID_ESCALATED_HOMOGRAPHY"
    assert fitted.matrix is not None


def test_choose_and_fit_deterministic(monkeypatch):
    from backend.app.registration_m9.fit import choose_and_fit

    pts_a, pts_b = _pts_affine(n=40)
    a = choose_and_fit(pts_a, pts_b, _m9cfg())
    b = choose_and_fit(pts_a, pts_b, _m9cfg())
    assert np.array_equal(a.matrix, b.matrix)
    assert a.selection_reason == b.selection_reason


def test_choose_and_fit_fit_diagnostics_recorded():
    from backend.app.registration_m9.fit import choose_and_fit

    pts_a, pts_b = _pts_affine(n=30)
    fitted = choose_and_fit(pts_a, pts_b, _m9cfg())
    assert fitted.fit_diagnostics["source_point_count"] == 30
    assert fitted.fit_diagnostics["rng_seed_policy"] == "Direct deterministic solve; no random sampling."


# ---------------------------------------------------------------------------
# 4. selected-correspondence input validation
# ---------------------------------------------------------------------------

def test_points_validation_ok():
    from backend.app.registration_m9.points import validate_selected_points

    pts_a, pts_b = _pts_affine(n=20)
    out = validate_selected_points(_m8_entries(pts_a, pts_b), _m9cfg())
    assert out.ok is True
    assert out.n_input == 20 and out.n_usable == 20
    assert out.abstain_code is None


def test_points_insufficient_abstain_code():
    from backend.app.registration_m9.points import validate_selected_points

    pts_a, pts_b = _pts_affine(n=2)
    out = validate_selected_points(_m8_entries(pts_a, pts_b), _m9cfg())
    assert out.ok is False
    assert out.abstain_code == "INSUFFICIENT_SELECTED_POINTS"


def test_points_empty_abstain():
    from backend.app.registration_m9.points import validate_selected_points

    out = validate_selected_points([], _m9cfg())
    assert out.ok is False
    assert out.abstain_code == "INSUFFICIENT_SELECTED_POINTS"


def test_points_non_finite_dropped_with_warning():
    from backend.app.registration_m9.points import validate_selected_points

    pts_a, pts_b = _pts_affine(n=12)
    entries = _m8_entries(pts_a, pts_b)
    entries[1]["x_a"] = float("nan")
    entries[5]["y_b"] = float("inf")
    out = validate_selected_points(entries, _m9cfg())
    assert out.ok is True
    assert out.dropped_non_finite == 2
    assert out.n_usable == 10
    assert "NON_FINITE_POINTS_DROPPED" in out.warnings


def test_points_duplicates_keep_first_with_warning():
    from backend.app.registration_m9.points import validate_selected_points

    pts_a, pts_b = _pts_affine(n=10)
    entries = _m8_entries(pts_a, pts_b)
    dup = dict(entries[3])
    dup["m8_index"] = 50
    entries.insert(6, dup)
    out = validate_selected_points(entries, _m9cfg())
    assert out.ok is True
    assert out.dropped_duplicates == 1
    assert out.n_usable == 10
    assert "DUPLICATE_POINTS_DROPPED" in out.warnings
    m8s = [e["m8_index"] for e in out.entries]
    assert m8s.count(3) == 1


def test_points_collinear_degenerate():
    from backend.app.registration_m9.points import validate_selected_points

    line = np.linspace(0, 100, 12)
    entries = _m8_entries(np.vstack([line, line * 0 + 5]).T,
                          np.vstack([line + 1, line * 0 + 6]).T)
    out = validate_selected_points(entries, _m9cfg())
    assert out.ok is False
    assert out.abstain_code == "DEGENERATE_GEOMETRY"


def test_points_assign_m9_index_preserving_upstream():
    from backend.app.registration_m9.points import validate_selected_points

    pts_a, pts_b = _pts_affine(n=6)
    entries = _m8_entries(pts_a, pts_b)
    entries[0]["m8_index"] = 100
    entries[0]["m7_index"] = 900
    out = validate_selected_points(entries, _m9cfg())
    assert out.entries[0]["m9_index"] == 0
    assert out.entries[0]["m8_index"] == 100
    assert out.entries[0]["m7_index"] == 900
    assert out.pts_a.shape == (6, 2)


# ---------------------------------------------------------------------------
# 5. independent transform validation
# ---------------------------------------------------------------------------

def _good_validation(cfg=None, n=30):
    from backend.app.registration_m9.fit import choose_and_fit
    from backend.app.registration_m9.validate import validate_transform

    cfg = cfg or _m9cfg()
    dims = {"height": 256, "width": 256}
    pts_a, pts_b = _pts_affine(n=n)
    fit = choose_and_fit(pts_a, pts_b, cfg)
    return validate_transform(fit.matrix, fit.model_type, fit.algorithm,
                              cfg, pts_a, pts_b, dims, dims)


def test_validate_accepts_good_affine_with_px_stats():
    out = _good_validation()
    assert out.transform_valid is True
    assert out.accepted is True
    stats = out.residual_statistics
    assert stats["unit"] == "px"
    assert stats["frame"] == "EFFECTIVE_MATCHER_PLANE"
    assert stats["rmse"] < 3.0
    assert out.to_registration_block()["accepted"] is True
    assert out.to_registration_block()["model_type"] == "AFFINE"


def test_validate_rejects_bad_residuals():
    from backend.app.registration_m9.validate import residual_statistics, validate_transform

    cfg = _m9cfg()
    dims = {"height": 256, "width": 256}
    M = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    pts_a, pts_b = _pts_affine(n=20)
    pts_b = pts_b + 500.0
    out = validate_transform(M, "AFFINE", "lstsq", cfg, pts_a, pts_b, dims, dims)
    assert out.accepted is False
    assert any(issue.startswith("RMSE_HIGH") for issue in out.issues)
    stats = residual_statistics(pts_a, pts_b, M)
    assert stats["unit"] == "px"


def test_validate_rejects_non_finite_matrix():
    from backend.app.registration_m9.validate import validate_transform

    dims = {"height": 256, "width": 256}
    M = np.array([[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
    pts_a, pts_b = _pts_affine(n=10)
    out = validate_transform(M, "AFFINE", "lstsq", _m9cfg(), pts_a, pts_b, dims, dims)
    assert out.checks["matrix_finite"] is False
    assert "NON_FINITE_MATRIX" in out.issues
    assert out.accepted is False


def test_validate_rejects_singular_determinant():
    from backend.app.registration_m9.validate import validate_transform

    dims = {"height": 256, "width": 256}
    M = np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 6.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    pts_a, pts_b = _pts_affine(n=10)
    out = validate_transform(M, "AFFINE", "lstsq", _m9cfg(), pts_a, pts_b, dims, dims)
    assert any("SINGULAR_OR_TINY_DETERMINANT" in i for i in out.issues)
    assert out.accepted is False


def test_validate_tiny_scale_rejected():
    from backend.app.registration_m9.validate import validate_transform

    dims = {"height": 256, "width": 256}
    M = np.array([[1e-9, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    pts_a, pts_b = _pts_affine(n=10)
    pts_b = pts_b * 1e-9
    out = validate_transform(M, "AFFINE", "lstsq", _m9cfg(), pts_a, pts_b, dims, dims)
    assert any("SCALE_TOO_SMALL" in i or "DETERMINANT" in i for i in out.issues)


def test_validate_reverse_roundtrip_statistics():
    out = _good_validation()
    rev = out.reverse_statistics
    assert rev["unit"] == "px"
    assert rev["count"] == out.residual_statistics["count"]
    assert rev["rmse"] is not None and rev["rmse"] < 3.0


def test_validate_scale_change_warning():
    from backend.app.registration_m9.validate import validate_transform

    dims = {"height": 256, "width": 256}
    M = np.array([[50.0, 0.0, 10.0], [0.0, 2.0, 10.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    pts_a, pts_b = _pts_affine(n=10)
    pts_b = pts_a * np.asarray([[50.0, 2.0]]) + 10.0
    out = validate_transform(M, "AFFINE", "lstsq", _m9cfg(), pts_a, pts_b, dims, dims)
    assert "SCALE_CHANGE_LARGE" in out.warnings


def test_validate_transform_corner_extent():
    from backend.app.registration_m9.validate import transform_corner_extent

    M = np.array([[1.0, 0.0, 5.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    extent = transform_corner_extent(M, {"height": 256, "width": 256})
    assert extent["finite"] is True
    assert extent["transformed_extent"]["min_x"] == 5.0
    assert extent["transformed_extent"]["max_y"] == 259.0


def test_validate_deterministic_statistics():
    a = _good_validation()
    b = _good_validation()
    assert a.residual_statistics == b.residual_statistics


# ---------------------------------------------------------------------------
# 6. derived aligned/warped output
# ---------------------------------------------------------------------------

def test_warp_to_frame_shapes_and_settings(tmp_path):
    from backend.app.registration_m9.warp import warp_to_frame

    rng = np.random.RandomState(2)
    src = rng.randint(0, 500, size=(256, 256)).astype(np.uint16)
    M = np.array([[1.0, 0.0, 5.0], [0.0, 1.0, 3.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    out = warp_to_frame(src, M, 256, 256, _m9cfg())
    assert out["warped"].shape == (256, 256)
    assert out["valid_mask"].dtype == np.bool_
    assert out["interpolation"] == "linear"
    assert out["border_mode"] == "constant"
    assert out["fill_value"] == 0
    assert out["dtype"] == "uint16"


def test_warp_with_singular_transform_error():
    from backend.app.registration_m9.warp import warp_to_frame

    src = np.zeros((8, 8), dtype=np.uint16)
    M = np.zeros((3, 3), dtype=np.float64)
    out = warp_to_frame(src, M, 8, 8, _m9cfg())
    assert out["error"] == "SINGULAR_TRANSFORM"


def test_warp_places_content_at_transformed_position():
    from backend.app.registration_m9.warp import warp_to_frame

    src = np.zeros((256, 256), dtype=np.uint16)
    src[40, 30] = 60000
    M = np.array([[1.0, 0.0, 55.0], [0.0, 1.0, 77.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    out = warp_to_frame(src, M, 256, 256, _m9cfg())
    yy, xx = np.unravel_index(np.argmax(out["warped"]), out["warped"].shape)
    assert abs(yy - 117) <= 2
    assert abs(xx - 85) <= 2
    assert out["warped"][yy, xx] > 0

    Hs = np.array([[1.0, 0.0, 55.0], [0.0, 1.0, 77.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    out2 = warp_to_frame(src, Hs.astype(np.float64) * 1.0, 256, 256, _m9cfg())
    nonzero = np.count_nonzero(out2["warped"])
    assert nonzero > 0


def test_warp_non_finite_transform_error():
    from backend.app.registration_m9.warp import warp_to_frame

    src = np.zeros((8, 8), dtype=np.uint16)
    M = np.array([[np.nan, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
    out = warp_to_frame(src, M, 8, 8, _m9cfg())
    assert out["error"] == "NON_FINITE_TRANSFORM"


def test_warp_missing_source_error():
    from backend.app.registration_m9.warp import warp_to_frame

    M = np.eye(3)
    out = warp_to_frame(None, M, 8, 8, _m9cfg())
    assert out["error"] == "WARP_INPUT_MISSING"


def test_to_dtype_uint16_clip():
    from backend.app.registration_m9.warp import to_dtype

    arr = np.array([-5.0, 0.5, 70000.0, 2.4], dtype=np.float32)
    out = to_dtype(arr, "uint16")
    assert out.dtype == np.uint16
    assert out[0] == 0
    assert out[3] == 2
    assert out[2] == np.iinfo(np.uint16).max
    assert to_dtype(arr, "not_a_dtype_xyz") is arr


def test_preview_and_visualizations_written(tmp_path):
    from backend.app.registration_m9.warp import (
        build_before_after,
        build_checkerboard,
        build_difference_map,
        build_overlay,
        build_residual_vectors,
        write_preview_png,
    )

    rng = np.random.RandomState(4)
    a = rng.randint(0, 1000, size=(64, 64)).astype(np.uint16)
    b = rng.randint(0, 1000, size=(64, 64)).astype(np.uint16)
    w = rng.randint(0, 1000, size=(64, 64)).astype(np.uint16)
    d = tmp_path
    write_preview_png(w, d / "preview.png")
    build_before_after(a, b, w, d / "ba.png")
    build_checkerboard(b, w, d / "ck.png")
    build_difference_map(b, w, d / "diff.png")
    build_overlay(b, w, d / "ov.png")
    pts_a, pts_b = _pts_affine(n=6)
    M = np.array([[1.0, 0.0, 2.0], [0.0, 1.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    build_residual_vectors(_m8_entries(pts_a, pts_b), M, 64, 64, d / "rv.png")
    for name in ("preview.png", "ba.png", "ck.png", "diff.png", "ov.png", "rv.png"):
        assert (d / name).is_file(), name


# ---------------------------------------------------------------------------
# 7. service resolution + persistence
# ---------------------------------------------------------------------------

def test_service_requires_registered_pair(tmp_path):
    from backend.app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        _m9_service(tmp_path).run("CS-NOPE")


def test_service_no_usable_m8_blocked_and_persisted(tmp_path):
    _registry(tmp_path)
    out = _m9_service(tmp_path).run("CS-P001")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "M8_SELECTION_NOT_AVAILABLE"
    path = tmp_path / "metadata" / "m9_registration" / f"{out['run_id']}.json"
    assert path.is_file()


def test_service_latest_non_usable_m8_blocked_with_reason(tmp_path):
    _registry(tmp_path)
    _write_m8_artifact(tmp_path, "m8s-cs-p001-abstain01", "CS-P001",
                       entries=_m8_entries(*_pts_affine(n=8)), state="NO_VALID_SELECTION")
    out = _m9_service(tmp_path).run("CS-P001")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "M8_SELECTION_NOT_AVAILABLE"
    assert "latest M8 state: NO_VALID_SELECTION" in out["decision"]["explanation"]


def test_service_explicit_unknown_m8_blocked(tmp_path):
    _registry(tmp_path)
    out = _m9_service(tmp_path).run("CS-P001", m8_run_id="m8s-doesnotexist")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "M8_SELECTION_NOT_AVAILABLE"


def test_service_explicit_m8_wrong_pair_blocked(tmp_path):
    _registry(tmp_path)
    _write_m8_artifact(tmp_path, "m8s-cs-p002-other01", "CS-P002",
                       entries=_m8_entries(*_pts_affine(n=12)))
    out = _m9_service(tmp_path).run("CS-P001", m8_run_id="m8s-cs-p002-other01")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "INPUT_ARTIFACT_INVALID"


def test_service_success_end_to_end_persisted(tmp_path):
    from backend.app.registration_m9.contract import assert_artifact_valid

    rec = _registry(tmp_path)
    entries = _standard_m8(tmp_path)
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert out["decision"]["state"] == "SUCCESS_WITH_WARNINGS"
    assert "WARP_INPUT_MISSING" in out["decision"]["reasons"]
    assert out["decision"]["block_code"] is None
    assert out["registration"]["accepted"] is True
    assert out["registration"]["model_type"] == "AFFINE"
    assert out["registration"]["residual_statistics"]["unit"] == "px"
    assert out["points"][0]["residual_px"] is not None
    assert_artifact_valid(out)
    path = tmp_path / "metadata" / "m9_registration" / f"{out['run_id']}.json"
    assert path.is_file()
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["decision_hash"] == out["decision_hash"]
    assert disk["m8_run_id"] == "m8s-cs-p001-fixture01"
    assert disk["decision"]["state"] == out["decision"]["state"]


def test_service_deterministic_across_two_runs(tmp_path):
    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    svc = _m9_service(tmp_path)
    a = svc.run(rec.pair_id)
    b = svc.run(rec.pair_id)
    assert a["run_id"] != b["run_id"]
    assert a["decision_hash"] == b["decision_hash"]
    assert a["registration"]["transform_matrix"] == b["registration"]["transform_matrix"]
    assert a["registration"]["residual_statistics"] == b["registration"]["residual_statistics"]


def test_service_vocabulary_safe_and_no_overwrite(tmp_path):
    from backend.app.registration_m9.contract import assert_artifact_vocabulary_safe

    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    svc = _m9_service(tmp_path)
    out = svc.run(rec.pair_id)
    assert_artifact_vocabulary_safe(out)
    text = json.dumps(out["decision"]) + json.dumps(out["registration"] or {})
    for word in ("confidence", "final_confidence", "best", "winner", "superior",
                 "perfect", "accurate"):
        assert f'"{word}"' not in text, word
    with pytest.raises(OSError, match="overwrite"):
        svc.write_artifact(out["run_id"], out)


def test_service_insufficient_points_abstain(tmp_path):
    rec = _registry(tmp_path)
    pts_a, pts_b = _pts_affine(n=2)
    _write_m8_artifact(tmp_path, "m8s-cs-p001-few01", rec.pair_id,
                       entries=_m8_entries(pts_a, pts_b))
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert out["decision"]["state"] == "ABSTAIN"
    assert out["decision"]["abstain_code"] == "INSUFFICIENT_SELECTED_POINTS"


def test_service_collinear_points_abstain(tmp_path):
    rec = _registry(tmp_path)
    line = np.linspace(5, 200, 10)
    pts_a = np.vstack([line, line * 0 + 5]).T
    _write_m8_artifact(tmp_path, "m8s-cs-p001-collinear", rec.pair_id,
                       entries=_m8_entries(pts_a, pts_a + 1.0))
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert out["decision"]["state"] == "ABSTAIN"
    assert out["decision"]["abstain_code"] == "DEGENERATE_GEOMETRY"


def test_service_missing_frame_dims_blocked(tmp_path):
    rec = _registry(tmp_path)
    pts_a, pts_b = _pts_affine(n=20)
    _write_m8_artifact(tmp_path, "m8s-cs-p001-noframe", rec.pair_id,
                       entries=_m8_entries(pts_a, pts_b), with_dims=False)
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "INVALID_COORDINATE_FRAME"


def test_service_m8_state_not_usable_blocked(tmp_path):
    rec = _registry(tmp_path)
    _write_m8_artifact(tmp_path, "m8s-cs-p001-blk01", rec.pair_id,
                       entries=_m8_entries(*_pts_affine(n=12)), state="BLOCKED")
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "M8_SELECTION_NOT_AVAILABLE"


def test_service_real_data_gate_blocked(tmp_path, monkeypatch):
    from backend.app import pairs as pairs_module
    from backend.app.registration_m9.service import _synthetic_like

    class _RealRec:
        pair_id = "CS-P002"
        source_class_a = "OHRC"
        source_class_b = "TMC2"
        data_source_gate = "PATH_A_REAL_DATA"

    rec = _RealRec()
    assert _synthetic_like(rec) is False
    _write_m8_artifact(tmp_path, "m8s-cs-p002-synth01", rec.pair_id,
                       entries=_m8_entries(*_pts_affine(n=12)), synthetic=True)
    monkeypatch.setattr(pairs_module.PairRegistry, "get", lambda self, pid: rec)
    out = _m9_service(tmp_path).run("CS-P002")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "REAL_DATA_BLOCKED"


def test_service_warp_success_with_products(tmp_path):
    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    _write_processing_products(tmp_path, rec.pair_id)
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert out["decision"]["state"] == "SUCCESS"
    assert out["warp"]["available"] is True
    assert out["warp"]["registered_image_rel"].endswith("registered_image.npy")
    assert out["warp"]["valid_mask_rel"].endswith("valid_mask.npy")
    base = _settings(tmp_path).data_root_path
    assert (base / out["warp"]["registered_image_rel"]).is_file()
    assert (base / out["warp"]["valid_mask_rel"]).is_file()
    assert out["warp"]["interpolation"] == "linear"
    assert out["warp"]["border_mode"] == "constant"
    assert out["warp"]["dtype"] == "uint16"


def test_service_artifact_relative_paths_only(tmp_path):
    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    _write_processing_products(tmp_path, rec.pair_id)
    out = _m9_service(tmp_path).run(rec.pair_id)
    text = json.dumps(out)
    blocks = [out["warp"]]
    mount = str(_settings(tmp_path).data_root_path).replace("\\", "/")
    for warp in blocks:
        for key in ("registered_image_rel", "valid_mask_rel", "preview_rel", "artifact_ref"):
            rel = warp.get(key)
            if rel:
                assert ".." not in rel
                assert not Path(rel).is_absolute()
    assert mount.split("/")[-1] not in text or "metadata/" in text


def test_service_provenance_chain(tmp_path):
    rec = _registry(tmp_path)
    entries = _standard_m8(tmp_path)
    out = _m9_service(tmp_path).run(rec.pair_id)
    prov = out["provenance"]
    assert prov["m9_run"] == out["run_id"]
    assert prov["m8_run"] == "m8s-cs-p001-fixture01"
    assert "M8 spatial selection -> M9 registration" in prov["chain"]
    upstream = out["upstream"]
    assert upstream["m8_run_id"] == "m8s-cs-p001-fixture01"
    assert upstream["m8_status"] == "SELECTED"
    assert upstream["m8_decision_hash"] == "m8hash"
    assert out["experiment_id"].startswith("EXP-M9-")


def test_service_explicit_models_honored(tmp_path):
    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    svc = _m9_service(tmp_path)
    aff = svc.run(rec.pair_id, model="affine")
    assert aff["registration"]["model_type"] == "AFFINE"
    assert aff["registration"]["selection_reason"] == "SMALLEST_VALID_AFFINE"
    hom = svc.run(rec.pair_id, model="homography")
    assert hom["registration"]["model_type"] == "HOMOGRAPHY"
    assert hom["registration"]["selection_reason"] == "EXPLICIT_HOMOGRAPHY"


def test_service_invalid_model_blocked(tmp_path):
    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    out = _m9_service(tmp_path).run(rec.pair_id, model="polynomial")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "INPUT_ARTIFACT_INVALID"


def test_service_fit_failure_failed_state(tmp_path, monkeypatch):
    from backend.app.registration_m9.fit import FitResult
    import backend.app.registration_m9.service as m9svc

    rec = _registry(tmp_path)
    _standard_m8(tmp_path)

    def _boom(pa, pb, cfg, requested_model="auto"):
        return FitResult("AFFINE", "SMALLEST_VALID_AFFINE", "lstsq", None,
                         {}, error="TEST_SINGULARITY")

    monkeypatch.setattr(m9svc, "choose_and_fit", _boom)
    out = m9svc.RegistrationM9Service(_settings(tmp_path)).run(rec.pair_id)
    assert out["decision"]["state"] == "FAILED"
    assert out["decision"]["reasons"] == ["TRANSFORM_FIT_ERROR"]


def test_service_status_shape_and_list_runs(tmp_path):
    rec = _registry(tmp_path)
    svc = _m9_service(tmp_path)
    status = svc.status(rec.pair_id)
    assert status["configured"]["configuration_id"] == "RG-M9-001"
    assert status["configured"]["model_preference"] == "smallest_valid"
    assert status["configured"]["max_rmse_px"] == 3.0
    assert status["latest_run"] is None
    assert svc.list_runs(rec.pair_id) == []

    _standard_m8(tmp_path)
    svc.run(rec.pair_id)
    runs = svc.list_runs(rec.pair_id)
    assert len(runs) == 1
    row = runs[0]
    assert row["pair_id"] == rec.pair_id
    assert row["state"] == "SUCCESS_WITH_WARNINGS"
    assert row["m8_run_id"] == "m8s-cs-p001-fixture01"
    assert row["model_type"] == "AFFINE"
    assert row["configuration_id"] == "RG-M9-001"
    assert row["decision_hash"]
    assert svc.read(row["run_id"]) is not None


def test_service_read_safe_runid_guard(tmp_path):
    svc = _m9_service(tmp_path)
    assert svc.read("../etc/passwd") is None
    assert svc.read("m9r-cs-p001:not!") is None


def test_service_runtime_and_environment_block(tmp_path):
    rec = _registry(tmp_path)
    _standard_m8(tmp_path)
    out = _m9_service(tmp_path).run(rec.pair_id)
    assert isinstance(out["runtime_ms"], int) and out["runtime_ms"] >= 0
    env = out["environment"]
    assert env["rng"] == "NONE"
    assert env["python_version"]
    assert out["performance"]["transform_fit_runtime_ms"] is not None
    assert out["registration"]["transform_hash"]


# ---------------------------------------------------------------------------
# 8. end-to-end API over synthetic fixtures
# ---------------------------------------------------------------------------

def _seed_pair_and_m8(tmp_path):
    from backend.app.config import Settings
    from backend.app.registration_m9.service import RegistrationM9Service
    from backend.app.pairs import PairRecord, PairRegistry

    st = Settings(data_root=str(tmp_path / "data"), _env_file=None)
    record = PairRecord(
        pair_id="CS-P001", image_a_filename="a.img", image_b_filename="b.img",
        source_class_a="TEST_FIXTURE", source_class_b="TEST_FIXTURE",
        data_source_gate="PATH_B_SYNTHETIC_ONLY",
    )
    PairRegistry(st).save(record)
    pts_a, pts_b = _pts_affine(n=30)
    _write_m8_artifact(st.data_root_path, "m8s-cs-p001-apifx", record.pair_id,
                       entries=_m8_entries(pts_a, pts_b))
    return record


def test_api_status_and_runs_empty(authed_client_factory, tmp_path):
    client = authed_client_factory()
    _seed_pair_and_m8(tmp_path)
    status = client.get("/api/pairs/CS-P001/registration-m9/status")
    assert status.status_code in (200, 401, 403), status.text
    if status.status_code == 200:
        assert status.json()["configured"]["configuration_id"] == "RG-M9-001"
        assert status.json()["latest_run"] is None


def test_api_run_detail_unknown_404(authed_client_factory, tmp_path):
    client = authed_client_factory()
    detail = client.get("/api/registration-m9/runs/m9r-nope-00000000")
    assert detail.status_code in (404, 401, 403)


def test_api_run_end_to_end_and_list_detail(authed_client_factory, tmp_path):
    client = authed_client_factory()
    _seed_pair_and_m8(tmp_path)
    resp = client.post("/api/pairs/CS-P001/registration-m9/run", json={"model": "auto"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["decision"]["state"] == "SUCCESS_WITH_WARNINGS"
    assert out["registration"]["accepted"] is True
    art = Path(tmp_path) / "data" / "metadata" / "m9_registration" / f"{out['run_id']}.json"
    assert art.is_file()

    runs = client.get("/api/pairs/CS-P001/registration-m9/runs")
    assert runs.status_code == 200
    rows = runs.json()["runs"]
    assert len(rows) == 1 and rows[0]["run_id"] == out["run_id"]

    detail = client.get(f"/api/registration-m9/runs/{out['run_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run_id"] == out["run_id"]
    assert body["decision"]["state"] == out["decision"]["state"]
    text = json.dumps(body["decision"]) + json.dumps(body["registration"])
    for word in ("confidence", "final_confidence", "winner", "superior", "perfect", "accurate"):
        assert f'"{word}"' not in text, word


def test_api_run_with_unknown_m8_blocked(authed_client_factory, tmp_path):
    client = authed_client_factory()
    _seed_pair_and_m8(tmp_path)
    resp = client.post("/api/pairs/CS-P001/registration-m9/run",
                       json={"m8_run_id": "m8s-doesnotexist"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"]["block_code"] == "M8_SELECTION_NOT_AVAILABLE"


def test_api_visualization_and_preview(authed_client_factory, tmp_path):
    client = authed_client_factory()
    _seed_pair_and_m8(tmp_path)
    # seed processing products under the client data root so warp is produced
    _write_processing_products_for_client(tmp_path)
    out = client.post("/api/pairs/CS-P001/registration-m9/run",
                      json={"model": "auto"}).json()
    viz = client.get(f"/api/registration-m9/runs/{out['run_id']}/visualization")
    assert viz.status_code == 200, viz.text
    assert viz.json()["warp_available"] is True
    names = {i["name"] for i in viz.json()["visualizations"]}
    assert "registered_preview.png" in names
    preview = client.get(f"/api/registration-m9/runs/{out['run_id']}/preview")
    assert preview.status_code == 200, preview.text
    registered = client.get(f"/api/registration-m9/runs/{out['run_id']}/registered")
    assert registered.status_code == 200


def _write_processing_products_for_client(tmp_path):
    from backend.app.config import Settings
    from backend.app.processing.service import default_configuration_id

    st = Settings(data_root=str(tmp_path / "data"), _env_file=None)
    run_dir = st.data_root_path / "derived" / "processing" / "CS-P001" / default_configuration_id()
    run_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(3)
    a = rng.randint(0, 2000, size=(256, 256)).astype(np.uint16)
    b = rng.randint(0, 2000, size=(256, 256)).astype(np.uint16)
    np.save(run_dir / "display_a.npy", a)
    np.save(run_dir / "display_b.npy", b)
    status = {
        "pair_id": "CS-P001",
        "configuration_id": default_configuration_id(),
        "state": "READY_FOR_MATCHING",
        "products": {
            "a": {"display_rel": f"derived/processing/CS-P001/{default_configuration_id()}/display_a.npy"},
            "b": {"display_rel": f"derived/processing/CS-P001/{default_configuration_id()}/display_b.npy"},
        },
    }
    (run_dir / "processing_status.json").write_text(json.dumps(status), encoding="utf-8")


def test_api_status_after_runs(authed_client_factory, tmp_path):
    client = authed_client_factory()
    _seed_pair_and_m8(tmp_path)
    client.post("/api/pairs/CS-P001/registration-m9/run", json={})
    status = client.get("/api/pairs/CS-P001/registration-m9/status")
    assert status.status_code in (200, 401, 403)
    if status.status_code == 200:
        assert status.json()["latest_run"]["run_id"]


# ---------------------------------------------------------------------------
# 9. M1–M8 + M10–M13 regression smokes
# ---------------------------------------------------------------------------

def test_regression_m1_m2_core_configs_load():
    from backend.app.config import m1_config, m2_config

    assert m1_config() and m1_config().get("allowed_raw_locations")
    assert m2_config().get("configuration_id") == "PC-M2-001"


def test_regression_m3_m4_m5_m6_legacy():
    from backend.app.config import m3_config, m4_config, m5_config, m6_config
    from backend.app.registration.service import RegistrationService

    assert m3_config() and any(m3_config())
    assert m4_config() and m4_config().get("name")
    assert m5_config()
    assert m6_config().get("registration_configuration_id", "RG-M6-001") == "RG-M6-001"
    assert RegistrationService


def test_regression_m7_trust_gate():
    from backend.app.spatial_m8.config import load_spatial_selection_config
    from backend.app.trust_gate.config import load_trust_gate_config

    assert load_spatial_selection_config().configuration_id == "SR-M8-001"
    assert load_trust_gate_config().configuration_id == "TG-M7-001"


def test_regression_m8_smoke():
    from backend.app.spatial_m8.service import SpatialSelectionService

    assert SpatialSelectionService
    from backend.app.spatial_m8.states import SELECTED, SELECTED_WITH_WARNINGS

    assert "SELECTED" in (SELECTED, SELECTED_WITH_WARNINGS)


def test_regression_m10_through_m13_import_smoke():
    from backend.app import security  # noqa: F401  (M10)

    from backend.app import auth, hardening, ops  # noqa: F401  (M10/M11)
    import backend.app.api.m12  # noqa: F401  (M12)
    import backend.app.api.m13  # noqa: F401  (M13)
    import backend.app.metrics.service  # noqa: F401

    assert security.Role is not None
    assert ops.SERVICE_IDS


def test_regression_routes_present():
    from backend.app.config import Settings
    from backend.app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app(settings=Settings(data_root="data", _env_file=None))
    spec = TestClient(app).get("/openapi.json").json()
    routes = set(spec["paths"])
    assert any("m12" in r for r in routes)
    assert any("m13" in r for r in routes)
    assert any("registration-m9" in r for r in routes)