"""M8 SPATIAL SELECTION tests.

Covers:
    * config (SR-M8-001, GRID_BALANCED, grid/bookkeeping defaults,
      forbidden vocabulary);
    * artifact contract + vocabulary guard;
    * grid cells (in-bounds, exact-boundary REPORT_ONLY, out-of-frame clip,
      occupancy counts);
    * per-side spatial analysis (coverage, concentration, entropy bounds,
      extent/centroid/spread/units) with an independent coverage recomputation
      compared to the engine's output;
    * deterministic GRID_BALANCED selection (subset proof, per-cell minimum,
      round-robin budget, residual priority, stability, limit flag);
    * pure engine decisions (INVALID_COORDINATE_FRAME block, ZERO/FEW trusted
      abstain, SELECTED / SELECTED_WITH_WARNINGS, boundary-point warning);
    * deterministic M7 trusted-set recovery (exact re-verification, hash and
      count cross-checks, refusal to re-decide) and its blocked paths;
    * service resolution + persistence (NO_TRUST_RUN / TRUST_NOT_ACCEPTED /
      REAL_DATA_BLOCKED / end-to-end SELECTED artifact, never overwrite);
    * API surface (status / runs / run / run detail, unknown and wrong-pair
      404s).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import numpy as np
import pytest

import auth_helpers  # noqa: F401
import fixturegen  # noqa: F401

from auth_helpers import AUTH_TEST_SECRET  # noqa: F401


# ---------------------------------------------------------------------------
# local synthetic fixtures (self-contained; mirrors the M7 test helpers)
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


def _write_matcher_artifact(tmp_path, *, run_id, pair_id, status="SUCCESS",
                            correspondence_count=30, with_frame=True,
                            synthetic=True, dims=(256, 256),
                            offset=(3.0, 0.5)):
    """Pure affine correspondence scene -> the M7 gate reliably ACCEPTs."""
    root = tmp_path / "metadata" / "m3_matching"
    root.mkdir(parents=True, exist_ok=True)
    corr = []
    rng = np.random.RandomState(9)
    pts = rng.uniform(20, 200, (correspondence_count, 2))
    pts_b = pts + np.asarray(offset, dtype=np.float64)
    for i in range(correspondence_count):
        corr.append({
            "x_a": float(pts[i, 0]), "y_a": float(pts[i, 1]),
            "x_b": float(pts_b[i, 0]), "y_b": float(pts_b[i, 1]),
            "score": 0.5, "descriptor_distance": 0.1,
            "match_index_a": i, "match_index_b": i,
        })
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
        "matcher": {"matcher_id": "sift", "status": status,
                    "candidate_match_count": len(corr), "correspondences": corr},
    }
    (root / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_id


def _m8cfg(**replace):
    from backend.app.spatial_m8.config import load_spatial_selection_config

    base = load_spatial_selection_config()
    return dataclasses.replace(base, **replace)


def _m8selcfg(**kw):
    from backend.app.spatial_m8.config import SelectionConfig

    base = _m8cfg().selection
    if not kw:
        return base
    return dataclasses.replace(base, **kw)


def _trusted_entries(pts, residuals=0.1, seed_offset=0):
    """Build the minimal M8 trusted entry list from an (N,4) [xa,ya,xb,yb] array."""
    return [
        {
            "m8_index": i,
            "m7_index": i,
            "match_index_a": i,
            "match_index_b": i,
            "x_a": float(pts[i, 0]), "y_a": float(pts[i, 1]),
            "x_b": float(pts[i, 2]), "y_b": float(pts[i, 3]),
            "score": 0.5, "descriptor_distance": 0.1,
            "residual": float(residuals),
        }
        for i in range(len(pts))
    ]


def _full_grid_pts(per_cell=4):
    """Deterministic points covering every cell of an 8x8 grid (dims 256)."""
    rows = []
    for r in range(8):
        for c in range(8):
            cx, cy = c * 32 + 16, r * 32 + 16
            for k in range(per_cell):
                dx, dy = (k * 3) % 12, (k * 7) % 12
                rows.append([cx + dx, cy + dy, cx + dx + 1.0, cy + dy + 1.0])
    return np.asarray(rows, dtype=np.float64)


def _trust_service(tmp_path):
    from backend.app.trust_gate.service import TrustGateService

    return TrustGateService(_settings(tmp_path))


def _spatial_service(tmp_path):
    from backend.app.spatial_m8.service import SpatialSelectionService

    return SpatialSelectionService(_settings(tmp_path))


# ---------------------------------------------------------------------------
# 1. config
# ---------------------------------------------------------------------------

def test_m8_config_loaded():
    from backend.app.spatial_m8.config import load_spatial_selection_config

    cfg = load_spatial_selection_config()
    assert cfg.configuration_id == "SR-M8-001"
    assert cfg.derived_rel == "metadata/m8_spatial"
    assert cfg.scientifically_tuned is False
    assert cfg.reference_status == "REFERENCE_UNAVAILABLE"
    assert cfg.grid.rows == 8 and cfg.grid.cols == 8
    assert cfg.grid.edge_policy == "REPORT_ONLY"
    assert cfg.selection.policy == "GRID_BALANCED"
    assert cfg.selection.max_selected == 4000
    assert cfg.selection.min_trusted == 4
    assert cfg.selection.min_selected == 1
    assert cfg.selection.min_per_occupied_cell == 1
    assert cfg.selection.min_occupied_cells == 4
    assert cfg.selection.tie_break == "residual_then_original_index"
    assert cfg.selection.limit_applied_warning is True
    assert cfg.coverage.low_coverage_ratio == 0.25
    assert cfg.coverage.concentration_ratio == 0.60
    assert cfg.execution.max_runtime_seconds == 60


def test_m8_config_forbidden_vocabulary():
    from backend.app.spatial_m8.config import SpatialSelectionConfig

    forbidden = SpatialSelectionConfig().forbidden_vocabulary
    for word in ("confidence", "final_confidence", "best", "winner", "superior"):
        assert word in forbidden


# ---------------------------------------------------------------------------
# 2. contract + vocabulary guard
# ---------------------------------------------------------------------------

def test_m8_contract_valid_payload_passes():
    from backend.app.spatial_m8.contract import assert_artifact_valid

    payload = {
        "run_id": "m8s-cs-p001-123",
        "decision": {
            "state": "SELECTED_WITH_WARNINGS", "reasons": ["LOW_SOURCE_COVERAGE"],
            "explanation": "spatial bookkeeping only", "block_code": None,
            "abstain_code": None,
        },
    }
    assert_artifact_valid(payload)


def test_m8_contract_missing_decision_raises():
    from backend.app.spatial_m8.contract import assert_artifact_valid

    with pytest.raises(ValueError, match="decision"):
        assert_artifact_valid({"run_id": "x"})


def test_m8_contract_bad_state_raises():
    from backend.app.spatial_m8.contract import assert_artifact_valid

    with pytest.raises(ValueError, match="state"):
        assert_artifact_valid({"decision": {"state": "GUESSED"}})


def test_m8_contract_vocabulary_guard_rejects_fields():
    from backend.app.spatial_m8.contract import assert_artifact_vocabulary_safe

    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SELECTED"}, "confidence": 0.9})
    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SELECTED"}, "best": "extent"})
    with pytest.raises(ValueError, match="Forbidden vocabulary"):
        assert_artifact_vocabulary_safe({"decision": {"state": "SELECTED"}, "nested": {"winner": 1}})


# ---------------------------------------------------------------------------
# 3. grid
# ---------------------------------------------------------------------------

def test_grid_cell_for_point_bounds():
    from backend.app.spatial_m8.grid import cell_for_point

    assert cell_for_point(16.0, 16.0, 256, 256, 8, 8) == (0, 0, False)
    assert cell_for_point(255.9, 255.9, 256, 256, 8, 8) == (7, 7, False)
    assert cell_for_point(32.0, 32.0, 256, 256, 8, 8) == (1, 1, False)
    assert cell_for_point(256.0, 256.0, 256, 256, 8, 8) == (7, 7, True)


def test_grid_exact_boundary_reported_but_clipped():
    from backend.app.spatial_m8.grid import cell_for_point

    r, c, out = cell_for_point(256.0, 128.0, 256, 256, 8, 8)
    assert (r, c) == (4, 7)
    assert out is True


def test_grid_out_of_frame_flags_and_clip():
    from backend.app.spatial_m8.grid import cell_for_point

    r, c, out = cell_for_point(-5.0, 10.0, 256, 256, 8, 8)
    assert (r, c) == (0, 0)
    assert out is True
    r, c, out = cell_for_point(float("nan"), 10.0, 256, 256, 8, 8)
    assert out is True
    r, c, out = cell_for_point(256.0, 256.0, 256, 256, 8, 8)
    assert out is True


def test_grid_counts_occupancy_matches_point_positions():
    from backend.app.spatial_m8.config import load_spatial_selection_config
    from backend.app.spatial_m8.grid import grid_counts

    grid = load_spatial_selection_config().grid
    pts = np.array([[16, 16], [48, 48], [256, 48], [16, 300]], dtype=np.float64)
    res = grid_counts(pts, 256, 256, grid)
    occ = res["occupancy"]
    assert occ[0, 0] == 1          # 16,16
    assert occ[1, 1] == 1          # 48,48
    assert occ[1, 7] == 1          # (256,48) clipped into last column
    assert occ[7, 0] == 1          # (16,300) clipped into last row
    assert sum(res["edge_flags"]) == 2
    assert occ.sum() == 4
    assert res["rows"] == 8 and res["cols"] == 8
    assert res["edge_policy"] == "REPORT_ONLY"


# ---------------------------------------------------------------------------
# 4. per-side spatial analysis (+ independent coverage recomputation)
# ---------------------------------------------------------------------------

def test_spatial_analysis_metrics_units():
    from backend.app.spatial_m8.analysis import spatial_analysis

    from backend.app.spatial_m8.config import load_spatial_selection_config

    cfg = load_spatial_selection_config()
    pts = _full_grid_pts(1)
    occ = grid_occ(pts)  # consistent with the point count
    dims = {"height": 256, "width": 256}
    blk = spatial_analysis(pts[:, :2], pts[:, 2:], occ, occ, dims, dims, cfg.coverage)
    for side in ("a", "b"):
        b = blk[side]
        assert b["count"] == len(pts) == int(occ.sum())
        assert b["total_cells"] == 64
        assert 0.0 <= b["coverage_ratio"] <= 1.0
        assert b["concentration_ratio"] is not None
        assert 0.0 <= b["concentration_ratio"] <= 1.0
        assert b["entropy_normalized"] is None or 0.0 <= b["entropy_normalized"] <= 1.0
        assert b["extent"]["span_x_px"] >= 0
        assert b["centroid"]["x"] is not None
        assert b["spread"]["std_x_px"] is not None
        assert b["units"] == "px in effective matcher plane"


def test_spatial_analysis_concentration_flag():
    from backend.app.spatial_m8.analysis import spatial_analysis
    from backend.app.spatial_m8.config import load_spatial_selection_config

    cfg = load_spatial_selection_config()
    pts = np.array([[30.0, 30.0], [31.0, 31.0], [32.0, 32.0], [33.0, 33.0],
                    [34.0, 34.0], [35.0, 35.0]], dtype=np.float64)
    occ = np.zeros((8, 8), dtype=np.int64)
    occ[0, 0] = 6
    dims = {"height": 256, "width": 256}
    blk = spatial_analysis(pts, pts, occ, occ, dims, dims, cfg.coverage)["a"]
    assert blk["concentration_ratio"] == 1.0
    assert blk["coverage_ratio"] == 1.0 / 64.0
    assert blk["occupied_cells"] == 1


def test_spatial_analysis_low_coverage_detection():
    from backend.app.spatial_m8.config import load_spatial_selection_config
    from backend.app.spatial_m8.engine import analyze_and_select

    cfg = load_spatial_selection_config()
    corner = np.array([[10.0, 10.0], [11.0, 11.0], [12.0, 12.0], [13.0, 13.0],
                       [14.0, 14.0], [15.0, 15.0]], dtype=np.float64)
    pts = np.hstack([corner, corner + 1.0])
    dims = {"height": 256, "width": 256}
    out = analyze_and_select(_trusted_entries(pts), dims, dims, cfg)
    assert out["decision"]["state"] == "SELECTED_WITH_WARNINGS"
    assert "LOW_SOURCE_COVERAGE" in out["decision"]["reasons"]

    # independent recomputation of coverage (8x8 grid, 32 px cells)
    def coverage_of(pts2):
        touched = set()
        for p in pts2:
            touched.add((int(p[1] // 32), int(p[0] // 32)))
        return len(touched) / 64.0

    blk = out["evidence"]["analysis"]["a"]
    assert abs(blk["coverage_ratio"] - coverage_of(pts[:, :2])) < 1e-9


def test_spatial_analysis_entropy_degenerate_uniform():
    from backend.app.spatial_m8.analysis import _normalized_entropy

    assert _normalized_entropy(np.array([[5]]), 5) is None          # one cell used
    assert _normalized_entropy(np.array([[0, 0]]), 0) is None       # empty
    two = _normalized_entropy(np.array([[5, 5]]), 10)               # two cells, p=0.5
    assert two is not None and 0.0 < two <= 1.0


def test_spatial_analysis_determinism():
    from backend.app.spatial_m8.analysis import spatial_analysis
    from backend.app.spatial_m8.config import load_spatial_selection_config

    cfg = load_spatial_selection_config()
    pts = _full_grid_pts(2)
    occ = grid_occ(pts)
    dims = {"height": 256, "width": 256}
    a = spatial_analysis(pts[:, :2], pts[:, 2:], occ, occ, dims, dims, cfg.coverage)
    b = spatial_analysis(pts[:, :2], pts[:, 2:], occ, occ, dims, dims, cfg.coverage)
    assert a == b


def grid_occ(pts):
    import numpy as np

    occ = np.zeros((8, 8), dtype=np.int64)
    for p in pts:
        occ[int(p[1] // 32), int(p[0] // 32)] += 1
    return occ


# ---------------------------------------------------------------------------
# 5. deterministic GRID_BALANCED selection
# ---------------------------------------------------------------------------

def _spread_entries(n=200, per_cell=1):
    """Entries spread so selection must exercise the round-robin budget."""
    pts = _full_grid_pts(per_cell)[:n]
    entries = _trusted_entries(pts)
    k = len(entries)
    for i in range(k):
        entries[i]["source_cell"] = (int(pts[i, 1] // 32), int(pts[i, 0] // 32))
    return entries


def test_select_balanced_subset_of_inputs():
    from backend.app.spatial_m8.selection import select_balanced

    entries = _trusted_entries(_full_grid_pts(2))
    for e in entries:
        e["source_cell"] = (int(e["y_a"] // 32), int(e["x_a"] // 32))
    sel = select_balanced(entries, _m8selcfg())
    picked = {e["m8_index"] for e in entries if e["m8_index"] in set(sel["selected"])}
    assert picked == set(sel["selected"])
    assert sel["state"] == "SELECTED"


def test_select_balanced_min_per_occupied_cell():
    from backend.app.spatial_m8.selection import select_balanced

    entries = _spread_entries(64, per_cell=16)  # 4 occupied cells x 16 points
    sel = select_balanced(entries, _m8selcfg(min_per_occupied_cell=4, min_trusted=1,
                                             max_selected=40, limit_applied_warning=True))
    cells = {}
    for e in entries:
        cell = tuple(e["source_cell"])
        cells.setdefault(cell, []).append(e["m8_index"])
    assert len(cells) == 4
    for cell, idxs in cells.items():
        picked = sum(1 for i in sel["selected"] if i in idxs)
        assert picked >= 4, cell


def test_select_balanced_never_exceeds_budget_round_robin():
    from backend.app.spatial_m8.selection import select_balanced

    entries = _spread_entries(256, per_cell=4)
    assert len({tuple(e["source_cell"]) for e in entries}) == 64
    sel = select_balanced(entries, _m8selcfg(min_trusted=1, max_selected=40,
                                             min_per_occupied_cell=1))
    assert len(sel["selected"]) <= 40
    assert sel["limit_applied"] is True
    assert len(sel["selected"]) == 40


def test_select_balanced_residual_priority_within_cell():
    from backend.app.spatial_m8.selection import select_balanced

    pts = _full_grid_pts(4)[:8]
    entries = _trusted_entries(pts)
    for i, e in enumerate(entries):
        e["residual"] = float(8 - i)  # descending; lowest residual is index 7
        e["source_cell"] = (0, 0)
    sel = select_balanced(entries, _m8selcfg(min_trusted=1, max_selected=1,
                                             min_per_occupied_cell=1, limit_applied_warning=True))
    assert sel["selected"] == [7]


def test_select_balanced_stability_and_limits():
    from backend.app.spatial_m8.selection import select_balanced

    entries = _spread_entries(256, per_cell=4)
    cfg = _m8selcfg(min_trusted=1, max_selected=120, min_per_occupied_cell=1)
    a = select_balanced(entries, cfg)
    b = select_balanced(entries, cfg)
    assert a == b
    assert a["policy"] == "GRID_BALANCED"
    assert a["tie_break"] == "residual_then_original_index"
    assert a["max_selected"] == 120


def test_select_balanced_limit_not_applied_within_budget():
    from backend.app.spatial_m8.selection import select_balanced

    entries = _trusted_entries(_full_grid_pts(1)[:16])
    sel = select_balanced(entries, _m8selcfg(min_trusted=1, max_selected=4000))
    assert sel["limit_applied"] is False
    assert len(sel["selected"]) == 16
    assert sel["excluded"] == []


# ---------------------------------------------------------------------------
# 6. pure engine decisions
# ---------------------------------------------------------------------------

def test_engine_invalid_dimensions_blocked():
    from backend.app.spatial_m8.engine import analyze_and_select

    cfg = _m8cfg()
    out = analyze_and_select(_trusted_entries(_full_grid_pts(1)),
                             {"height": 0, "width": 256}, {"height": 256, "width": 256}, cfg)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "INVALID_COORDINATE_FRAME"


def test_engine_zero_trusted_abstain():
    from backend.app.spatial_m8.engine import analyze_and_select

    dims = {"height": 256, "width": 256}
    out = analyze_and_select([], dims, dims, _m8cfg())
    assert out["decision"]["state"] == "ABSTAIN"
    assert out["decision"]["abstain_code"] == "ZERO_TRUSTED"


def test_engine_few_trusted_abstain():
    from backend.app.spatial_m8.engine import analyze_and_select

    pts = np.array([[16, 16, 17, 17], [48, 48, 49, 49], [80, 80, 81, 81]], dtype=np.float64)
    dims = {"height": 256, "width": 256}
    out = analyze_and_select(_trusted_entries(pts), dims, dims, _m8cfg())
    assert out["decision"]["state"] == "ABSTAIN"
    assert out["decision"]["abstain_code"] == "FEW_TRUSTED"


def test_engine_selected_state_and_subset_proof():
    from backend.app.spatial_m8.engine import analyze_and_select
    from backend.app.spatial_m8.config import load_spatial_selection_config

    pts = _full_grid_pts(4)
    entries = _trusted_entries(pts)
    dims = {"height": 256, "width": 256}
    out = analyze_and_select(entries, dims, dims, load_spatial_selection_config())
    assert out["decision"]["state"] in ("SELECTED", "SELECTED_WITH_WARNINGS")
    selected = out["evidence"]["selection_record"]["selected"]
    trust_xy = {(round(e["x_a"], 6), round(e["y_a"], 6)) for e in entries}
    for s in selected:
        assert (round(s["x_a"], 6), round(s["y_a"], 6)) in trust_xy
        assert 0 <= s["m7_index"] < len(entries)
    assert len(selected) == out["evidence"]["selected_count"]
    m8s = [s["m8_index"] for s in selected]
    assert len(set(m8s)) == len(m8s)
    assert out["evidence"]["excluded_count"] == len(entries) - len(selected)
    assert out["evidence"]["trusted_count"] == len(entries)


def test_engine_warnings_recorded_and_state_tone():
    from backend.app.spatial_m8.engine import analyze_and_select

    corner = np.array([[10, 10, 11, 11], [12, 12, 13, 13], [14, 14, 15, 15],
                       [16, 16, 17, 17], [18, 18, 19, 19], [20, 20, 21, 21]],
                      dtype=np.float64)
    dims = {"height": 256, "width": 256}
    out = analyze_and_select(_trusted_entries(corner), dims, dims, _m8cfg())
    assert out["decision"]["state"] == "SELECTED_WITH_WARNINGS"
    assert "FEW_OCCUPIED_CELLS" in out["decision"]["reasons"]
    assert "CONCENTRATED_SOURCE" in out["decision"]["reasons"]
    assert out["warnings"] == list(dict.fromkeys(out["warnings"]))
    from backend.app.spatial_m8.states import tone

    assert tone(out["decision"]["state"]) == "warn"


def test_engine_boundary_points_reported_warning():
    from backend.app.spatial_m8.engine import analyze_and_select

    pts = _full_grid_pts(1)[:12]
    pts2 = np.vstack([pts, [[-8.0, 130.0, -8.0, 130.0]]])  # outside frame on side A
    dims = {"height": 256, "width": 256}
    out = analyze_and_select(_trusted_entries(pts2), dims, dims, _m8cfg())
    assert out["decision"]["state"] == "SELECTED_WITH_WARNINGS"
    assert "BOUNDARY_POINTS_REPORTED" in out["decision"]["reasons"]


def test_engine_determinism_frame_and_units():
    from backend.app.spatial_m8.engine import analyze_and_select

    pts = _full_grid_pts(3)
    dims = {"height": 256, "width": 256}
    cfg = _m8cfg()
    a = analyze_and_select(_trusted_entries(pts), dims, dims, cfg)
    b = analyze_and_select(_trusted_entries(pts), dims, dims, cfg)
    assert a["decision"] == b["decision"]
    assert a["evidence"] == b["evidence"]
    frame = a["evidence"]["frame"]
    assert frame["frame"] == "EFFECTIVE_MATCHER_PLANE"
    assert frame["side_a"]["effective_dimensions"] == dims
    assert a["evidence"]["analysis"]["a"]["units"] == "px in effective matcher plane"


# ---------------------------------------------------------------------------
# 7. deterministic M7 trusted-set recovery
# ---------------------------------------------------------------------------

def _run_m7_accept(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-rec0001",
                                  pair_id=rec.pair_id, correspondence_count=90)
    trust = _trust_service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    assert trust["decision"]["state"] == "ACCEPT"
    payload = json.loads(
        (Path(tmp_path) / "metadata" / "m3_matching" / f"{rid}.json").read_text(encoding="utf-8")
    )
    return trust, payload


def test_recovery_accept_ok_and_deterministic(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    trust, payload = _run_m7_accept(tmp_path)
    r1 = recover_trusted(trust, payload)
    r2 = recover_trusted(trust, payload)
    assert r1["state"] == "RECOVERY_OK"
    assert r1 == r2
    assert len(r1["trusted"]) > 0


def test_recovery_reproduces_m7_inlier_residuals(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    trust, payload = _run_m7_accept(tmp_path)
    rec = recover_trusted(trust, payload)
    assert rec["state"] == "RECOVERY_OK"
    threshold = trust["configuration"]["geometry"]["ransac"]["inlier_threshold_px"]
    for e in rec["trusted"]:
        assert float(e["residual"]) < float(threshold)
        orig = payload["matcher"]["correspondences"][e["m7_index"]]
        assert abs(e["x_a"] - orig["x_a"]) < 1e-9
        assert abs(e["x_b"] - orig["x_b"]) < 1e-9
        assert e["match_index_a"] == orig["match_index_a"]
    assert len(rec["trusted"]) == trust["evidence"]["inlier_count"]
    assert rec["dims_a"]["height"] == 256
    assert rec["dims_b"]["width"] == 256


def test_recovery_non_accept_blocked(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    trust, _ = _run_m7_accept(tmp_path)
    tampered = json.loads(json.dumps(trust))
    tampered["decision"]["state"] = "REJECT"
    rec = recover_trusted(tampered, {"matcher": {}})
    assert rec["state"] == "BLOCKED"
    assert rec["decision"]["block_code"] == "TRUST_NOT_ACCEPTED"


def test_recovery_tampered_decision_hash_blocked(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-tamper01", pair_id="CS-P001")
    trust = _trust_service(tmp_path).run("CS-P001", matcher_run_id=rid)
    payload = json.loads(
        (Path(tmp_path) / "metadata" / "m3_matching" / f"{rid}.json").read_text(encoding="utf-8")
    )
    tampered = json.loads(json.dumps(trust))
    tampered["decision_hash"] = tampered["decision_hash"][:-1] + ("0" if tampered["decision_hash"][-1] != "0" else "1")
    rec = recover_trusted(tampered, payload)
    assert rec["state"] == "BLOCKED"
    assert rec["decision"]["block_code"] == "NONDETERMINISTIC_RECOVERY"


def test_recovery_tampered_inlier_count_blocked(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-tamper02", pair_id="CS-P001")
    trust = _trust_service(tmp_path).run("CS-P001", matcher_run_id=rid)
    payload = json.loads(
        (Path(tmp_path) / "metadata" / "m3_matching" / f"{rid}.json").read_text(encoding="utf-8")
    )
    tampered = json.loads(json.dumps(trust))
    tampered["evidence"]["inlier_count"] = tampered["evidence"]["inlier_count"] + 1
    rec = recover_trusted(tampered, payload)
    assert rec["state"] == "BLOCKED"
    assert rec["decision"]["block_code"] == "NONDETERMINISTIC_RECOVERY"


def test_recovery_missing_frame_blocked(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-noframe1", pair_id="CS-P001")
    trust = _trust_service(tmp_path).run("CS-P001", matcher_run_id=rid)
    payload = json.loads(
        (Path(tmp_path) / "metadata" / "m3_matching" / f"{rid}.json").read_text(encoding="utf-8")
    )
    del payload["input"]["image_a"]["effective_dimensions"]
    rec = recover_trusted(trust, payload)
    assert rec["state"] == "BLOCKED"
    assert rec["decision"]["block_code"] == "INVALID_COORDINATE_FRAME"


def test_recovery_missing_correspondences_blocked(tmp_path):
    from backend.app.spatial_m8.recovery import recover_trusted

    _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-nocorr01", pair_id="CS-P001")
    trust = _trust_service(tmp_path).run("CS-P001", matcher_run_id=rid)
    assert trust["decision"]["state"] == "ACCEPT"
    payload = json.loads(
        (Path(tmp_path) / "metadata" / "m3_matching" / f"{rid}.json").read_text(encoding="utf-8")
    )
    del payload["matcher"]["correspondences"]
    payload["matcher"]["candidate_match_count"] = 0
    rec = recover_trusted(trust, payload)
    assert rec["state"] == "BLOCKED"
    assert rec["decision"]["block_code"] == "MATCH_RUN_UNRECOVERABLE"


# ---------------------------------------------------------------------------
# 8. service resolution + persistence
# ---------------------------------------------------------------------------

def _write_trust_artifact(tmp_path, run_id, pair_id, state="REJECT", matcher_run_id=None):
    root = Path(tmp_path) / "metadata" / "m7_trust"
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id, "trust_run_id": run_id, "pair_id": pair_id,
        "matcher_run_id": matcher_run_id or "m3-sift-blah",
        "decision": {
            "state": state, "reasons": [state],
            "explanation": "synthetic non-accept trust artifact",
            "block_code": None, "abstain_code": None,
        },
        "configuration_id": "TG-M7-001",
        "configuration": {"configuration_id": "TG-M7-001"},
    }
    (root / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")
    return run_id


def test_service_requires_registered_pair(tmp_path):
    from backend.app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        _spatial_service(tmp_path).run("CS-NOPE")


def test_service_no_trust_run_records_blocked(tmp_path):
    _registry(tmp_path)
    out = _spatial_service(tmp_path).run("CS-P001")
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "NO_TRUST_RUN"
    path = tmp_path / "metadata" / "m8_spatial" / f"{out['run_id']}.json"
    assert path.is_file()


def test_service_non_accept_trust_blocked(tmp_path):
    _registry(tmp_path)
    rid = _write_trust_artifact(tmp_path, "tg7-CS-P001-reject01", "CS-P001", "REJECT")
    out = _spatial_service(tmp_path).run("CS-P001", trust_run_id=rid)
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "TRUST_NOT_ACCEPTED"


def test_service_end_to_end_selected_persisted(tmp_path):
    from backend.app.spatial_m8.contract import assert_artifact_valid

    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-e2e0001",
                                  pair_id=rec.pair_id, correspondence_count=120)
    trust = _trust_service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    out = _spatial_service(tmp_path).run(rec.pair_id, trust_run_id=trust["run_id"])
    assert out["decision"]["state"] in ("SELECTED", "SELECTED_WITH_WARNINGS")
    assert_artifact_valid(out)
    path = tmp_path / "metadata" / "m8_spatial" / f"{out['run_id']}.json"
    assert path.is_file()
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["decision_hash"] == out["decision_hash"]
    assert disk["trust_run_id"] == trust["run_id"]
    assert disk["matcher_run_id"] == rid

    # selected set is a strict subset of the M7 trusted set (by coordinates)
    payload = json.loads(
        (Path(tmp_path) / "metadata" / "m3_matching" / f"{rid}.json").read_text(encoding="utf-8")
    )
    trust_xy = {(round(c["x_a"], 6), round(c["y_a"], 6)) for c in payload["matcher"]["correspondences"]}
    for s in out["evidence"]["selection_record"]["selected"]:
        assert (round(s["x_a"], 6), round(s["y_a"], 6)) in trust_xy
    assert out["evidence"]["selected_count"] > 0
    assert out["evidence"]["selected_count"] <= out["evidence"]["trusted_count"]


def test_service_vocabulary_safe_and_no_overwrite(tmp_path):
    from backend.app.spatial_m8.contract import assert_artifact_vocabulary_safe

    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-vocab001", pair_id=rec.pair_id)
    trust = _trust_service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    svc = _spatial_service(tmp_path)
    out = svc.run(rec.pair_id, trust_run_id=trust["run_id"])
    assert_artifact_vocabulary_safe(out)
    text = json.dumps(out["decision"]) + json.dumps(out["evidence"])
    for word in ("confidence", "final_confidence", "best", "winner", "superior"):
        assert f'"{word}"' not in text, word
    with pytest.raises(OSError, match="overwrite"):
        svc.write_artifact(out["run_id"], out)


def test_service_deterministic_across_two_runs(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-det0001", pair_id=rec.pair_id)
    trust = _trust_service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    svc = _spatial_service(tmp_path)
    a = svc.run(rec.pair_id, trust_run_id=trust["run_id"])
    b = svc.run(rec.pair_id, trust_run_id=trust["run_id"])
    assert a["run_id"] != b["run_id"]
    assert a["decision_hash"] == b["decision_hash"]
    assert a["decision"] == b["decision"]
    assert a["evidence"]["selection_record"] == b["evidence"]["selection_record"]


def test_service_explicit_unknown_trust_run_404(tmp_path):
    from backend.app.errors import NotFoundError

    _registry(tmp_path)
    with pytest.raises(NotFoundError, match="trust gate run"):
        _spatial_service(tmp_path).run("CS-P001", trust_run_id="tg7-nope-000000")


def test_service_explicit_trust_wrong_pair_404(tmp_path):
    from backend.app.errors import NotFoundError

    _registry(tmp_path)
    _write_trust_artifact(tmp_path, "tg7-CS-P002-other", "CS-P002", "ACCEPT")
    with pytest.raises(NotFoundError, match="different pair"):
        _spatial_service(tmp_path).run("CS-P001", trust_run_id="tg7-CS-P002-other")


def test_service_real_data_gate_blocked(tmp_path, monkeypatch):
    from backend.app import pairs as pairs_module
    from backend.app.spatial_m8.service import _synthetic_like

    class _RealRec:
        pair_id = "CS-P002"
        source_class_a = "OHRC"
        source_class_b = "TMC2"
        data_source_gate = "PATH_A_REAL_DATA"

    rec = _RealRec()
    assert _synthetic_like(rec) is False
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-real01",
                                  pair_id="CS-P002", synthetic=True)
    monkeypatch.setattr(pairs_module.PairRegistry, "get", lambda self, pid: rec)
    trust = _trust_service(tmp_path).run("CS-P002", matcher_run_id=rid)
    assert trust["decision"]["state"] == "BLOCKED"
    out = _spatial_service(tmp_path).run("CS-P002", trust_run_id=trust["run_id"])
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] in ("TRUST_NOT_ACCEPTED", "REAL_DATA_BLOCKED")


def test_service_status_shape_and_list_runs(tmp_path):
    rec = _registry(tmp_path)
    svc = _spatial_service(tmp_path)
    status = svc.status(rec.pair_id)
    assert status["configured"]["configuration_id"] == "SR-M8-001"
    assert status["configured"]["policy"] == "GRID_BALANCED"
    assert status["configured"]["grid_rows"] == 8
    assert status["latest_run"] is None
    assert svc.list_runs(rec.pair_id) == []

    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-list001", pair_id=rec.pair_id)
    trust = _trust_service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    svc.run(rec.pair_id, trust_run_id=trust["run_id"])
    runs = svc.list_runs(rec.pair_id)
    assert len(runs) == 1
    row = runs[0]
    assert row["pair_id"] == rec.pair_id
    assert row["state"] in ("SELECTED", "SELECTED_WITH_WARNINGS")
    assert row["trusted_count"] and row["selected_count"] and row["trusted_count"] > 0
    assert row["configuration_id"] == "SR-M8-001"
    assert svc.read(row["run_id"]) is not None


def test_service_read_safe_runid_guard(tmp_path):
    svc = _spatial_service(tmp_path)
    assert svc.read("../etc/passwd") is None
    assert svc.read("m8s-cs-p001:not!") is None


def test_service_provenance_chain_and_experiment(tmp_path):
    rec = _registry(tmp_path)
    rid = _write_matcher_artifact(tmp_path, run_id="m3-sift-prov001", pair_id=rec.pair_id)
    trust = _trust_service(tmp_path).run(rec.pair_id, matcher_run_id=rid)
    out = _spatial_service(tmp_path).run(rec.pair_id, trust_run_id=trust["run_id"])
    prov = out["provenance"]
    assert prov["m7_run"] == trust["run_id"]
    assert prov["m3_or_m4_run"] == rid
    assert prov["m8_run"] == out["run_id"]
    assert out["experiment_id"].startswith("EXP-M8-")
    assert "M8 spatial selection" in prov["chain"]


# ---------------------------------------------------------------------------
# 9. end-to-end API over synthetic correlated fixtures
# ---------------------------------------------------------------------------

CORRELATED_GEOMETRY = {
    "source": "TEST_FIXTURE",
    "reference": "Synthetic correlated scene for M8 spatial selection API tests.",
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


def test_api_spatial_status_and_runs_empty(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    status = client.get(f"/api/pairs/{pair_id}/spatial-m8/status")
    assert status.status_code == 200, status.text
    body = status.json()
    assert body["configured"]["configuration_id"] == "SR-M8-001"
    assert body["latest_run"] is None
    runs = client.get(f"/api/pairs/{pair_id}/spatial-m8/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"] == []


def test_api_run_detail_unknown_404(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    detail = client.get("/api/spatial-m8/runs/m8s-nope-00000000")
    assert detail.status_code in (404, 401, 403)


def test_api_run_without_trust_records_blocked(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    resp = client.post(f"/api/pairs/{pair_id}/spatial-m8/run", json={})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["decision"]["state"] == "BLOCKED"
    assert out["decision"]["block_code"] == "NO_TRUST_RUN"


def test_api_run_unknown_trust404(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    resp = client.post(f"/api/pairs/{pair_id}/spatial-m8/run",
                       json={"trust_run_id": "tg7-doesnotexist"})
    assert resp.status_code == 404


def test_api_run_end_to_end_and_list_detail(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    match = _run_baseline(client, pair_id, "sift")
    assert match["status"] == "SUCCESS", match

    trust = client.post(f"/api/pairs/{pair_id}/trust/run",
                        json={"matcher_run_id": match["run_id"]})
    assert trust.status_code == 200, trust.text
    trust_out = trust.json()

    resp = client.post(f"/api/pairs/{pair_id}/spatial-m8/run",
                       json={"trust_run_id": trust_out["run_id"]})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    if trust_out["decision"]["state"] == "ACCEPT":
        assert out["decision"]["state"] in ("SELECTED", "SELECTED_WITH_WARNINGS",
                                            "ABSTAIN", "BLOCKED")
    else:
        assert out["decision"]["state"] == "BLOCKED"
        assert out["decision"]["block_code"] == "TRUST_NOT_ACCEPTED"
    art = Path(tmp_path) / "metadata" / "m8_spatial" / f"{out['run_id']}.json"
    assert art.is_file()

    runs = client.get(f"/api/pairs/{pair_id}/spatial-m8/runs")
    assert runs.status_code == 200
    rows = runs.json()["runs"]
    assert len(rows) == 1
    assert rows[0]["run_id"] == out["run_id"]

    detail = client.get(f"/api/spatial-m8/runs/{out['run_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["run_id"] == out["run_id"]
    assert body["decision"]["state"] == out["decision"]["state"]
    if out["decision"]["state"] in ("SELECTED", "SELECTED_WITH_WARNINGS"):
        text = json.dumps(body["decision"]) + json.dumps(body["evidence"])
        for word in ("confidence", "final_confidence", "winner", "superior"):
            assert f'"{word}"' not in text, word


def test_api_status_after_runs(authed_client_factory, tmp_path):
    fixturegen.write_correlated_fixtures(tmp_path)
    client = authed_client_factory(data_root=str(tmp_path))
    pair_id = _register(client)
    _prepare(client, pair_id)
    match = _run_baseline(client, pair_id, "sift")
    trust = client.post(f"/api/pairs/{pair_id}/trust/run",
                        json={"matcher_run_id": match["run_id"]})
    trust_out = trust.json()
    client.post(f"/api/pairs/{pair_id}/spatial-m8/run",
                json={"trust_run_id": trust_out["run_id"]})
    status = client.get(f"/api/pairs/{pair_id}/spatial-m8/status")
    assert status.status_code == 200
    assert status.json()["latest_run"]["run_id"]