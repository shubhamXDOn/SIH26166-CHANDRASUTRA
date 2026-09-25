"""M7 TRUST GATE tests — deterministic geometric verification.

Covers:
    * pure-engine decisions (ZERO_CANDIDATES / INSUFFICIENT_CANDIDATES /
      INVALID_INPUT / RESOURCE_LIMIT / DEGENERATE_GEOMETRY / NO_VALID_MODEL,
      ACCEPT on clean affine + homography, REJECT on noise / residual /
      spatial-sanity failures) and determinism;
    * the artifact contract + vocabulary guard (field names like
      ``confidence`` / ``best`` are scan-rejected, not silently renamed);
    * the service resolution rules (explicit matcher run, M6 routing
      provenance, latest-run fallback, pair mismatch);
    * honest pre-flight blocks: missing candidates, non-SUCCESS runs,
      undeclared coordinate frame, real-data pair fed by a synthetic-derived
      run (REAL_DATA_BLOCKED);
    * persistence: unique never-overwritten artifacts under metadata/m7_trust,
      no M8 spatial-selection / M9 registration semantics, no absolute paths.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import numpy as np
import pytest

import auth_helpers  # noqa: F401
import fixturegen  # noqa: F401

from auth_helpers import AUTH_TEST_SECRET  # noqa: F401


# ---------------------------------------------------------------------------
# synthetic geometry helpers
# ---------------------------------------------------------------------------

def _affine_scene(n_in=60, n_out=10, noise=0.4, seed=7):
    rng = np.random.RandomState(seed)
    pts = rng.uniform(20, 200, size=(n_in, 2))
    m = np.array([[1.02, 0.05, 4.0], [-0.03, 0.98, -3.0], [0.0, 0.0, 1.0]])
    ha = np.hstack([pts, np.ones((n_in, 1))])
    proj = (m @ ha.T).T
    b = proj[:, :2] / proj[:, 2:3] + rng.normal(0, noise, (n_in, 2))
    rows = [list(pts[i]) + list(b[i]) for i in range(n_in)]
    if n_out:
        rows += [list(r) for r in rng.uniform(-60, 260, size=(n_out, 4))]
    return np.asarray(rows, dtype=np.float64)


def _homography_scene(n=45, seed=1):
    rng = np.random.RandomState(seed)
    pts = rng.uniform(30, 170, size=(n, 2))
    h = np.array([[1.1, 0.2, 5], [0.1, 0.95, -4], [0.0004, 0.001, 1.0]])
    ha = np.hstack([pts, np.ones((n, 1))])
    p = (h @ ha.T).T
    b = p[:, :2] / p[:, 2:3]
    return np.hstack([pts, b])


def _cfg(preferred="affine", **decision_kw):
    from backend.app.trust_gate.config import (
        DecisionGateConfig,
        GeometryGateConfig,
        TrustGateConfig,
        load_trust_gate_config,
    )

    base = load_trust_gate_config()
    dec = dataclasses.replace(base.decision, **decision_kw)
    geo = dataclasses.replace(
        base.geometry, preferred_model=preferred
    )
    return dataclasses.replace(base, decision=dec, geometry=geo)


def _verify(coords, **kw):
    from backend.app.trust_gate.engine import verify

    return verify(coords, _cfg(**kw))


# ---------------------------------------------------------------------------
# 1. config
# ---------------------------------------------------------------------------

def test_trust_gate_config_loaded():
    from backend.app.trust_gate.config import load_trust_gate_config

    cfg = load_trust_gate_config()
    assert cfg.configuration_id == "TG-M7-001"
    assert cfg.configuration_version == "1"
    assert cfg.derived_rel == "metadata/m7_trust"
    assert cfg.scientifically_tuned is False
    assert cfg.reference_status == "REFERENCE_UNAVAILABLE"
    assert cfg.geometry.preferred_model == "affine"
    assert cfg.geometry.models == ("affine", "homography")
    assert cfg.geometry.ransac.seed == 20260923
    assert cfg.decision.min_candidates == 8
    assert cfg.decision.min_inliers == 8


def test_config_forbidden_vocabulary_used_by_guard():
    from backend.app.trust_gate.config import TrustGateConfig

    forbidden = TrustGateConfig().forbidden_vocabulary
    assert "confidence" in forbidden
    assert "best" in forbidden


def test_configuration_snapshot_persisted_shape():
    from backend.app.trust_gate.service import _configuration_dict
    from backend.app.trust_gate.config import load_trust_gate_config

    snap = _configuration_dict(load_trust_gate_config())
    assert snap["configuration_id"] == "TG-M7-001"
    assert snap["decision"]["min_inlier_ratio"] == 0.30
    assert snap["geometry"]["preferred_model"] == "affine"
    assert snap["geometry"]["ransac"]["confidence_parameter"] == 0.99


# ---------------------------------------------------------------------------
# 2. pure engine: abstain / blocked pre-checks
# ---------------------------------------------------------------------------

def test_verify_zero_candidates_abstain():
    r = _verify(None)
    assert r["decision"]["state"] == "ABSTAIN"
    assert r["decision"]["abstain_code"] == "ZERO_CANDIDATES"
    r2 = _verify(np.zeros((0, 4)))
    assert r2["decision"]["state"] == "ABSTAIN"
    assert r2["decision"]["abstain_code"] == "ZERO_CANDIDATES"


def test_verify_insufficient_candidates_abstain():
    r = _verify(np.random.RandomState(0).uniform(0, 100, (4, 4)))
    assert r["decision"]["state"] == "ABSTAIN"
    assert r["decision"]["abstain_code"] == "INSUFFICIENT_CANDIDATES"
    assert r["evidence"]["candidate_count"] == 4


def test_verify_nan_blocked():
    coords = _affine_scene(n_in=20, n_out=0)
    bad = np.vstack([coords, [[np.nan, 1, 2, 3]]])
    r = _verify(bad)
    assert r["decision"]["state"] == "BLOCKED"
    assert r["decision"]["block_code"] == "INVALID_INPUT"
    assert r["evidence"]["non_finite_count"] == 1


def test_verify_inf_blocked():
    coords = _affine_scene(n_in=20, n_out=0)
    bad = np.vstack([coords, [[1.0, np.inf, 2, 3]]])
    r = _verify(bad)
    assert r["decision"]["block_code"] == "INVALID_INPUT"


def test_verify_resource_cap_abstain():
    from backend.app.trust_gate.config import load_trust_gate_config

    cap = load_trust_gate_config().resource.max_candidates
    big = np.random.RandomState(0).uniform(0, 100, (cap + 1, 4))
    r = _verify(big)
    assert r["decision"]["state"] == "ABSTAIN"
    assert r["decision"]["abstain_code"] == "RESOURCE_LIMIT"


def test_verify_collinear_degeneracy_abstain():
    xs = np.linspace(0, 100, 20)
    pts = np.column_stack([xs, xs * 0.5])
    coords = np.column_stack([pts, pts])
    r = _verify(coords)
    assert r["decision"]["state"] == "ABSTAIN"
    assert r["decision"]["abstain_code"] == "DEGENERATE_GEOMETRY"
    flags = r["evidence"]["degeneracy"]["flags"]
    assert any("SOURCE_COLLINEAR" in f for f in flags)
    assert any("TARGET_COLLINEAR" in f for f in flags)


# ---------------------------------------------------------------------------
# 3. pure engine: accept / reject / determinism
# ---------------------------------------------------------------------------

def test_verify_accept_clean_affine():
    r = _verify(_affine_scene())
    assert r["decision"]["state"] == "ACCEPT"
    reasons = r["decision"]["reasons"]
    assert "INLIER_MIN_OK" in reasons
    assert "RESIDUAL_OK" in reasons
    assert r["evidence"]["model"]["model_type"] == "affine"
    assert r["evidence"]["model"]["model_valid"] is True
    assert float(r["evidence"]["model"]["determinant_linear_part"]) > 0
    assert r["decision"]["block_code"] is None


def test_verify_model_parameters_recorded():
    from backend.app.trust_gate.config import load_trust_gate_config

    r = _verify(_affine_scene())
    cfg = load_trust_gate_config()
    params = r["evidence"]["model"]["model_parameters"]
    assert params["seed_used"] == cfg.geometry.ransac.seed
    assert params["preferred_model"] == "affine"
    assert params["confidence_parameter"] == 0.99
    assert params["max_iterations"] == 2000


def test_verify_accept_with_outliers():
    r = _verify(_affine_scene(n_in=60, n_out=45))
    assert r["decision"]["state"] == "ACCEPT"
    assert r["evidence"]["inlier_count"] >= 55
    assert r["evidence"]["outlier_count"] >= 40
    assert r["evidence"]["inlier_ratio"] > 0.30


def test_verify_reject_random_noise():
    r = _verify(np.random.RandomState(0).uniform(0, 300, (60, 4)))
    assert r["decision"]["state"] == "REJECT"
    assert "LOW_INLIER_RATIO" in r["decision"]["reasons"] or \
        "INSUFFICIENT_INLIERS" in r["decision"]["reasons"]


def test_verify_reject_low_inlier_ratio_no_promotion():
    """A technically valid affine that fails the ratio must STAY affine: never
    promoted to homography to evade the acceptance gate."""
    inliers = _affine_scene(n_in=14, n_out=0, seed=11)
    noise = np.random.RandomState(2).uniform(0, 300, (34, 4))
    r = _verify(np.vstack([inliers, noise]))
    assert r["decision"]["state"] == "REJECT"
    assert "LOW_INLIER_RATIO" in r["decision"]["reasons"]
    assert r["evidence"]["model"]["model_type"] == "affine"


def test_verify_residual_exceeded_reject():
    # Widen the RANSAC threshold so noisy inliers land inside it, then the
    # residual median gate (5 px) fires on a REJECT — never silently accepted.
    from backend.app.trust_gate.config import (
        DecisionGateConfig,
        GeometryGateConfig,
        RansacGateConfig,
        TrustGateConfig,
    )
    from backend.app.trust_gate.engine import verify

    cfg = TrustGateConfig(
        decision=DecisionGateConfig(min_inliers=8, min_inlier_ratio=0.05,
                                    max_residual_median_px=5.0),
        geometry=GeometryGateConfig(
            models=("affine",), preferred_model="affine",
            ransac=RansacGateConfig(inlier_threshold_px=20.0),
        ),
    )
    rng = np.random.RandomState(4)
    pts = rng.uniform(20, 200, (40, 2))
    m = np.array([[1.0, 0.0, 10.0], [0.0, 1.0, 10.0], [0.0, 0.0, 1.0]])
    ha = np.hstack([pts, np.ones((40, 1))])
    b = (m @ ha.T).T[:, :2] + rng.normal(0, 14.0, (40, 2))
    coords = np.hstack([pts, b])
    r = verify(coords, cfg)
    assert r["decision"]["state"] == "REJECT"
    assert "RESIDUAL_EXCEEDED" in r["decision"]["reasons"]


def test_verify_spatial_extent_fail_rejects():
    rng = np.random.RandomState(5)
    pts = rng.uniform(50, 53, (14, 2))  # tiny 3px cluster
    coords = np.hstack([pts, pts + 0.05])
    r = _verify(coords)
    assert r["decision"]["state"] == "REJECT"
    assert "SPATIAL_SANITY_FAILED" in r["decision"]["reasons"]


def test_verify_spatial_strip_warn_accept():
    rng = np.random.RandomState(6)
    x = np.linspace(0, 200, 60)
    y = 44.5 + rng.normal(0, 0.2, 60)
    pts_a = np.column_stack([x, y])
    pts_b = pts_a + np.array([3.0, 0.5])
    r = _verify(np.column_stack([pts_a, pts_b]))
    assert r["decision"]["state"] == "ACCEPT"
    assert r["evidence"]["spatial_sanity"]["state"] == "WARN"
    assert "CONCENTRATED_STRIP" in r["evidence"]["spatial_sanity"]["reasons"]


def test_verify_homography_preferred():
    r = _verify(_homography_scene(), preferred="homography")
    assert r["decision"]["state"] == "ACCEPT"
    assert r["evidence"]["model"]["model_type"] == "homography"
    assert len(r["evidence"]["model"]["model_matrix"]) == 3


def test_verify_duplicate_counting():
    clean = _affine_scene(n_in=20, n_out=0, seed=8)
    dups = np.vstack([clean, clean[:5]])
    r = _verify(dups)
    assert r["evidence"]["exact_duplicate_count"] == 5
    assert r["evidence"]["deduplicated_candidate_count"] == 20
    assert r["evidence"]["candidate_count"] == 25
    assert r["evidence"]["source_sharing_points"] >= 1


def test_verify_determinism():
    coords = _affine_scene()
    a = _verify(coords)
    b = _verify(coords)
    assert a["decision"] == b["decision"]
    assert a["evidence"] == b["evidence"]


def test_verify_residual_units_and_stats():
    r = _verify(_affine_scene())
    stats = r["evidence"]["residual_statistics"]
    assert stats["units"] == "px in effective matcher plane"
    assert stats["count"] == r["evidence"]["inlier_count"]
    assert stats["rmse"] is not None


def test_verify_empty_residual_stats_for_abstain():
    r = _verify(np.random.RandomState(0).uniform(0, 100, (4, 4)))
    stats = r["evidence"]["residual_statistics"]
    assert stats["count"] == 0
    assert stats["median"] is None


def test_verify_identical_points_honest_abstain():
    """A batch of identical mappings collapses under dedup and cannot be turned
    into a fabricated ACCEPT."""
    pts = np.full((20, 2), 5.0)
    coords = np.hstack([pts, pts])
    r = _verify(coords)
    assert r["decision"]["state"] == "ABSTAIN"
    assert r["evidence"]["exact_duplicate_count"] == 19
    assert r["evidence"]["deduplicated_candidate_count"] == 1


# ---------------------------------------------------------------------------
# 4. artifact contract + vocabulary guard
# ---------------------------------------------------------------------------

def _minimal_payload(state="ACCEPT"):
    return {
        "run_id": "tg7-x-00000000",
        "decision": {"state": state, "reasons": [], "block_code": None,
                     "abstain_code": None},
        "evidence": {"model": None},
    }


def test_contract_valid_payload_passes():
    from backend.app.trust_gate.contract import assert_artifact_valid

    assert_artifact_valid(_minimal_payload())
    assert_artifact_valid(_minimal_payload("REJECT"))
    assert_artifact_valid(_minimal_payload("ABSTAIN"))
    assert_artifact_valid(_minimal_payload("BLOCKED"))


def test_contract_missing_decision_raises():
    from backend.app.trust_gate.contract import assert_artifact_valid

    with pytest.raises(ValueError, match="decision"):
        assert_artifact_valid({"evidence": {}})


def test_contract_bad_state_raises():
    from backend.app.trust_gate.contract import assert_artifact_valid

    with pytest.raises(ValueError, match="state"):
        assert_artifact_valid(_minimal_payload("MAYBE"))


def test_contract_vocabulary_guard_rejects_fields():
    from backend.app.trust_gate.contract import assert_artifact_vocabulary_safe

    for word in ("confidence", "final_confidence", "best", "winner", "superior"):
        nested = {"decision": {"state": "ACCEPT"}, "evidence": {word: {"x": 1}}}
        with pytest.raises(ValueError, match=word):
            assert_artifact_vocabulary_safe(nested)
        deep = {"decision": {"state": "ACCEPT", "meta": [{"inner": {word: 1}}]}}
        with pytest.raises(ValueError):
            assert_artifact_vocabulary_safe(deep)


def test_contract_confidence_parameter_ok():
    from backend.app.trust_gate.contract import assert_artifact_vocabulary_safe

    assert_artifact_vocabulary_safe({
        "decision": {"state": "ACCEPT"},
        "model": {"algorithm": "DLT_RANSAC_NUMPY_SEEDED",
                  "confidence_parameter": 0.99},
    })


# ---------------------------------------------------------------------------
# 5. service-level resolution rules (fake matcher artifacts on disk)
# ---------------------------------------------------------------------------

def _settings(tmp_path):
    from backend.app.config import Settings

    return Settings(data_root=str(tmp_path), _env_file=None)


def _write_matcher_artifact(tmp_path, *, run_id, pair_id, status="SUCCESS",
                            correspondence_count=30, with_frame=True,
                            synthetic=True, dims=(256, 256),
                            matcher_block_only=False):
    root = tmp_path / "metadata" / "m3_matching"
    root.mkdir(parents=True, exist_ok=True)
    matcher = None
    if not matcher_block_only:
        corr = []
        rng = np.random.RandomState(9)
        pts = rng.uniform(20, 200, (correspondence_count, 2))
        pts_b = pts + np.array([3.0, 0.5])
        for i in range(correspondence_count):
            corr.append({
                "x_a": float(pts[i, 0]), "y_a": float(pts[i, 1]),
                "x_b": float(pts_b[i, 0]), "y_b": float(pts_b[i, 1]),
                "score": 0.5, "descriptor_distance": 0.1,
                "match_index_a": i, "match_index_b": i,
            })
        matcher = {
            "matcher_id": "sift", "status": status,
            "candidate_match_count": len(corr),
            "correspondences": corr,
        }
    frame = {
        "effective_dimensions": {"height": dims[0], "width": dims[1]},
        "original_dimensions": {"height": dims[0] * 2, "width": dims[1] * 2},
        "resample_factor": 0.5, "resampled": True,
        "source_product": f"PRODUCT-{pair_id}-A",
        "native_dimensions": {"height": dims[0] * 2, "width": dims[1] * 2},
    } if with_frame else {}
    payload = {
        "run_id": run_id, "pair_id": pair_id, "matcher_id": "sift",
        "created_at_utc": "2026-09-23T00:00:00Z", "status": status,
        "state": status, "configuration_id": "MB-M3-001",
        "synthetically_derived": synthetic,
        "source_gate": {"data_source_gate": "PATH_B_SYNTHETIC_ONLY",
                        "source_class_a": "TEST_FIXTURE",
                        "source_class_b": "TEST_FIXTURE"},
        "input": {
            "image_a": {"sha256": "aa", **frame},
            "image_b": {"sha256": "bb", **frame},
        },
        "matcher": matcher,
    }
    (root / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_id


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


def _service(tmp_path):
    from backend.app.trust_gate.service import TrustGateService

    settings = _settings(tmp_path)
    return TrustGateService(settings)


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


def test_service_requires_registered_pair(tmp_path):
    svc = _service(tmp_path)
    from backend.app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        svc.run("CS-MISSING", matcher_run_id="m3-sift-x")


def test_service_run_without_any_matcher_artifact_404(tmp_path):
    from backend.app.errors import NotFoundError

    _registry(tmp_path)
    svc = _service(tmp_path)
    with pytest.raises(NotFoundError, match="MATCH_RUN_NOT_AVAILABLE"):
        svc.run("CS-P001")


def test_service_explicit_matcher_run_accept(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-abc12345", pair_id=rec.pair_id)
    from backend.app.trust_gate.contract import assert_artifact_valid

    svc = _service(tmp_path)
    out = svc.run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "ACCEPT"
    assert_artifact_valid(out)
    assert out["matcher_run_id"] == rid
    assert out["routing_run_id"] is None
    assert out["coordinate_count"] == 30
    assert out["reference_status"] == "REFERENCE_UNAVAILABLE"
    path = tmp_path / "metadata" / "m7_trust" / f"{out['run_id']}.json"
    assert path.is_file()


def test_service_artifact_vocabulary_and_paths(tmp_path):
    from backend.app.trust_gate.contract import assert_artifact_vocabulary_safe

    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-abc12346", pair_id=rec.pair_id)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    # any forbidden field NAME must be absent (the guard scans names, not the
    # config description that lists them); also check the decision/evidence raw
    assert_artifact_vocabulary_safe(out)
    text = json.dumps(out["decision"]) + json.dumps(out["evidence"])
    for word in ("confidence", "final_confidence", "winner", "superior"):
        assert f'"{word}"' not in text, word
    # never overwrite an existing M7 artifact
    with pytest.raises(OSError, match="overwrite"):
        _service(tmp_path).write_artifact(out["run_id"], out)


def test_service_deterministic_across_two_runs_same_matcher(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-abc12347", pair_id=rec.pair_id)
    svc = _service(tmp_path)
    a = svc.run(rec.pair_id, matcher_run_id=rid)
    b = svc.run(rec.pair_id, matcher_run_id=rid)
    assert a["decision"] == b["decision"]
    assert a["run_id"] != b["run_id"]
    assert a["decision_hash"] == b["decision_hash"]


def test_service_blocked_when_matcher_non_success(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-blk00001",
                                  pair_id=rec.pair_id, status="BLOCKED",
                                  correspondence_count=0)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "CANDIDATES_MISSING"
    assert out["errors"]


def test_service_blocked_when_candidates_missing(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-zero0001",
                                  pair_id=rec.pair_id, correspondence_count=0)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "CANDIDATES_MISSING"


def test_service_blocked_when_input_missing(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-in000001",
                                  pair_id=rec.pair_id, matcher_block_only=True)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "CANDIDATES_MISSING"


def test_service_blocked_invalid_coordinate_frame(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-fr000001",
                                  pair_id=rec.pair_id, with_frame=False)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "INVALID_COORDINATE_FRAME"
    assert "never silently" in out["decision"]["explanation"]


def test_service_status_reads_configured_and_latest(tmp_path):
    rec = _registry(tmp_path)
    svc = _service(tmp_path)
    status = svc.status(rec.pair_id)
    assert status["configured"]["configuration_id"] == "TG-M7-001"
    assert status["latest_run"] is None

    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-stat00001", pair_id=rec.pair_id)
    svc.run(rec.pair_id, matcher_run_id=rid)
    status2 = svc.status(rec.pair_id)
    assert status2["latest_run"]["state"] == "ACCEPT"
    assert "TG-M7-001" in [status2["configured"]["configuration_id"]]


def test_service_list_runs_sorted_desc(tmp_path):
    rec = _registry(tmp_path)
    svc = _service(tmp_path)
    a = _write_matcher_artifact(tmp_path, run_id="m3-sift-run00001", pair_id=rec.pair_id)
    svc.run(rec.pair_id, matcher_run_id=a)
    b = _write_matcher_artifact(tmp_path, run_id="m3-sift-run00002", pair_id=rec.pair_id)
    svc.run(rec.pair_id, matcher_run_id=b)
    rows = svc.list_runs(rec.pair_id)
    assert len(rows) == 2
    assert rows[0]["run_id"] != rows[1]["run_id"]
    assert rows[0]["created_at_utc"] >= rows[1]["created_at_utc"]
    assert rows[0]["candidate_count"] == 30


def test_service_read_unknown_run_returns_none(tmp_path):
    assert _service(tmp_path).read("tg7-does-not-exist-0000") is None


def test_service_read_safe_run_id_guard(tmp_path):
    assert _service(tmp_path).read("../etc/passwd") is None


def test_service_provenance_resolves_from_routing_run(tmp_path, monkeypatch):
    # Fake a routing artifact that dispatched matcher run rid, then verify the
    # service picks up routing_mode + routing_run_id when only the matcher run
    # is named.
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-pro000001", pair_id=rec.pair_id)

    rroot = tmp_path / "metadata" / "m6_routing"
    rroot.mkdir(parents=True, exist_ok=True)
    routing_payload = {
        "run_id": "r6-cs-p001-pro00001", "routing_run_id": "r6-cs-p001-pro00001",
        "pair_id": rec.pair_id, "mode": "FIXED_BASELINE",
        "created_at_utc": "2026-09-23T00:00:00Z",
        "execution": {
            "executed_routes": ["sift"], "final_route": "sift",
            "runs": {"sift": {"run_id": rid, "status": "SUCCESS",
                               "candidate_match_count": 30}},
        },
    }
    (rroot / "r6-cs-p001-pro00001.json").write_text(json.dumps(routing_payload), encoding="utf-8")

    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["routing_mode"] == "FIXED_BASELINE"
    assert out["routing_run_id"] == "r6-cs-p001-pro00001"
    assert "EXP-M7-FIXED_BASELINE-sift-TG-M7-001" in out["experiment_id"]


def test_service_pairs_mismatch_404(tmp_path):
    from backend.app.errors import NotFoundError

    _registry(tmp_path)
    _write_matcher_artifact(tmp_path, run_id="m3-sift-oth000001", pair_id="CS-OTHER")
    with pytest.raises(NotFoundError, match="different pair"):
        _service(tmp_path).run("CS-P001", matcher_run_id="m3-sift-oth000001")


def test_service_unknown_matcher_run_404(tmp_path):
    from backend.app.errors import NotFoundError

    _registry(tmp_path)
    with pytest.raises(NotFoundError, match="No M3/M4 matcher run"):
        _service(tmp_path).run("CS-P001", matcher_run_id="m3-sift-nope0000")


def test_real_data_blocked_by_synthetic_matcher_artifact(tmp_path, monkeypatch):
    from backend.app import pairs as pairs_module

    rec = PairRecordReal()
    rid = _write_matcher_artifact(
        tmp_path, run_id="m3-sift-real00001", pair_id=rec.pair_id,
        synthetic=True,  # artifact says synthetically derived
    )
    monkeypatch.setattr(pairs_module.PairRegistry, "get", lambda self, pid: rec)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "REAL_DATA_BLOCKED"
    assert out["errors"]


class PairRecordReal:
    pair_id = "CS-P002"
    image_a_filename = "a.img"
    image_b_filename = "b.img"
    source_class_a = "OHRC"
    source_class_b = "TMC2"
    data_source_gate = "PATH_A_REAL_DATA"
    source_gate = {"data_source_gate": "PATH_A_REAL_DATA"}


def test_real_data_allowed_when_artifact_not_synthetic(tmp_path, monkeypatch):
    from backend.app import pairs as pairs_module

    rec = PairRecordReal()
    rid = _write_matcher_artifact(
        tmp_path, run_id="m3-sift-real00002", pair_id=rec.pair_id, synthetic=False,
    )
    monkeypatch.setattr(pairs_module.PairRegistry, "get", lambda self, pid: rec)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "ACCEPT"
    assert out["decision"]["block_code"] is None


# ---------------------------------------------------------------------------
# 6. no M8 spatial selection / no M9 registration semantics
# ---------------------------------------------------------------------------

def test_artifact_has_no_m8m9_stage_keys(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-m8m900001", pair_id=rec.pair_id)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    text = json.dumps(out)
    for bad in ("selected_matcher", "spatial_reliability_map", "registered_transform",
                "overlay_rel", "registration_rmse"):
        assert bad not in text, bad
    assert "M8 spatial selection" not in out["decision"]["explanation"]
    assert "M9 registration" not in out["decision"]["explanation"]


def test_engine_output_contains_no_m8m9_concepts():
    r = _verify(_affine_scene())
    text = json.dumps(r)
    for bad in ("selected", "registered", "overlay", "reliability_map"):
        assert bad not in text, bad


# ---------------------------------------------------------------------------
# 7. end-to-end API over synthetic correlated fixtures
# ---------------------------------------------------------------------------

CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M7 trust gate API tests.",
    "products": {
        "ohrc": {"row_offset_m": 0.0, "col_offset_m": 0.0, "gsd_m": 0.5},
        "tmc2": {"row_offset_m": -2.0, "col_offset_m": -2.0, "gsd_m": 0.5},
    },
}


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
    return pair_id


def _prepare(client, pair_id):
    resp = client.post(f"/api/processing/{pair_id}/prepare", json={"geometry": CORRELATED_GEOMETRY})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_baseline(client, pair_id, matcher="sift"):
    resp = client.post(f"/api/matching/{pair_id}/baseline/run", json={"matcher": matcher})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_routing(client, pair_id, mode="FIXED_BASELINE"):
    resp = client.post(f"/api/pairs/{pair_id}/routing/run", json={"mode": mode})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_api_pair_trust_status_and_runs_empty(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    status = client.get(f"/api/pairs/{pair_id}/trust/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["configured"]["configuration_id"] == "TG-M7-001"
    assert body["latest_run"] is None
    runs = client.get(f"/api/pairs/{pair_id}/trust/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"] == []


def test_api_run_detail_unknown_404(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    detail = client.get("/api/trust/runs/tg7-nope-00000000")
    assert detail.status_code in (404, 401, 403)


def test_api_run_blocks_without_matcher_artifact(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    resp = client.post(f"/api/pairs/{pair_id}/trust/run", json={})
    assert resp.status_code == 404, resp.text
    assert "MATCH_RUN_NOT_AVAILABLE" in resp.text


def test_api_run_end_to_end_with_baseline_matcher(authed_client_factory, tmp_path):
    from backend.app.trust_gate.contract import assert_artifact_valid

    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    match = _run_baseline(client, pair_id, "sift")
    assert match["status"] == "SUCCESS", match
    matcher_run_id = match["run_id"]

    resp = client.post(f"/api/pairs/{pair_id}/trust/run",
                       json={"matcher_run_id": matcher_run_id})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["decision"]["state"] in ("ACCEPT", "REJECT", "ABSTAIN")
    assert out["matcher_run_id"] == matcher_run_id
    assert_artifact_valid(out)
    art = Path(tmp_path) / "metadata" / "m7_trust" / f"{out['run_id']}.json"
    assert art.is_file()
    disk = json.loads(art.read_text(encoding="utf-8"))
    assert disk["decision_hash"] == out["decision_hash"]


def test_api_run_via_routing_provenance(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    routing = _run_routing(client, pair_id, "FIXED_BASELINE")
    rrid = routing["routing_run_id"]
    exec_resp = client.post(f"/api/pairs/{pair_id}/routing/execute", json={"run_id": rrid})
    assert exec_resp.status_code == 200, exec_resp.text

    resp = client.post(f"/api/pairs/{pair_id}/trust/run", json={"routing_run_id": rrid})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["routing_run_id"] == rrid
    assert out["routing_mode"] == "FIXED_BASELINE"
    assert out["matcher_run_id"] in {
        run["run_id"] for run in exec_resp.json()["execution"]["runs"].values()
    }
    assert out["experiment_id"].startswith("EXP-M7-FIXED_BASELINE-")


def test_api_run_unknown_matcher_run_404(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    resp = client.post(f"/api/pairs/{pair_id}/trust/run",
                       json={"matcher_run_id": "m3-sift-doesnotexist"})
    assert resp.status_code == 404


def test_api_run_writes_blocked_candidates_missing_artifact(tmp_path):
    # Direct service-level: a SUCCESS run that produced zero candidates is
    # recorded as BLOCKED/CANDIDATES_MISSING (never an acceptance).
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-empty0001",
                                  pair_id=rec.pair_id, correspondence_count=0)
    out = _service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "CANDIDATES_MISSING"


def test_api_run_list_and_detail_after_runs(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    match = _run_baseline(client, pair_id, "sift")
    client.post(f"/api/pairs/{pair_id}/trust/run", json={"matcher_run_id": match["run_id"]})

    runs = client.get(f"/api/pairs/{pair_id}/trust/runs")
    assert runs.status_code == 200, runs.text
    rows = runs.json()["runs"]
    assert len(rows) == 1
    assert rows[0]["candidate_count"] and rows[0]["candidate_count"] > 0
    assert rows[0]["state"] in ("ACCEPT", "REJECT", "ABSTAIN")

    detail = client.get(f"/api/trust/runs/{rows[0]['run_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run_id"] == rows[0]["run_id"]
    assert body["decision"]["state"] == rows[0]["state"]
    assert body["coordinate_count"] == rows[0]["candidate_count"]


def test_api_trust_status_after_runs(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    match = _run_baseline(client, pair_id, "sift")
    client.post(f"/api/pairs/{pair_id}/trust/run", json={"matcher_run_id": match["run_id"]})
    status = client.get(f"/api/pairs/{pair_id}/trust/status")
    assert status.status_code == 200
    assert status.json()["latest_run"]["run_id"]


def test_api_run_resolves_latest_matcher_without_reading_routing(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    match = _run_baseline(client, pair_id, "sift")
    resp = client.post(f"/api/pairs/{pair_id}/trust/run", json={})  # no ids
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["matcher_run_id"] == match["run_id"]
    assert out["routing_run_id"] is None