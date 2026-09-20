"""M13 tests — final release layer bug-hunt corpus B01–B40.

The M13 layer /api/m13 is the jury-facing release surface: aggregate release
status, evidence explorer, report centre, reproducibility record, honest
measurements and a non-destructive demonstration reset. The suite checks:

  B01..B04  authentication: every endpoint requires an analyst (401)
  B05..B14  release_status aggregation: identity, frozen evidence, gate,
            provenance honesty, reproducibility, audits, measurements
  B15..B20  evidence explorer: listing, detail, tamper detection, 404s, no
            absolute paths, manifest/artifact consistency
  B21..B25  report centre: listing, content, traversal blocking, 404s, stability
  B26..B30  provenance record + demo reset + measurements honesty
  B31..B40  robustness: deterministic JSON, structured errors, latency sanity,
            secret hygiene, multi-client consistency, non-destructive reset,
            graceful empty-root behaviour, namespace convention, fingerprint
            stability, cross-endpoint consistency

Everything is verified against the frozen package as it is shipped. No result
is fabricated; empty/BLOCKED/NOT_MEASURED are honest first-class states.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path

import pytest

import auth_helpers
from backend.app.config import Settings
from backend.app.main import create_app

REPO = Path(__file__).resolve().parents[1]

EXP_ID = "EXP-EE0EBE7187E5"
DIGEST = "c8fbab19dee75ce92870755bdf5202ad1402ee97166a8bdbfc3db8dfd7557e37"
FINGERPRINT = "9b2a2f7ca15e9ffcfcc970bd2ff1eeb76bd41326a412483842c682d53e32dbce"
FUNNEL = (100, 84, 19, 19)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _build_authed(settings: Settings) -> auth_helpers.AuthedTestClient:
    auth_helpers.configure_auth(settings)
    app = create_app(settings=settings)
    return auth_helpers.authed_client_for_app(app)


def _copy_tree(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if child.name in ("auth",):  # dev accounts must not shadow test bootstrap admin
            continue
        if child.is_dir():
            shutil.copytree(child, dst / child.name)
        else:
            shutil.copy2(child, dst / child.name)


def _recursive_shas(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="module")
def seeded_settings():
    """A byte-for-byte copy of the shipped/data root with frozen evidence."""
    root = Path(tempfile.mkdtemp(prefix="cs_m13_seeded_"))
    src = REPO / "data"
    assert (src / "final_evidence" / EXP_ID / "manifest.json").is_file(), \
        "seeded release data root is missing; run scripts/m13_release_prep.py first"
    _copy_tree(src, root)
    return Settings(data_root=str(root), _env_file=None)


@pytest.fixture()
def seeded_client(seeded_settings):
    """A fresh authed client (its own token) per test.

    The auth layer invalidates a user's previous token when the same admin
    logs in again (single-active-session policy), so a shared module-scope
    token would be nullified by any later login in the same process. Building
    one client per test keeps every test independent.
    """
    return _build_authed(seeded_settings)


def _clone(settings: Settings) -> Settings:
    dst = Path(tempfile.mkdtemp(prefix="cs_m13_clone_"))
    _copy_tree(settings.data_root_path, dst)
    return Settings(data_root=str(dst), _env_file=None)


@pytest.fixture()
def fresh_empty_settings(tmp_path):
    return Settings(data_root=str(tmp_path / "empty"), _env_file=None)


def _tamper(pkg: Path, relative: str) -> str:
    target = pkg / relative
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.write_bytes(bytes(data))
    return relative


# ===========================================================================
# B01..B04  authentication
# ===========================================================================

def test_b01_unauthenticated_status_is_401(seeded_client):
    resp = seeded_client.bare().get("/api/m13/status")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"]


def test_b02_unauthenticated_evidence_is_401(seeded_client):
    resp = seeded_client.bare().get("/api/m13/evidence")
    assert resp.status_code == 401


def test_b03_unauthenticated_reset_is_401(seeded_client):
    resp = seeded_client.bare().post("/api/m13/demo/reset")
    assert resp.status_code == 401


def test_b04_invalid_token_is_401(seeded_client):
    resp = seeded_client.request("GET", "/api/m13/status",
                                 headers={"Authorization": "Bearer garbage-token"})
    assert resp.status_code == 401


# ===========================================================================
# B05..B14  release_status aggregation
# ===========================================================================

def test_b05_status_shape_complete(seeded_client):
    payload = seeded_client.get("/api/m13/status").json()
    for key in ("app", "evidence", "provenance", "reproducibility", "real_data",
                "reference", "ai", "deep_matcher", "auth", "measurements", "note"):
        assert key in payload, f"missing block {key}"


def test_b06_identity_block_carries_engineering_and_release_identity(seeded_client):
    app = seeded_client.get("/api/m13/status").json()["app"]
    assert app["product_name"] == "CHANDRASUTRA"
    assert app["milestone"] == "M11"          # engineering stage (frozen config id)
    assert app["version"] == "0.11.0"         # M11 configuration_id — must not drift
    assert app["release_milestone"] == "M13"
    assert app["release_version"] == "1.0.0"
    assert app["demo_mode"] is False


def test_b07_release_identity_is_presentation_only(seeded_settings):
    override = Settings(data_root=str(seeded_settings.data_root_path),
                        release_version="1.1.0-rc", release_milestone="M13-RC",
                        _env_file=None)
    client = _build_authed(override)
    payload = client.get("/api/m13/status").json()
    assert payload["app"]["release_version"] == "1.1.0-rc"
    assert payload["evidence"]["verify_status"] == "VERIFIED"
    assert payload["evidence"]["configuration_fingerprint"] == FINGERPRINT


def test_b08_frozen_evidence_verified(seeded_client):
    ev = seeded_client.get("/api/m13/status").json()["evidence"]
    assert ev["present"] is True
    assert ev["experiment_id"] == EXP_ID
    assert ev["pair_id"] == "CS-P001"
    assert ev["final_evidence_sha256"] == DIGEST
    assert ev["verify_status"] == "VERIFIED"
    assert ev["artifact_count"] == 29
    assert ev["configuration_fingerprint"] == FINGERPRINT


def test_b09_gate_is_path_b_synthetic(seeded_client):
    ev = seeded_client.get("/api/m13/status").json()["evidence"]
    assert ev["gate_path"] == "PATH B"
    assert ev["gate_condition"] == "SYNTHETIC_DATA_ONLY"
    assert ev["gate_reason"]


def test_b10_provenance_chain_is_honest(seeded_client):
    prov = seeded_client.get("/api/m13/status").json()["provenance"]
    chain = {s["milestone"]: s for s in prov["chain"]}
    assert prov["status"] == "INCOMPLETE"      # recorded truth: not fully complete
    assert "M8" in prov["missing_stages"]
    for m in ("M1", "M2", "M3", "M4", "M5", "M6", "M7"):
        assert chain[m]["status"] == "COMPLETE"
    assert chain["M8"]["status"] == "NOT_RUN"  # no fabricated artifacts
    assert chain["M9"]["status"] == "NOT_RUN"
    assert chain["M8"]["artifact_count"] == 0
    assert chain["M9"]["artifact_count"] == 0


def test_b11_honest_blocked_states(seeded_client):
    p = seeded_client.get("/api/m13/status").json()
    assert p["real_data"]["status"] == "BLOCKED"
    assert p["reference"]["status"] == "NOT_AVAILABLE"
    assert p["ai"]["state"] in ("NOT_CONFIGURED", "NOT_AVAILABLE")
    assert p["deep_matcher"]["state"] == "UNAVAILABLE"


def test_b12_reproducibility_reproducible_and_identical(seeded_client):
    repro = seeded_client.get("/api/m13/status").json()["reproducibility"]
    assert repro["status"] == "REPRODUCIBLE"
    assert len(repro["runs"]) == 3
    funnels = {tuple(r["funnel"].values()) for r in repro["runs"].values()}
    assert funnels == {FUNNEL}
    fps = {r["configuration_fingerprint"] for r in repro["runs"].values()}
    assert len(fps) == 1 and next(iter(fps)) == FINGERPRINT
    hashes = {(r["transform_matrix_hash"], r["report_md_sha256"]) for r in repro["runs"].values()}
    assert len(hashes) == 1 and all(a and b for a, b in hashes)


def test_b13_measurements_honest_when_record_present(seeded_client):
    m = seeded_client.get("/api/m13/status").json()["measurements"]
    assert m["status"] == "MEASURED_LOCALLY"
    assert m["hosted"] == "NOT_MEASURED"
    assert m["schema_version"] == "M13-PERF-001"
    assert m.get("hosted_note")


def test_b14_audits_crosscheck_security_reflected(seeded_client):
    ev = seeded_client.get("/api/m13/status").json()["evidence"]
    assert ev["audit_status"] == "VERIFIED"
    assert ev["crosscheck_status"] == "CLEAR"
    assert ev["crosscheck_violations"] == []
    assert ev["security_status"] == "CLEAN"


# ===========================================================================
# B15..B20  evidence explorer
# ===========================================================================

def test_b15_evidence_listing(seeded_client):
    body = seeded_client.get("/api/m13/evidence").json()
    assert body["count"] == 1
    pkg = body["packages"][0]
    assert pkg["experiment_id"] == EXP_ID
    assert pkg["pair_id"] == "CS-P001"
    assert pkg["artifact_count"] == 29
    assert pkg["final_evidence_sha256"] == DIGEST
    assert json.dumps(body).find(":\\") == -1 and "C:/" not in json.dumps(body)


def test_b16_evidence_detail_verified(seeded_client):
    body = seeded_client.get(f"/api/m13/evidence/{EXP_ID}").json()
    assert body["verify"]["status"] == "VERIFIED"
    assert body["pair_id"] == "CS-P001"
    assert body["final_evidence_sha256"] == DIGEST
    assert body["manifest"]["pair_id"] == "CS-P001"
    assert body["audits"]["status"] == "VERIFIED"


def test_b17_tampered_artifact_is_detected(seeded_settings):
    settings = _clone(seeded_settings)
    pkg = settings.data_root_path / "final_evidence" / EXP_ID
    relative = _tamper(pkg, "audits.json")
    client = _build_authed(settings)
    body = client.get(f"/api/m13/evidence/{EXP_ID}").json()
    assert body["verify"]["status"] == "INTEGRITY_DEGRADED"
    assert relative in body["verify"]["modified_files"]


def test_b18_unknown_experiment_is_404(seeded_client):
    resp = seeded_client.get("/api/m13/evidence/EXP-NOPE-NOPE")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_b19_no_absolute_paths_in_package_json(seeded_client):
    detail = seeded_client.get(f"/api/m13/evidence/{EXP_ID}").json()
    text = json.dumps(detail)
    assert "C:" not in text and ":/" not in text and "/Users" not in text
    assert str(REPO).replace("\\", "/").lower() not in text.lower()


def test_b20_manifest_consistent(seeded_client):
    manifest = seeded_client.get(f"/api/m13/evidence/{EXP_ID}").json()["manifest"]
    assert manifest["schema_version"] == "M12-EVIDENCE-MANIFEST-001"
    assert manifest["experiment_id"] == EXP_ID
    assert manifest["artifact_count"] == len(manifest["artifacts"])
    for entry in manifest["artifacts"]:
        assert entry["path"] == entry["path"].replace("\\", "/")
        assert not entry["path"].startswith("/") and ":" not in entry["path"]


# ===========================================================================
# B21..B25  report centre
# ===========================================================================

def test_b21_report_centre_lists_reports(seeded_client):
    body = seeded_client.get("/api/m13/reports").json()
    names = {r["name"] for r in body["reports"]}
    assert "M12_FINAL_SCIENTIFIC_REPORT.md" in names
    assert body["has_reproducibility_record"] is True
    assert len(names) >= 12


def test_b22_report_content_served(seeded_client):
    resp = seeded_client.get("/api/m13/report/M12_FINAL_SCIENTIFIC_REPORT.md")
    assert resp.status_code == 200
    markdown = resp.json()["markdown"]
    assert len(markdown) > 500
    assert "REPRODUCIBLE" in markdown.upper()


def test_b23_traversal_is_blocked(seeded_client):
    for name in ("../config.py", "%2e%2e/%2e%2e/etc/passwd.md", "a\\b.md",
                 "NOT_A_REPORT"):
        resp = seeded_client.get(f"/api/m13/report/{name}")
        assert resp.status_code in (404, 422), name


def test_b24_unknown_report_is_404(seeded_client):
    resp = seeded_client.get("/api/m13/report/NO_SUCH_REPORT.md")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


def test_b25_report_centre_is_stable(seeded_client):
    first = seeded_client.get("/api/m13/reports").json()
    second = seeded_client.get("/api/m13/reports").json()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    for r in first["reports"]:
        assert r["kind"] and r["size"] >= 0


# ===========================================================================
# B26..B30  provenance + reset + measurements
# ===========================================================================

def test_b26_provenance_record_is_honest(seeded_client):
    body = seeded_client.get("/api/m13/provenance").json()
    assert body["status"] == "INCOMPLETE"
    chain = {s["milestone"]: s for s in body["chain"]}
    assert chain["M8"]["status"] == "NOT_RUN"
    assert chain["M9"]["status"] == "NOT_RUN"
    text = json.dumps(body)
    assert "C:" not in text and "/Users" not in text


def test_b27_demo_reset_preserves_frozen_evidence(seeded_client):
    resp = seeded_client.post("/api/m13/demo/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_preserved"] is True
    entry = body["evidence"][0]
    assert entry["experiment_id"] == EXP_ID
    assert entry["verify_status"] == "VERIFIED"
    assert entry["final_evidence_sha256"] == DIGEST


def test_b28_reset_without_evidence_is_graceful(fresh_empty_settings):
    client = _build_authed(fresh_empty_settings)
    resp = client.post("/api/m13/demo/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["evidence_preserved"] is True
    assert body["evidence"] == []


def test_b29_measurements_endpoint_reports_honestly(seeded_client):
    m = seeded_client.get("/api/m13/measurements").json()
    assert m["status"] == "MEASURED_LOCALLY"
    assert m["hosted"] == "NOT_MEASURED"


def test_b30_measurements_without_record(fresh_empty_settings):
    client = _build_authed(fresh_empty_settings)
    m = client.get("/api/m13/measurements").json()
    assert m["status"] == "NOT_MEASURED"
    assert "No measurement record" in m["note"]


# ===========================================================================
# B31..B40  robustness
# ===========================================================================

def test_b31_payload_is_deterministic_clean_json(seeded_client):
    a = seeded_client.get("/api/m13/status").json()
    b = seeded_client.get("/api/m13/status").json()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    text = json.dumps(a, allow_nan=False)  # raises on NaN/Infinity
    assert text


def test_b32_errors_are_structured_json(seeded_client):
    bad = seeded_client.bare().get("/api/m13/status")
    assert bad.status_code == 401
    assert "error" in bad.json()
    missing = seeded_client.get("/api/m13/evidence/EXP-MISSING")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"]


def test_b33_status_latency_sanity_budget(seeded_client):
    start = time.perf_counter()
    seeded_client.get("/api/m13/status")
    assert time.perf_counter() - start < 5.0  # generous sanity, not a perf claim


def test_b34_secret_hygiene(seeded_client, seeded_settings):
    secret = auth_helpers.AUTH_TEST_SECRET
    password = auth_helpers.ADMIN_PASSWORD
    for path in ("/status", "/evidence", f"/evidence/{EXP_ID}", "/reports",
                 "/record/reproducibility", "/provenance", "/measurements"):
        resp = seeded_client.get(f"/api/m13{path}")
        assert resp.status_code == 200
        text = json.dumps(resp.json())
        assert secret not in text
        assert password not in text


def test_b35_multi_client_consistency(seeded_settings):
    first = _build_authed(seeded_settings)
    first_payload = json.dumps(first.get("/api/m13/status").json(), sort_keys=True)
    second = _build_authed(seeded_settings)  # logs in the same admin (first token invalidated)
    assert first_payload == json.dumps(second.get("/api/m13/status").json(), sort_keys=True)


def test_b36_reset_is_non_destructive(seeded_settings):
    settings = _clone(seeded_settings)
    client = _build_authed(settings)
    root = settings.data_root_path / "final_evidence"
    before = _recursive_shas(root)
    client.post("/api/m13/demo/reset")
    after = _recursive_shas(root)
    assert before == after


def test_b37_empty_root_status_is_graceful(fresh_empty_settings):
    client = _build_authed(fresh_empty_settings)
    resp = client.get("/api/m13/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["evidence"]["present"] is False
    assert payload["evidence"]["experiment_id"] is None
    assert payload["note"]


def test_b38_api_namespace_convention(seeded_client):
    assert seeded_client.get("/m13/status").status_code == 404
    assert seeded_client.get("/api/m13/status").status_code == 200


def test_b39_release_flags_never_enter_fingerprint(seeded_settings):
    base = _build_authed(seeded_settings)
    override = Settings(data_root=str(seeded_settings.data_root_path),
                        release_version="9.9.9-evil", release_milestone="M99",
                        _env_file=None)
    client = _build_authed(override)
    assert base.get("/api/m13/status").json()["evidence"]["configuration_fingerprint"] \
        == FINGERPRINT
    assert client.get("/api/m13/status").json()["evidence"]["configuration_fingerprint"] \
        == FINGERPRINT


def test_b40_cross_endpoint_consistency(seeded_client):
    status_ev = seeded_client.get("/api/m13/status").json()["evidence"]
    listed = seeded_client.get("/api/m13/evidence").json()["packages"][0]
    detail = seeded_client.get(f"/api/m13/evidence/{EXP_ID}").json()
    assert status_ev["artifact_count"] == listed["artifact_count"] == \
        detail["manifest"]["artifact_count"] == 29
    assert status_ev["final_evidence_sha256"] == listed["final_evidence_sha256"] \
        == detail["final_evidence_sha256"] == DIGEST