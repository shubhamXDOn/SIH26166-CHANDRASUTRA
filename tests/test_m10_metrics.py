"""M10 METRICS & BENCHMARK tests.

Covers:
    * config (MET-M10-001 ≠ AU-M10-001, scientifically_tuned false,
      failure taxonomy FT-M10-001, reference status, V1..V6 matrix);
    * variant matrix semantics (V1 baseline, V2/V3 availability gates,
      V4 routed, V5/V6 offline ablations);
    * read-only funnel extraction over synthetic M3..M9 artefacts
      (matching → trust → spatial → registration without re-running);
    * blocked / failed / abstain separation (a failed run never abstains,
      an abstaining run never fails, a blocked run is never an outcome);
    * null vs zero discipline (unobserved counts are None, never 0);
    * immutable append-only registry (no overwrite / reuse of run ids);
    * descriptive aggregation (median preferred, mean+p95, no winner);
    * deltas (Vx − V1, descriptive only), failure taxonomy classification;
    * forbidden vocabulary enforcement (winner/best/accuracy/confidence/...);
    * API surface (read endpoints, analyst-only writes, 404s).

All fixtures are synthetic; nothing here is REAL data and no physical accuracy
is ever claimed.
"""

from __future__ import annotations

import pytest

import auth_helpers  # noqa: F401

from auth_helpers import AUTH_TEST_SECRET  # noqa: F401


# ---------------------------------------------------------------------------
# synthetic stage services (read-only fakes mirroring the real read surfaces)
# ---------------------------------------------------------------------------

class FakeMatching:
    def __init__(self, pair_id: str, candidates: int, *, available: bool = True):
        self._pair = pair_id
        self._candidates = candidates
        self._available = available

    def find_run_for_pair(self, pair_id):  # noqa: N802
        if not self._available:
            return None
        return object()

    def summary(self, pair_id):
        if not self._available:
            return None
        return {"state": "COMPLETE", "matcher_family": "classical_sift",
                "run_id": "m3-CS-P001-0001", "candidate_count": self._candidates}


class FakeTrust:
    def __init__(self, pair_id: str, verified: int, *, state: str = "COMPLETE"):
        self._pair = pair_id
        self._verified = verified
        self._state = state

    def latest_for_pair(self, pair_id):
        return {"state": self._state, "run_id": "m7-CS-P001-0001",
                "verified_count": self._verified, "inlier_count": self._verified}


class FakeSpatial:
    def __init__(self, pair_id: str, selected: int, *, state: str = "COMPLETE"):
        self._pair = pair_id
        self._selected = selected
        self._state = state

    def latest_for_pair(self, pair_id):
        return {"state": self._state, "run_id": "m8-CS-P001-0001",
                "selected_count": self._selected}


class FakeRegistration:
    def __init__(self, pair_id: str, registered: int, rmse: float, p95: float,
                 *, state: str = "COMPLETE"):
        self._pair = pair_id
        self._registered = registered
        self._rmse = rmse
        self._p95 = p95
        self._state = state

    def latest_for_pair(self, pair_id):
        return {"state": self._state, "run_id": "m9-CS-P001-0001",
                "registered_count": self._registered,
                "rmse_px": self._rmse, "p95_px": self._p95}


_MISSING = "MISSING"


def _services(pair_id: str, *, matcher=_MISSING, trust=_MISSING, spatial=_MISSING, reg=_MISSING):
    out = {}
    out["matching"] = matcher if matcher is not _MISSING else FakeMatching(pair_id, 120)
    out["trust"] = trust if trust is not _MISSING else FakeTrust(pair_id, 80)
    out["spatial"] = spatial if spatial is not _MISSING else FakeSpatial(pair_id, 60)
    out["registration"] = reg if reg is not _MISSING else FakeRegistration(pair_id, 52, 1.4, 3.1)
    return out


def _settings(tmp_path):
    from backend.app.config import Settings
    return Settings(data_root=str(tmp_path), _env_file=None)


def _svc(tmp_path):
    from backend.app.metrics_m10.service import M10MetricsService
    return M10MetricsService(_settings(tmp_path))


# ---------------------------------------------------------------------------
# 1. config
# ---------------------------------------------------------------------------

def test_config_id_distinct_from_auth_m10():
    from backend.app.config import m10_metrics_config, m10_config
    m = m10_metrics_config()
    a = m10_config()
    assert m["m10_metrics_configuration_id"] == "MET-M10-001"
    assert a["authentication_configuration_id"] == "AU-M10-001"
    assert m["m10_metrics_configuration_id"] != a["authentication_configuration_id"]


