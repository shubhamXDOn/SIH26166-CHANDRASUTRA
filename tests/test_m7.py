"""M7 tests — Quantitative Metrics, Reproducible Experiment Reports & Scientific Diagnostics.

Covers MT-M7-001 configuration, canonical metric schema/taxonomy, the evidence
funnel, spatial/registration metric reads, independent recomputation (and
mismatch detection), deterministic experiment identity, deterministic reports,
provenance (M2->M7) + manifest, comparison (no ranking), full lifecycle through
the real M2->M3->M4->M5->M6->M7 pipeline, reset isolation, honest
BLOCKED/INSUFFICIENT states, forbidden-terminology guards and the API surface.

All fixtures are synthetic and labelled as such; no scientific claim is made.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import fixturegen  # noqa: F401
import test_m6 as m6h

from auth_helpers import authed_client_for_app, configure_auth

PA, PB = "CS-P001", "CS-P002"
PC, MK, TG, SR, RG = m6h.PC, m6h.MK, m6h.TG, m6h.SR, m6h.RG
MT = "MT-M7-001"


# ---------------------------------------------------------------------------
# harness helpers
# ---------------------------------------------------------------------------

def _m7_harness(settings_factory):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app
    from fastapi.testclient import TestClient

    tmp = Path(tempfile.mkdtemp(prefix="cs_m7_"))
    fixturegen.write_correlated_fixtures(tmp)
    settings = Settings(data_root=str(tmp), _env_file=None)
    ensure_derived_directories(settings)
    configure_auth(settings)
    app = create_app(settings=settings)
    return authed_client_for_app(app), settings, tmp


def _get_m7_svc(tmp):
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    from backend.app.metrics.service import MetricsService
    return MetricsService(
        tmp, m7_cfg=m7_config(), m6_cfg=m6_config(),
        m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])


def _get_m6_svc(tmp):
    from backend.app.config import m4_config, m5_config, m6_config
    from backend.app.registration.service import RegistrationService
    return RegistrationService(
        tmp, m6_cfg=m6_config(), m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])


def _ready_for_m7(settings, pair_id=PA, **kw):
    """Build M2..M5 tree and run M6 to COMPLETE."""
    tmp = m6h._build_m6_ready_tree(settings, pair_id, **kw)
    status = _get_m6_svc(tmp).run(pair_id)
    assert status["state"] == "COMPLETE", status
    return tmp


def _run_m7(tmp, pair_id=PA):
    svc = _get_m7_svc(tmp)
    status = svc.run(pair_id)
    assert status["state"] == "COMPLETE", status
    return svc


def _metric(svc, pair_id, metric_id):
    return svc.metric_by_id(pair_id, metric_id)


# ===========================================================================
# 1. configuration
# ===========================================================================

def test_m7_configuration_registered():
    from backend.app.config import m7_config
    cfg = m7_config()
    assert cfg["metrics_configuration_id"] == MT
    assert int(cfg["metrics_configuration_version"]) == 1
    assert cfg["scientifically_tuned"] is False
    d = cfg["defaults"]
    assert d["rejected"]["scientifically_tuned"] is False
    assert d["recompute"]["scientifically_tuned"] is False
    assert d["recompute"]["enabled"] is True
    assert float(d["recompute"]["consistency_tolerance"]) == pytest.approx(1e-3)
    assert int(d["execution"]["max_runtime_seconds"]) == 60


def test_m7_config_loader_from_defaults():
    from backend.app.config import m7_config
    from backend.app.metrics.config import MetricsConfig
    cfg = MetricsConfig.from_dict(m7_config()["defaults"])
    assert cfg.metrics_configuration_id == MT
    assert cfg.rejected.inlier_ratio_minimum == pytest.approx(0.3)
    assert cfg.recompute.inlier_threshold_px == pytest.approx(3.0)
    assert cfg.scientifically_tuned is False


def test_m7_config_coercion():
    from backend.app.metrics.config import MetricsConfig
    raw = {
        "rejected": {"inlier_ratio_minimum": "0.4", "residual_mean_max_px": "8.5"},
        "recompute": {"inlier_threshold_px": "2.5", "consistency_tolerance": "1e-4"},
        "execution": {"max_runtime_seconds": "30"},
    }
    cfg = MetricsConfig.from_dict(raw)
    assert cfg.rejected.inlier_ratio_minimum == pytest.approx(0.4)
    assert cfg.rejected.residual_mean_max_px == pytest.approx(8.5)
    assert cfg.recompute.inlier_threshold_px == pytest.approx(2.5)
    assert cfg.recompute.consistency_tolerance == pytest.approx(1e-4)
    assert cfg.execution["max_runtime_seconds"] == "30"


def test_m7_configuration_endpoint(settings_factory):
    client, _s, _t = _m7_harness(settings_factory)
    with client:
        body = client.get("/api/metrics/configurations").json()
        assert body["default_metrics_configuration_id"] == MT
        conf = body["configurations"][0]
        assert conf["metrics_configuration_id"] == MT
        assert conf["scientifically_tuned"] is False
        assert body["valid_metrics_configuration_ids"] == [MT]
        assert "no scientifically tuned" in body["note"]


def test_m7_health_meta_includes_m7_config():
    from fastapi.testclient import TestClient as TC
    from backend.app.main import app
    with TC(app) as c:
        meta = c.get("/api/meta").json()
        assert meta["m7_config"]["metrics_configuration_id"] == MT
        assert meta["milestone"] == "M10"


def test_m7_state_vocabulary():
    from backend.app.metrics.states import (
        FORBIDDEN_TERMINOLOGY,
        MetricCategory,
        MetricStatus,
        MetricsBlockCode,
        MetricsRunState,
        ScientificStatus,
    )
    assert MetricsRunState.COMPLETE.value == "COMPLETE"
    assert MetricsRunState.INSUFFICIENT.value == "INSUFFICIENT"
    assert MetricsBlockCode.M6_NOT_AVAILABLE.value == "M6_NOT_AVAILABLE"
    assert MetricStatus.REFERENCE_UNAVAILABLE.value == "REFERENCE_UNAVAILABLE"
    assert MetricCategory.REFERENCE.value == "REFERENCE"
    assert ScientificStatus.NOT_SCIENTIFIC.value == "NOT_SCIENTIFIC"
    for token in ("overall_accuracy", "scientific_confidence", "registration_confidence",
                  "alignment_score", "lunar_accuracy", "geolocation_accuracy", "ce90", "le90"):
        assert token in FORBIDDEN_TERMINOLOGY


# ===========================================================================
# 2. schema / taxonomy
# ===========================================================================

def test_metric_record_required_keys():
    from backend.app.metrics.schema import metric, as_records
    from backend.app.metrics.states import MetricCategory, ScientificStatus
    rec = metric("X", "x", 1, "count", MetricCategory.OBSERVATION, "M3", None,
                 "m", "i", ScientificStatus.ENGINEERING)
    for key in ("metric_id", "name", "value", "unit", "category", "source_milestone",
                "source_artifact", "calculation_method", "interpretation",
                "scientific_status", "status"):
        assert key in rec
    assert rec["status"] == "AVAILABLE"
    with pytest.raises(ValueError):
        as_records([{"metric_id": "X"}])


def test_unavailable_metric_value_is_none_not_zero():
    from backend.app.metrics.schema import unavailable_metric
    from backend.app.metrics.states import MetricCategory, MetricStatus
    rec = unavailable_metric("X", "x", "count", MetricCategory.MEASUREMENT, "M6", None,
                             "m", "i", MetricStatus.BLOCKED)
    assert rec["value"] is None
    assert rec["value"] != 0
    assert rec["scientific_status"] == "NOT_SCIENTIFIC"
    assert rec["status"] == "BLOCKED"


def test_forbidden_terminology_rejected():
    from backend.app.metrics.schema import assert_no_forbidden_terminology, metric
    from backend.app.metrics.states import MetricCategory, ScientificStatus
    with pytest.raises(ValueError):
        metric("alignment_score", "x", 1, None, MetricCategory.MEASUREMENT, "M6", None,
               "m", "i", ScientificStatus.MEASUREMENT)
    with pytest.raises(ValueError):
        assert_no_forbidden_terminology({"note": "this is a CE90 result"})
    assert_no_forbidden_terminology({"note": "clean engineering measurement"})


def test_taxonomy_covers_produced_metrics(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        from backend.app.metrics.taxonomy import TAXONOMY
        produced = {m["metric_id"] for m in svc.metrics(PA)}
        assert produced <= set(TAXONOMY)
        assert "PHYSICAL_ACCURACY" in produced
        assert "RECOMPUTE_MISMATCH" in produced


# ===========================================================================
# 3. full lifecycle + funnel + spatial + registration
# ===========================================================================

def test_m7_full_lifecycle_complete(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        status = svc.read_status(PA)
        assert status["state"] == "COMPLETE"
        summary = svc.summary(PA)
        assert summary["state"] == "COMPLETE"
        assert summary["metrics_configuration_id"] == MT
        assert summary["metrics_total"] > 0
        assert summary["metrics_available"] > 0
        assert summary["reference_dataset"] == "NOT_AVAILABLE"
        assert summary["recomputation_consistent"] is True


def test_funnel_counts_and_retention(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        m3 = _metric(svc, PA, "FUNNEL_M3_CANDIDATES")["value"]
        m4 = _metric(svc, PA, "FUNNEL_M4_TRUSTED_CORRESPONDENCES")["value"]
        m5 = _metric(svc, PA, "FUNNEL_M5_SELECTED_CORRESPONDENCES")["value"]
        m6 = _metric(svc, PA, "FUNNEL_M6_REGISTERED_CORRESPONDENCES")["value"]
        assert m3 and m3 > 0
        assert m4 and m4 > 0
        assert m5 and m5 > 0
        assert m6 and m6 > 0
        r34 = _metric(svc, PA, "FUNNEL_M3_TO_M4_RETENTION")
        assert r34["status"] == "AVAILABLE"
        assert r34["value"] == pytest.approx(m4 / m3, rel=1e-6)
        r56 = _metric(svc, PA, "FUNNEL_M5_TO_M6_RETENTION")
        assert r56["value"] == pytest.approx(m6 / m5, rel=1e-6)


def test_spatial_metrics_read_from_m5(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        rows = _metric(svc, PA, "SPATIAL_GRID_ROWS")
        cols = _metric(svc, PA, "SPATIAL_GRID_COLS")
        assert rows["value"] == 8 and cols["value"] == 8
        assert rows["source_artifact"].endswith("/summary.json")
        outcome = _metric(svc, PA, "SPATIAL_SELECTION_OUTCOME")
        assert outcome["value"] in ("SELECTED", "INSUFFICIENT")


def test_registration_metrics_read_from_m6(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        for mid in ("REG_INLIERS", "REG_RESIDUAL_MEAN_PX", "REG_VALIDATION_VERDICT",
                    "REG_TRANSFORM_TYPE", "REG_INLIER_RATIO"):
            m = _metric(svc, PA, mid)
            assert m.get("error") != "NOT_FOUND"
            assert m["source_milestone"] == "M6"
        resid = _metric(svc, PA, "REG_RESIDUAL_MEAN_PX")
        assert resid["value"] is not None and resid["value"] >= 0


def test_physical_accuracy_never_numeric(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        phys = _metric(svc, PA, "PHYSICAL_ACCURACY")
        assert phys["value"] is None
        assert phys["value"] not in (0, 100, 1.0)
        assert phys["status"] == "REFERENCE_UNAVAILABLE"
        assert phys["category"] == "REFERENCE"
        avail = _metric(svc, PA, "PHYSICAL_TRUTH_AVAILABLE")
        assert avail["value"] is None
        assert avail["status"] == "REFERENCE_UNAVAILABLE"


# ===========================================================================
# 4. independent recomputation
# ===========================================================================

def test_recomputation_consistent_with_fit(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        rec = _metric(svc, PA, "RECOMPUTE_RESIDUAL_MEAN_PX")
        assert rec["value"] is not None
        assert rec["source_milestone"] == "M7"
        assert svc.summary(PA)["recomputation_consistent"] is True
        assert _metric(svc, PA, "RECOMPUTE_MISMATCH")["status"] == "NOT_APPLICABLE"


def test_recomputation_mismatch_detected(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        _run_m7(tmp)
        # Tamper the recorded diagnostics so recomputation must disagree.
        m6_run = _get_m6_svc(tmp).find_run_for_pair(PA)
        diag_path = Path(m6_run) / "diagnostics.json"
        diag = json.loads(diag_path.read_text(encoding="utf-8"))
        diag["residuals"]["mean_px"] = 9999.0
        diag_path.write_text(json.dumps(diag, indent=2), encoding="utf-8")
        svc = _get_m7_svc(tmp)
        svc.run(PA)
        assert svc.summary(PA)["recomputation_consistent"] is False
        mismatch = _metric(svc, PA, "RECOMPUTE_MISMATCH")
        assert mismatch["status"] == "AVAILABLE"
        assert mismatch["value"]


# ===========================================================================
# 5. experiment identity + report determinism
# ===========================================================================

def test_experiment_identity_deterministic(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        first = svc.experiment(PA)["experiment_id"]
        svc.run(PA)
        second = svc.experiment(PA)["experiment_id"]
        assert first == second
        assert first.startswith("EXP-") and len(first) == 16


def test_experiment_seed_excludes_config_path(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        seed = svc.experiment(PA)["seed"]
        assert "source" not in seed["configuration_chain"]
        assert seed["experiment_policy"]["reference_dataset"] == "NOT_AVAILABLE"


def test_report_markdown_deterministic_and_no_timestamp(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        md1 = svc.report_markdown(PA)
        svc.run(PA)
        md2 = svc.report_markdown(PA)
        assert md1 == md2
        assert "CHANDRASUTRA M7" in md1
        assert "physical_accuracy: NOT_AVAILABLE" in md1
        for token in ("overall_accuracy", "alignment_score", "ce90", "le90"):
            assert token not in md1.lower()


def test_report_json_has_metrics_and_recompute(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        report = svc.report_json(PA)
        assert report["schema_version"] == "1.0"
        assert report["experiment_id"]
        assert len(report["metrics"]) > 0
        assert report["recompute"]["recomputed"] is True
        assert report["validation"]["metrics_total"] == len(report["metrics"])


# ===========================================================================
# 6. provenance + manifest
# ===========================================================================

def test_provenance_chain_m2_to_m7(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        prov = svc.provenance(PA)
        milestones = [n["milestone"] for n in prov["chain"]]
        assert milestones == ["M2", "M3", "M4", "M5", "M6", "M7"]
        m7_node = prov["chain"][-1]
        assert m7_node["configuration_id"] == MT
        blob = json.dumps(prov)
        assert str(tmp) not in blob
        assert "C:\\" not in blob


def test_manifest_records_sha256(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        man = svc.manifest(PA)
        assert man["metrics_configuration_id"] == MT
        kinds = {a["kind"] for a in man["artifacts"]}
        assert {"experiment", "summary", "report_json", "report_markdown"} <= kinds
        for a in man["artifacts"]:
            assert len(a["sha256"]) == 64
            assert not a["path"].startswith("/")
            assert ".." not in a["path"]


# ===========================================================================
# 7. comparison
# ===========================================================================

def test_comparison_has_no_ranking_or_winner(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings, pair_id=PA)
        _run_m7(tmp, PA)
        # Compare PA against a pair with no run (empty metrics): the engine must
        # remain descriptive and never rank or declare a winner.
        comp = _get_m7_svc(tmp).comparison(PA, PB)
        assert "winner" not in comp
        assert "ranking" not in comp
        assert "rank" not in comp
        for row in comp["rows"]:
            assert "rank" not in row
            assert "winner" not in row
            assert "is_better" not in row
        assert "No ranking and no winner" in comp["note"]
        assert comp["pair_a"] == PA and comp["pair_b"] == PB
        assert comp["metrics_compared"] > 0
        assert comp["metrics_only_in_b"] == 0


# ===========================================================================
# 8. blocked / insufficient states
# ===========================================================================

def test_blocked_without_m6(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        pair_id = m6h._register(client)
        m6h._prepare(client, pair_id)
        m6h._run_m3(client, pair_id)
        svc = _get_m7_svc(tmp)
        status = svc.run(pair_id, MT)
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "M6_NOT_AVAILABLE"
        assert svc.metrics(pair_id) == []


def test_blocked_when_m6_not_complete(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        m6h._build_full_tree(settings, PA)
        # M6 exists but never run -> no status
        svc = _get_m7_svc(tmp)
        status = svc.run(PA, MT)
        assert status["state"] == "BLOCKED"


def test_unknown_metrics_configuration_blocked(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        status = _get_m7_svc(tmp).run(PA, "MT-M7-999")
        assert status["state"] == "BLOCKED"
        assert status["block_code"] == "METRICS_UNKNOWN_CONFIG"


# ===========================================================================
# 9. reset isolation
# ===========================================================================

def test_reset_removes_only_metrics(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        m6_run = Path(_get_m6_svc(tmp).find_run_for_pair(PA))
        m5_run = m6_run.parents[2]
        assert m6_run.is_dir() and m5_run.is_dir()
        svc.reset(PA)
        assert svc.read_status(PA)["state"] == "NOT_STARTED"
        assert m6_run.is_dir()
        assert m5_run.is_dir()


# ===========================================================================
# 10. API surface
# ===========================================================================

def _api_ready(client, settings):
    pair_id = m6h._register(client)
    m6h._prepare(client, pair_id)
    m6h._run_m3(client, pair_id)
    return pair_id


def test_api_full_lifecycle(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        assert m6h._register(client) == PA
        assert client.post(f"/api/metrics/{PA}/run", json={}).json()["state"] == "COMPLETE"
        assert client.get(f"/api/metrics/{PA}/status").json()["state"] == "COMPLETE"
        summary = client.get(f"/api/metrics/{PA}/summary").json()
        assert summary["summary"]["metrics_total"] > 0
        metrics = client.get(f"/api/metrics/{PA}/metrics").json()
        assert metrics["count"] > 0
        one = client.get(f"/api/metrics/{PA}/metrics/REG_RESIDUAL_MEAN_PX").json()
        assert one["metric"]["metric_id"] == "REG_RESIDUAL_MEAN_PX"
        assert client.get(f"/api/metrics/{PA}/experiment").json()["experiment"]["experiment_id"]
        assert client.get(f"/api/metrics/{PA}/report").json()["report"]["metrics"]
        md = client.get(f"/api/metrics/{PA}/report/markdown")
        assert md.status_code == 200 and "CHANDRASUTRA M7" in md.text
        assert client.get(f"/api/metrics/{PA}/provenance").json()["provenance"]["chain"]
        assert client.get(f"/api/metrics/{PA}/manifest").json()["manifest"]["artifacts"]


def test_api_unknown_pair_404(settings_factory):
    client, _s, _t = _m7_harness(settings_factory)
    with client:
        assert client.get("/api/metrics/CS-P999/status").status_code == 404
        assert client.post("/api/metrics/CS-P999/run", json={}).status_code == 404
        assert client.get("/api/metrics/CS-P999/summary").status_code == 404
        assert client.get("/api/metrics/CS-P999/metrics").status_code == 404


def test_api_unknown_metric_404(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        client.post(f"/api/metrics/{PA}/run", json={})
        assert client.get(f"/api/metrics/{PA}/metrics/NOPE").status_code == 404


def test_api_comparison_requires_pairs(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        client.post(f"/api/metrics/{PA}/run", json={})
        resp = client.get(f"/api/metrics/comparison?pair_a={PA}&pair_b=CS-P999")
        assert resp.status_code == 404


def test_api_overview_honest(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        m6h._register(client)
        client.post(f"/api/metrics/{PA}/run", json={})
        overview = client.get("/api/metrics/overview").json()
        assert overview["total_metrics_pairs"] == 1
        assert overview["complete_pairs"] == 1
        assert overview["not_complete_pairs"] == 0


# ===========================================================================
# 11. bug-hunt corpus
# ===========================================================================

def test_b01_status_is_not_started_before_run(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        assert _get_m7_svc(tmp).read_status(PA)["state"] == "NOT_STARTED"


def test_b02_metrics_empty_before_run(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        assert _get_m7_svc(tmp).metrics(PA) == []


def test_b03_summary_missing_before_run(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        assert _get_m7_svc(tmp).summary(PA).get("error") == "NOT_FOUND"


def test_b04_markdown_missing_before_run(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        with pytest.raises(FileNotFoundError):
            _get_m7_svc(tmp).report_markdown(PA)


def test_b05_blocked_run_writes_no_metrics(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        pair_id = m6h._register(client)
        m6h._prepare(client, pair_id)
        m6h._run_m3(client, pair_id)
        svc = _get_m7_svc(tmp)
        svc.run(pair_id, MT)
        assert svc.metrics(pair_id) == []


def test_b06_recompute_handles_clean_tree(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        rec = _metric(svc, PA, "RECOMPUTE_INLIER_COUNT")
        assert rec["status"] in ("AVAILABLE", "NOT_APPLICABLE")


def test_b07_metric_values_are_json_finite(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        blob = json.dumps(svc.metrics(PA))
        assert "Infinity" not in blob
        assert "NaN" not in blob


def test_b08_two_runs_are_stable(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        snap1 = {(m["metric_id"]): m["value"] for m in svc.metrics(PA)}
        svc.run(PA)
        snap2 = {(m["metric_id"]): m["value"] for m in svc.metrics(PA)}
        assert snap1 == snap2


def test_b09_reset_idempotent(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        svc.reset(PA)
        svc.reset(PA)
        assert svc.read_status(PA)["state"] == "NOT_STARTED"


def test_b10_forbidden_terminology_fails_run(monkeypatch, settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        import backend.app.metrics.service as svc_mod
        import backend.app.metrics.funnel as funnel_mod
        from backend.app.metrics.schema import metric
        from backend.app.metrics.states import MetricCategory, ScientificStatus

        def _bad(*a, **k):
            return [metric("alignment_score", "bad", 1, None, MetricCategory.MEASUREMENT,
                           "M6", None, "m", "i", ScientificStatus.MEASUREMENT)]

        monkeypatch.setattr(funnel_mod, "collect_funnel_metrics", _bad)
        monkeypatch.setattr(svc_mod, "collect_funnel_metrics", _bad)
        monkeypatch.setattr(svc_mod, "collect_spatial_metrics", lambda *a, **k: [])
        monkeypatch.setattr(svc_mod, "collect_registration_metrics", lambda *a, **k: [])
        status = _get_m7_svc(tmp).run(PA, MT)
        assert status["state"] == "FAILED"
        assert status["block_code"] == "FORBIDDEN_TERMINOLOGY"


def test_b11_manifest_paths_are_relative_posix(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        man = _run_m7(tmp).manifest(PA)
        for a in man["artifacts"]:
            assert a["path"].startswith("derived/metrics/")
            assert "\\" not in a["path"]


def test_b12_provenance_artifacts_have_no_nulls(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        prov = _run_m7(tmp).provenance(PA)
        for node in prov["chain"]:
            for a in node["artifacts"]:
                assert a is not None
                assert "sha256" in a and len(a["sha256"]) == 64


def test_b13_experiment_seed_changes_with_inputs(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        svc = _run_m7(tmp)
        first = svc.experiment(PA)["experiment_id"]
        m6_run = Path(_get_m6_svc(tmp).find_run_for_pair(PA))
        tpath = m6_run / "transform.json"
        t = json.loads(tpath.read_text(encoding="utf-8"))
        t["transform_type"] = "AFFINE"
        tpath.write_text(json.dumps(t, indent=2), encoding="utf-8")
        svc.run(PA)
        assert svc.experiment(PA)["experiment_id"] != first


def test_b14_no_absolute_paths_in_report(settings_factory):
    client, settings, tmp = _m7_harness(settings_factory)
    with client:
        _ready_for_m7(settings)
        report = _run_m7(tmp).report_json(PA)
        blob = json.dumps(report)
        assert "C:\\" not in blob