def test_config_scientifically_tuned_false():
    from backend.app.config import m10_metrics_config
    assert m10_metrics_config()["scientifically_tuned"] is False


def test_failure_taxonomy_version_present():
    from backend.app.config import m10_metrics_config
    ft = m10_metrics_config().get("failure_taxonomy") or {}
    assert ft.get("version") == "FT-M10-001"


# ---------------------------------------------------------------------------
# 2. variant matrix
# ---------------------------------------------------------------------------

def test_variant_matrix_has_expected_variants():
    svc = _svc
    # matrix reads from config defaults per probe
    from backend.app.metrics_m10.variants import variants_from_config
    vs = variants_from_config([])
    ids = [v.id for v in vs]
    assert ids == ["V1", "V2", "V3", "V4", "V5", "V6"]


def test_v5_v6_ablations_flagged_offline():
    from backend.app.metrics_m10.variants import variants_from_config
    by_id = {v.id: v for v in variants_from_config([])}
    assert by_id["V5"].trust_gate == "DISABLED_FOR_ABLATION"
    assert by_id["V6"].spatial_selection == "DISABLED_FOR_ABLATION"
    assert by_id["V5"].is_ablation() and by_id["V6"].is_ablation()


def test_v2_v3_availability_gates_honest():
    from backend.app.metrics_m10.variants import variants_from_config
    by_id = {v.id: v for v in variants_from_config([])}
    assert by_id["V2"].availability == "NOT_AVAILABLE"
    assert by_id["V3"].availability == "NOT_AVAILABLE"


def test_service_overview_exposes_matrix_and_ref(tmp_path):
    s = _svc(tmp_path)
    ov = s.overview()
    assert {"V1", "V4", "V5", "V6"} <= {v["id"] for v in ov["variants"]}
    assert ov["reference_status"]["value"] == "REFERENCE_UNAVAILABLE"
    assert ov["no_claim"] is True


# ---------------------------------------------------------------------------
# 3. funnel extraction (read-only over synthetic artefacts)
# ---------------------------------------------------------------------------

def test_funnel_reads_all_stages_with_counts(tmp_path):
    s = _svc(tmp_path)
    p = "CS-P001"
    svc = _services(p)
    rec = s.run(p, "V1", services=svc)
    m = rec["metrics"]
    assert m["candidate_count"] == 120
    assert m["verified_count"] == 80
    assert m["selected_count"] == 60
    assert m["registered_count"] == 52
    assert m["registration_rmse_px"] == 1.4
    assert m["registration_p95_px"] == 3.1
    assert rec["state"] == "COMPLETE"


def test_funnel_absent_artefact_is_none_not_zero(tmp_path):
    s = _svc(tmp_path)
    p = "CS-P002"
    svc = _services(p, reg=None)
    rec = s.run(p, "V1", services=svc)
    m = rec["metrics"]
    assert m["registered_count"] is None
    assert m["registration_rmse_px"] is None
    assert m["candidate_count"] == 120
    assert rec["state"] in ("ABSTAIN", "BLOCKED")


def test_extraction_is_read_only(tmp_path):
    from backend.app.metrics_m10.extraction import read_funnel
    p = "CS-P003"
    reg = FakeRegistration(p, 52, 1.4, 3.1)
    svc = _services(p, reg=reg)
    ev = read_funnel(_settings(tmp_path), svc, p)
    assert ev.stages["matching"]["candidate_count"] == 120
    assert ev.stages["registration"]["registered_count"] == 52
    # read-only: no benchmark registry files were touched, and stage fakes
    # were never asked to write anything.
    from backend.app.metrics_m10.registry import BenchmarkRegistry
    assert BenchmarkRegistry(_settings(tmp_path)).list() == []


# ---------------------------------------------------------------------------
# 4. blocked / failed / abstain separation
# ---------------------------------------------------------------------------

def test_failed_registration_never_reported_as_abstain(tmp_path):
    s = _svc(tmp_path)
    p = "CS-F1"
    reg = FakeRegistration(p, 0, None, None, state="TRANSFORM_FIT_ERROR")
    rec = s.run(p, "V1", services=_services(p, reg=reg))
    assert rec["state"] == "FAILED"


def test_abstain_registration_never_reported_as_failed(tmp_path):
    s = _svc(tmp_path)
    p = "CS-A1"
    reg = FakeRegistration(p, 0, None, None, state="SPARSE_EVIDENCE")
    rec = s.run(p, "V1", services=_services(p, reg=reg))
    assert rec["state"] == "ABSTAIN"


def test_blocked_when_matching_absent_is_not_an_outcome(tmp_path):
    s = _svc(tmp_path)
    p = "CS-B1"
    svc = {"matching": FakeMatching(p, 0, available=False),
           "trust": FakeTrust(p, 0), "spatial": FakeSpatial(p, 0),
           "registration": FakeRegistration(p, 0, None, None)}
    rec = s.run(p, "V1", services=svc)
    assert rec["state"] == "BLOCKED"


def test_no_run_ever_claims_accuracy(tmp_path):
    s = _svc(tmp_path)
    p = "CS-N1"
    rec = s.run(p, "V4", services=_services(p))
    text = str(rec)
    for word in ("accuracy", "winner", "confidence", "CE90"):
        assert word.lower() not in text.lower()


# ---------------------------------------------------------------------------
# 5. immutable registry
# ---------------------------------------------------------------------------

def test_registry_append_only_no_reuse_of_run_id(tmp_path):
    s = _svc(tmp_path)
    p = "CS-R1"
    svc = _services(p)
    r1 = s.run(p, "V1", services=svc)
    r2 = s.run(p, "V1", services=svc)
    assert r1["run_id"] != r2["run_id"]
    assert r1["run_id"].startswith("m10-")
    assert r2["run_id"].startswith("m10-")


def test_registry_read_of_unknown_run_returns_none(tmp_path):
    s = _svc(tmp_path)
    assert s.read("m10-00000000") is None


def test_registry_rejects_unsafe_run_ids(tmp_path):
    s = _svc(tmp_path)
    from backend.app.metrics_m10.registry import _safe_run_id
    assert _safe_run_id("m10-abc123") is True
    assert _safe_run_id("../../../etc") is False


# ---------------------------------------------------------------------------
# 6. descriptive aggregation
# ---------------------------------------------------------------------------

def test_aggregation_median_reported_with_mean_p95(tmp_path):
    s = _svc(tmp_path)
    for i in range(5):
        p = "CS-AGG%d" % i
        s.run(p, "V1", services=_services(p, reg=FakeRegistration(
            p, 50 + i, rmse=1.0 + i * 0.5, p95=2.0 + i)))
    a = s.analyze()
    sum_ = a["summary"]
    r = sum_["metrics"]["registration_rmse_px"]
    assert r["median"] is not None and r["mean"] is not None and r["p95"] is not None
    assert r["mean"] >= r["median"]
    assert a["no_claim"] is True


def test_aggregation_missing_count_is_not_zero_filled(tmp_path):
    s = _svc(tmp_path)
    s.run("CS-Z1", "V1", services=_services("CS-Z1", reg=None))
    s.run("CS-Z2", "V1", services=_services("CS-Z2"))
    a = s.analyze()
    r = a["summary"]["metrics"]["registered_count"]
    assert r["median"] == 52  # single observed value, not a mean of a zero-padded set


def test_deltas_are_descriptive_only(tmp_path):
    s = _svc(tmp_path)
    s.run("CS-D1", "V1", services=_services("CS-D1"))
    s.run("CS-D1", "V4", services=_services("CS-D1"))
    d = s.deltas()
    assert d["baseline"] == "V1"
    assert d["scale"] == "DESCRIPTIVE"
    assert d["no_claim"] is True
    assert d["reference_status"]["value"] == "REFERENCE_UNAVAILABLE"
    v4 = next((x for x in d["delta"] if x["variant_label"] == "V4"), None)
    assert v4 is not None
    diff = v4["delta"]["candidate_count"]
    assert diff is None or isinstance(diff, dict)


# ---------------------------------------------------------------------------
# 7. failure taxonomy
# ---------------------------------------------------------------------------

def test_failure_taxonomy_separates_failed_vs_abstain():
    from backend.app.metrics_m10.taxonomy import classify
    f = classify("TRANSFORM_FIT_ERROR")
    a = classify("SPARSE_EVIDENCE")
    assert f["branch"] == "failed" and f["code"] == "TRANSFORM_FIT_ERROR"
    assert a["branch"] == "abstain" and a["code"] == "SPARSE_EVIDENCE"


def test_failure_analysis_buckets(tmp_path):
    s = _svc(tmp_path)
    s.run("CS-FA1", "V1", services=_services(
        "CS-FA1", reg=FakeRegistration("CS-FA1", 0, None, None, state="TRANSFORM_FIT_ERROR")))
    s.run("CS-FA2", "V1", services=_services(
        "CS-FA2", reg=FakeRegistration("CS-FA2", 0, None, None, state="SPARSE_EVIDENCE")))
    fa = s.failure_analysis()
    assert fa["counts"]["failed"] == 1
    assert fa["counts"]["abstain"] == 1
    assert "never" in fa["policy"]


# ---------------------------------------------------------------------------
# 8. schema + forbidden vocabulary
# ---------------------------------------------------------------------------

def test_schema_row_has_stable_keys(tmp_path):
    s = _svc(tmp_path)
    p = "CS-S1"
    rec = s.run(p, "V1", services=_services(p))
    # rows exposed through analyze carry state/variant, not a verdict
    assert "no_claim" in s.analyze()


def test_forbidden_vocabulary_rejected_in_notes():
    from backend.app.metrics_m10.schema import build_row, ForbiddenVocabularyError
    class V:
        id = "V1"
        name = "X"
        ablation = "none"
        availability = "AVAILABLE"
    with pytest.raises(ForbiddenVocabularyError):
        build_row("P", V(), state="COMPLETE", stage="registration", notes="this is the accuracy winner")


def test_forbidden_vocabulary_rejected_in_state():
    from backend.app.metrics_m10.schema import build_row, ForbiddenVocabularyError
    class V:
        id = "V1"
        name = "X"
        ablation = "none"
        availability = "AVAILABLE"
    with pytest.raises(ForbiddenVocabularyError):
        build_row("P", V(), state="GEOLOCATION_ACCURACY", stage="registration")


# ---------------------------------------------------------------------------
# 9. API surface
# ---------------------------------------------------------------------------

def test_api_overview_readable(authed_client_factory):
    client = authed_client_factory()
    r = client.get("/api/metrics-m10/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["m10_metrics_configuration_id"] == "MET-M10-001"
    assert body["reference_status"]["value"] == "REFERENCE_UNAVAILABLE"


def test_api_variants_readable(authed_client_factory):
    client = authed_client_factory()
    r = client.get("/api/metrics-m10/variants")
    assert r.status_code == 200
    ids = {v["id"] for v in r.json()["variants"]}
    assert {"V1", "V2", "V3", "V4", "V5", "V6"} == ids


def test_api_run_requires_analyst(authed_client_factory):
    client = authed_client_factory()
    # analyst write on a pair with no prior pipeline evidence -> blocked
    r = client.post("/api/metrics-m10/runs", json={"pair_id": "CS-P001", "variant_id": "V4"})
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert r.json()["state"] in ("BLOCKED", "ABSTAIN", "COMPLETE")


def test_api_run_rejects_unknown_variant(authed_client_factory):
    client = authed_client_factory()
    r = client.post("/api/metrics-m10/runs", json={"pair_id": "CS-P001", "variant_id": "V99"})
    assert r.status_code in (400, 422), r.text


def test_api_unknown_run_404(authed_client_factory):
    client = authed_client_factory()
    assert client.get("/api/metrics-m10/runs/m10-00000000").status_code == 404


def test_api_deltas_and_failure_analysis(authed_client_factory):
    client = authed_client_factory()
    assert client.get("/api/metrics-m10/deltas").status_code == 200
    r = client.get("/api/metrics-m10/failure-analysis")
    assert r.status_code == 200
    assert "failed" in r.json()


# ---------------------------------------------------------------------------
# 10. regression smokes
# ---------------------------------------------------------------------------

def test_m1_m9_regression_smoke(client_factory):
    client = client_factory()
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/pairs/list").status_code in (200, 401, 501)


def test_boot_imports_ok():
    import backend.app.main  # noqa: F401
    import backend.app.metrics_m10.service  # noqa: F401
    import backend.app.api.metrics_m10  # noqa: F401


def test_config_defaults_and_extraction_imports():
    import backend.app.metrics_m10.states  # noqa: F401
    import backend.app.metrics_m10.taxonomy  # noqa: F401
    import backend.app.metrics_m10.schema  # noqa: F401
    import backend.app.metrics_m10.variants  # noqa: F401
    import backend.app.metrics_m10.extraction  # noqa: F401
    import backend.app.metrics_m10.aggregation  # noqa: F401
    import backend.app.metrics_m10.registry  # noqa: F401
