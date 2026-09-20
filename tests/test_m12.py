"""M12 tests — Final scientific validation, reproducibility & evidence freeze.

Corpus B01–B35 across the M12 layer:

  B01..B06  configuration freeze (deterministic ids/versions/hashes, verification)
  B07..B11  raw integrity re-verification + real-data gate (two-path rule)
  B12       full M1..M9 provenance chain (relative paths, hashes, honest NOT_RUN)
  B13..B15  evidence package freeze, manifest + FINAL_EVIDENCE_SHA256, tamper detect
  B16       raw SHA-256 equals registered hash (part of B07/B08 workflow)
  B17..B21  independent audits recompute recorded evidence (funnel/trust/spatial/reg)
  B22..B24  reproducibility RUN A/B/C signatures (incl. tamper detection)
  B25..B30  AI cross-check validation against the evidence packet
  B31       measurement/claim separation (physical accuracy NOT_AVAILABLE)
  B32       report/visualization labelling (experiment id, pair, status, synthetic)
  B33       relative-only linkage in evidence package (no absolute paths)
  B34       final evidence package layout completeness
  B35       status matrix / M12 report renders with required sections

All fixtures are synthetic and labelled TEST_FIXTURE; no scientific claim is made.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

# fixturegen is imported via conftest path (tests dir on sys.path)
import fixturegen  # noqa: F401

from auth_helpers import authed_client_for_app  # noqa: E401

PA = "CS-P001"
PC, MK, TG, SR, RG, MT = (
    "PC-M2-001", "MC-M3-001", "TG-M4-001", "SR-M5-001", "RG-M6-001", "MT-M7-001")


# ---------------------------------------------------------------------------
# workspace helpers
# ---------------------------------------------------------------------------

def _settings(root: Path):
    from backend.app.config import Settings
    return Settings(data_root=str(root), _env_file=None)


def _healthy_fixture_settings(root: Path):
    """A root with registered synthetic raw products (fixturegen)."""
    from backend.app.data import ensure_derived_directories
    fixturegen.write_correlated_fixtures(root)
    settings = _settings(root)
    ensure_derived_directories(settings)
    _register_fixture(settings)
    return settings


def _register_fixture(settings, pair_id=PA):
    from backend.app.loader import sha256_of
    from backend.app.pairs import PairRecord, PairRegistry
    ohrc = settings.data_root_path / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    tmc2 = settings.data_root_path / "raw" / "tmc2" / "ch2_tmc_ncn_20200207T0716469418_d_img_d18.img"
    record = PairRecord(
        pair_id=pair_id,
        image_a_filename=ohrc.name,
        image_a_rel_path="raw/ohrc",
        image_b_filename=tmc2.name,
        image_b_rel_path="raw/tmc2",
        image_a_product_id="urn:fixture:ch2:ohrc:ch2_ohr_ncp_20211228T2209123959_d_img_d18",
        image_b_product_id="urn:fixture:ch2:tmc2:ch2_tmc_ncn_20200207T0716469418_d_img_d18",
        image_a_width=520, image_a_height=700,
        image_b_width=540, image_b_height=700,
        sensor_a="ohrc", sensor_b="tmc2",
        product_type_a="test_product", product_type_b="test_product",
        processing_level_a="TEST", processing_level_b="TEST",
        nominal_gsd_a="0.5", nominal_gsd_b="0.5",
        acquisition_datetime_a="2021-12-28T22:09:12.395Z",
        acquisition_datetime_b="2020-02-07T07:16:46.418Z",
        footprint_a="fixture_bbox", footprint_b="fixture_bbox",
        raw_file_hash_a=sha256_of(ohrc),
        raw_file_hash_b=sha256_of(tmc2),
        raw_size_a=ohrc.stat().st_size,
        raw_size_b=tmc2.stat().st_size,
        label_a_filename=ohrc.with_suffix(".xml").name,
        label_b_filename=tmc2.with_suffix(".xml").name,
        overlap_status="CONFIRMED_OVERLAP",
        overlap_evidence="fixture overlap derived from synthetic geometry",
    )
    return PairRegistry(settings).save(record)


def _geometry_manifest(settings, source="TEST_FIXTURE"):
    """Write the M2 geometry manifest (geometry source -> PATH decision)."""
    d = settings.data_root_path / "derived" / "processing" / PA / PC
    d.mkdir(parents=True, exist_ok=True)
    (d / "processing_manifest.json").write_text(json.dumps({
        "configuration": {"configuration_id": PC},
        "geometry": {"source": source},
    }, indent=2), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({
        "pair_id": PA, "configuration_id": PC, "geometry": {"source": source},
    }, indent=2), encoding="utf-8")


def _complete_tree(settings, pair_id=PA):
    """M2 tree + real M6 + real M7 to COMPLETE."""
    import test_m6 as m6h
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    from backend.app.metrics.service import MetricsService
    from backend.app.registration.service import RegistrationService

    m6h._build_m6_ready_tree(settings, pair_id)
    root = settings.data_root_path
    reg = RegistrationService(root, m6_cfg=m6_config(), m5_cfg=m5_config(),
                              m4_defaults=m4_config()["defaults"])
    assert reg.run(pair_id)["state"] == "COMPLETE"
    met = MetricsService(root, m7_cfg=m7_config(), m6_cfg=m6_config(),
                         m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    assert met.run(pair_id)["state"] == "COMPLETE"
    return met


@pytest.fixture(scope="module")
def m12_suite():
    """One pristine complete workspace shared across the corpus (read-only)."""
    root = Path(tempfile.mkdtemp(prefix="cs_m12_pristine_"))
    settings = _settings(root)
    from backend.app.data import ensure_derived_directories
    fixturegen.write_correlated_fixtures(root)
    ensure_derived_directories(settings)
    _register_fixture(settings)
    _geometry_manifest(settings)
    _complete_tree(settings)
    return settings


@pytest.fixture()
def fresh_settings():
    root = Path(tempfile.mkdtemp(prefix="cs_m12_fresh_"))
    settings = _healthy_fixture_settings(root)
    _geometry_manifest(settings)
    return settings


def clone_settings(settings):
    """Clone the pristine workspace so destructive tests never corrupt shared state."""
    src = settings.data_root_path
    dst = Path(tempfile.mkdtemp(prefix="cs_m12_clone_"))
    for name in src.iterdir():
        if name.is_dir():
            shutil.copytree(name, dst / name.name)
        else:
            shutil.copy2(name, dst / name.name)
    return _settings(dst)


# ===========================================================================
# B01..B06  configuration freeze
# ===========================================================================

def test_b01_canonical_config_json_is_deterministic_and_excludes_source(m12_suite):
    from backend.app.m12.config_freeze import canonical_config_json
    from backend.app.config import m2_config
    cfg = dict(m2_config())
    cfg["source"] = "C:/secret/path"
    first = canonical_config_json(cfg)
    cfg["source"] = "D:/elsewhere"
    assert canonical_config_json(cfg) == first
    assert "secret/path" not in first


def test_b02_configuration_chain_covers_m1_to_m11(m12_suite):
    from backend.app.m12.config_freeze import configuration_chain
    chain = configuration_chain(settings=m12_suite)
    stages = [s["milestone"] for s in chain["chain"]]
    assert stages == ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11"]
    by = {s["milestone"]: s for s in chain["chain"]}
    assert by["M2"]["configuration_id"] == PC
    assert by["M8"]["configuration_id"] == "DM-M8-001"
    assert by["M9"]["configuration_id"] == "AI-M9-001"
    assert by["M10"]["configuration_id"] == "AU-M10-001"
    for stage in chain["chain"]:
        assert len(stage["sha256"]) == 64


def test_b03_fingerprint_is_pure_function_of_config(m12_suite):
    from backend.app.m12.config_freeze import configuration_chain
    a = configuration_chain(settings=m12_suite)
    b = configuration_chain(settings=_settings(m12_suite.data_root_path))
    assert a["fingerprint"] == b["fingerprint"]
    assert a["fingerprint"].startswith("CHANDRASUTRA-SIH26166") or len(a["fingerprint"]) == 64


def test_b04_write_configuration_freeze_writes_frozen_doc(m12_suite):
    from backend.app.m12.config_freeze import configuration_chain, write_configuration_freeze
    dst = m12_suite.data_root_path / "final_evidence" / "EXP-WRITE" / "deep"
    path = write_configuration_freeze(configuration_chain(settings=m12_suite), m12_suite,
                                      "EXP-WRITE", dst)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["experiment_id"] == "EXP-WRITE"
    assert payload["freeze"]["fingerprint"]
    assert "C:" not in path.read_text(encoding="utf-8")


def test_b05_verify_configuration_freeze_flags_drift(m12_suite):
    from backend.app.m12.config_freeze import configuration_chain, verify_configuration_freeze
    recorded = configuration_chain(settings=m12_suite)
    frozen = verify_configuration_freeze(recorded, settings=m12_suite)
    assert frozen["status"] == "VERIFIED"
    tampered = {**recorded, "chain": [{**s, "sha256": "0" * 64} if s["milestone"] == "M4" else s
                                      for s in recorded["chain"]]}
    drifted = verify_configuration_freeze(tampered, settings=m12_suite)
    assert drifted["status"] == "DRIFTED"


def test_b06_operations_digest_reflects_operational_surface(m12_suite):
    from backend.app.m12.config_freeze import operations_digest
    d1 = operations_digest(m12_suite)
    altered = _settings(m12_suite.data_root_path)
    from backend.app.config import Settings
    altered = Settings(data_root=str(m12_suite.data_root_path),
                       run_stale_budget_seconds=m12_suite.run_stale_budget_seconds + 5,
                       _env_file=None)
    assert operations_digest(altered) != d1


# ===========================================================================
# B07..B11  raw integrity + real-data gate
# ===========================================================================

def test_b07_raw_integrity_verified_when_hashes_match(fresh_settings):
    from backend.app.m12.raw_integrity import raw_integrity
    result = raw_integrity(PA, fresh_settings)
    assert result["status"] == "VERIFIED"
    for side in result["sides"]:
        assert side["recorded_hash"] == side["recomputed_hash"]


def test_b08_raw_integrity_failed_on_bytes_changed(fresh_settings):
    from backend.app.m12.raw_integrity import raw_integrity
    raw = fresh_settings.data_root_path / "raw" / "ohrc" / \
        "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    with open(raw, "r+b") as f:
        f.write(b"\x00\x11")
    result = raw_integrity(PA, fresh_settings)
    assert result["status"] == "FAILED"
    assert any(c["status"] == "FAIL" for c in result["sides"][0]["checks"])


def test_b09_raw_integrity_not_found_for_unknown_pair(fresh_settings):
    from backend.app.m12.raw_integrity import raw_integrity
    assert raw_integrity("CS-NOPE-999", fresh_settings)["status"] == "NOT_FOUND"


def test_b10_real_data_gate_verified_for_certified_real_dataset(m12_suite):
    """Emulate a certified real dataset: official source + geometry source not TEST_FIXTURE."""
    settings = clone_settings(m12_suite)
    raw_dir = settings.data_root_path / "raw"
    shutil.rmtree(raw_dir, ignore_errors=True)
    fixturegen.write_correlated_fixtures(settings.data_root_path)
    _register_fixture(settings)
    _geometry_manifest(settings, source="ISRO-ISSDC-AUTHENTICATED")
    from backend.app.pairs import PairRegistry
    record = PairRegistry(settings).get(PA)
    record.source_archive = "ISRO / ISSDC PRADAN — Chandrayaan-2"
    record.source_url = "https://pradan.issdc.gov.in/ch2/"
    record.image_a_product_id = "urn:isro:ch2:ohrc:ch2_ohr_ncp_20211228T2209123959_d_img_d18"
    record.image_b_product_id = "urn:isro:ch2:tmc2:ch2_tmc_ncn_20200207T0716469418_d_img_d18"
    record.overlap_status = "CONFIRMED_OVERLAP"
    record.overlap_evidence = "orbit-geometry derived overlap"
    from backend.app.pairs import PairRegistry as PR
    PR(settings).save(record)
    from backend.app.m12.raw_integrity import real_data_gate
    gate = real_data_gate(PA, settings)
    assert gate["status"] == "REAL_DATA_VERIFIED"
    assert gate["decision"]["path_a"] is True
    assert gate["decision"]["path_b"] is False


def test_b11_real_data_gate_path_b_for_test_fixture(m12_suite):
    settings = clone_settings(m12_suite)
    _geometry_manifest(settings, source="TEST_FIXTURE")
    from backend.app.m12.raw_integrity import real_data_gate
    gate = real_data_gate(PA, settings)
    assert gate["status"] == "SYNTHETIC_DATA_ONLY"
    assert gate["decision"]["path_a"] is False
    assert gate["decision"]["path_b"] is True


# ===========================================================================
# B12  provenance chain
# ===========================================================================

def test_b12_full_provenance_chain_relative_paths_and_honest_not_run(m12_suite):
    from backend.app.m12.provenance import build_full_provenance
    chain = build_full_provenance(PA, m12_suite)
    assert len(chain["chain"]) == 9
    by = {s["milestone"]: s for s in chain["chain"]}
    assert by["M1"]["status"] == "COMPLETE"
    assert by["M2"]["status"] == "COMPLETE"
    assert by["M3"]["status"] == "COMPLETE"
    assert by["M6"]["status"] == "COMPLETE"
    for stage in chain["chain"]:
        for artifact in stage["artifacts"]:
            assert not artifact["path"].startswith("/")
            assert ":" not in artifact["path"].split("/")[0]
            assert len(artifact["sha256"]) == 64
    assert by["M9"]["status"] == "NOT_RUN"
    assert chain["status"] in ("COMPLETE", "INCOMPLETE")


# ===========================================================================
# B13..B16  evidence package freeze + tamper detect
# ===========================================================================

def _package_args(settings, exp="EXP-BUNDLE"):
    from backend.app.m12 import audits, provenance, raw_integrity
    from backend.app.m12.config_freeze import configuration_chain
    from backend.app.m12.crosscheck import validate_ai_response
    gate = raw_integrity.real_data_gate(PA, settings)
    freeze = configuration_chain(settings=settings)
    prov = provenance.build_full_provenance(PA, settings)
    aud = audits.run_all_audits(PA, settings)
    cc = validate_ai_response({"reference": "NOT_AVAILABLE", "pipeline": {"M7": "BLOCKED"}},
                              "a grounded fragment 3.7")
    return {
        "experiment_id": exp, "gate": gate, "freeze": freeze, "provenance": prov,
        "audits": aud, "crosscheck": cc, "report_md": "# M12 report\nsynthetic.",
        "notes": "test",
    }


def test_b13_evidence_package_frozen_with_manifest_and_digest(m12_suite):
    from backend.app.m12.package import build_final_evidence, verify_frozen
    settings = clone_settings(m12_suite)
    pkg = build_final_evidence(PA, settings, **_package_args(settings, "EXP-B13"))
    assert pkg["status"] == "FROZEN"
    root = settings.data_root_path / "final_evidence" / "EXP-B13"
    assert (root / "manifest.json").is_file()
    digest = (root / "FINAL_EVIDENCE_SHA256").read_text().strip()
    assert digest == pkg["final_evidence_sha256"]
    assert verify_frozen(settings, "EXP-B13")["status"] == "VERIFIED"


def test_b14_secret_scan_catches_api_key(m12_suite):
    from backend.app.m12.package import scan_secrets
    root = Path(tempfile.mkdtemp(prefix="cs_m12_sec_"))
    (root / "notes.txt").write_text("my google key is AIzaSyDx-leaked-sample-0123456789abc", encoding="utf-8")
    result = scan_secrets(root)
    assert result["status"] == "SECRET_FOUND"
    assert result["hits"][0]["kind"] == "google_api_key"


def test_b15_tamper_detected_by_verify_frozen(m12_suite):
    from backend.app.m12.package import build_final_evidence, verify_frozen
    settings = clone_settings(m12_suite)
    build_final_evidence(PA, settings, **_package_args(settings, "EXP-B15"))
    root = settings.data_root_path / "final_evidence" / "EXP-B15"
    (root / "report.md").write_text("# tampered\n", encoding="utf-8")
    check = verify_frozen(settings, "EXP-B15")
    assert check["status"] == "INTEGRITY_DEGRADED"
    assert "report.md" in check["modified_files"]


def test_b16_raw_sha256_equivalence(fresh_settings):
    from backend.app.m12.raw_integrity import raw_integrity
    result = raw_integrity(PA, fresh_settings)
    assert result["status"] == "VERIFIED"
    for side in result["sides"]:
        assert side["recomputed_hash"] == side["recorded_hash"]


# ===========================================================================
# B17..B21  independent audits (recomputed vs recorded)
# ===========================================================================

def test_b17_candidate_funnel_audit_matches_recorded(m12_suite):
    from backend.app.m12.audits import candidate_funnel_audit
    result = candidate_funnel_audit(PA, m12_suite)
    assert result["status"] == "MATCH"
    assert all(r["match"] for r in result["rows"])


def test_b18_candidate_funnel_audit_flags_recorded_mismatch(m12_suite):
    from backend.app.m12.audits import candidate_funnel_audit
    settings = clone_settings(m12_suite)
    run = settings.data_root_path / "derived" / "matches" / PA / PC / MK
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    summary["total_candidates"] = 42
    (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    result = candidate_funnel_audit(PA, settings)
    assert result["status"] == "MISMATCH"


def test_b19_trust_audit_recomputes_verdicts(m12_suite):
    from backend.app.m12.audits import trust_audit
    result = trust_audit(PA, m12_suite)
    assert result["status"] == "MATCH"
    assert result["rows"]


def test_b20_spatial_audit_matches_selected_count(m12_suite):
    from backend.app.m12.audits import spatial_audit
    result = spatial_audit(PA, m12_suite)
    assert result["status"] == "MATCH"
    row = next(r for r in result["rows"] if r["metric"] == "FUNNEL_M5_SELECTED")
    assert row["recorded"] == row["recomputed"]
    assert row["recorded"] > 0


def test_b21_registration_audit_enforces_coordinate_space(m12_suite):
    from backend.app.m12.audits import registration_audit
    result = registration_audit(PA, m12_suite)
    assert result["status"] == "MATCH"
    shapes = {r["metric"]: r for r in result["rows"]}
    assert shapes["TRANSFORM_DIRECTION"]["match"] is True
    assert shapes["TRANSFORM_COORDINATE_SPACE"]["match"] is True
    assert "sensor_a_pixel -> sensor_b_pixel" in (
        shapes["TRANSFORM_DIRECTION"]["recorded"],
        shapes["TRANSFORM_DIRECTION"]["recorded"] or "")


# ===========================================================================
# B22..B24  reproducibility
# ===========================================================================

def test_b22_run_signatures_identical_across_workspaces(m12_suite):
    from backend.app.m12.reproducibility import compute_run_signature
    import test_m6 as m6h
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    from backend.app.data import ensure_derived_directories
    from backend.app.metrics.service import MetricsService
    from backend.app.registration.service import RegistrationService
    root = Path(tempfile.mkdtemp(prefix="cs_m12_repro_"))
    settings = _settings(root)
    ensure_derived_directories(settings)
    m6h._build_m6_ready_tree(settings, PA)
    RegistrationService(root, m6_cfg=m6_config(), m5_cfg=m5_config(),
                        m4_defaults=m4_config()["defaults"]).run(PA)
    MetricsService(root, m7_cfg=m7_config(), m6_cfg=m6_config(),
                   m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"]).run(PA)
    sig_local = compute_run_signature(settings, PA)
    sig_pristine = compute_run_signature(m12_suite, PA)
    for key in sig_local:
        assert sig_local[key] == sig_pristine[key], key


def test_b23_tampered_evidence_drifts_signature():
    from backend.app.m12.reproducibility import compare_signatures, compute_run_signature
    import test_m6 as m6h
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    from backend.app.data import ensure_derived_directories
    from backend.app.metrics.service import MetricsService
    from backend.app.registration.service import RegistrationService
    build = []
    for _ in (1, 2):
        root = Path(tempfile.mkdtemp(prefix="cs_m12_sig_"))
        settings = _settings(root)
        ensure_derived_directories(settings)
        m6h._build_m6_ready_tree(settings, PA)
        RegistrationService(root, m6_cfg=m6_config(), m5_cfg=m5_config(),
                            m4_defaults=m4_config()["defaults"]).run(PA)
        MetricsService(root, m7_cfg=m7_config(), m6_cfg=m6_config(),
                       m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"]).run(PA)
        build.append((root, settings))
    s_run = build[1][0] / "derived" / "spatial" / PA / PC / MK / TG / SR
    data = np.load(s_run / "selected_correspondences.npz")
    keep = {k: data[k][: data["x_a"].size // 2] for k in data.files}
    np.savez(s_run / "selected_correspondences.npz", **keep)
    good = compute_run_signature(build[0][1], PA)
    bad = compute_run_signature(build[1][1], PA)
    assert bad["m5_selected_count"] != good["m5_selected_count"]
    ver = compare_signatures({"A": good, "B": bad})
    assert ver["status"] == "DRIFTED"


def test_b24_three_run_reproducibility_reproducible():
    from backend.app.m12.reproducibility import compare_signatures, compute_run_signature
    import test_m6 as m6h
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    from backend.app.data import ensure_derived_directories
    from backend.app.metrics.service import MetricsService
    from backend.app.registration.service import RegistrationService
    sig = {}
    for name in ("A", "B", "C"):
        root = Path(tempfile.mkdtemp(prefix="cs_m12_run_"))
        settings = _settings(root)
        ensure_derived_directories(settings)
        m6h._build_m6_ready_tree(settings, PA)
        RegistrationService(root, m6_cfg=m6_config(), m5_cfg=m5_config(),
                            m4_defaults=m4_config()["defaults"]).run(PA)
        MetricsService(root, m7_cfg=m7_config(), m6_cfg=m6_config(),
                       m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"]).run(PA)
        sig[name] = compute_run_signature(settings, PA)
    ver = compare_signatures(sig)
    assert ver["status"] == "REPRODUCIBLE"
    assert not ver["drifted_subjects"]


# ===========================================================================
# B25..B30  AI cross-check against evidence packet
# ===========================================================================

def test_b25_crosscheck_clear_for_grounded_answer(m12_suite):
    from backend.app.m12.crosscheck import validate_ai_response
    packet = {"reference": "NOT_AVAILABLE", "pipeline_state": {"M7": "COMPLETE"},
              "residual_mean_px": 3.7, "geometry_source": "TEST_FIXTURE"}
    result = validate_ai_response(packet, "The residual mean was 3.7 px on synthetic TEST_FIXTURE data.")
    assert result["status"] == "CLEAR"


def test_b26_ungrounded_number_flagged(m12_suite):
    from backend.app.m12.crosscheck import validate_ai_response
    packet = {"residual_mean_px": 1.2}
    result = validate_ai_response(packet, "the value is 99.5")
    assert any(v["code"] == "UNGROUNDED_NUMBER" for v in result["violations"])


def test_b27_physical_accuracy_claim_flagged(m12_suite):
    from backend.app.m12.crosscheck import validate_ai_response
    packet = {"reference_dataset": "NOT_AVAILABLE"}
    result = validate_ai_response(packet, "This gives 5 m CE90 absolute accuracy.")
    assert any(v["code"] == "PHYSICAL_ACCURACY_CLAIM" for v in result["violations"])


def test_b28_blocked_as_success_flagged(m12_suite):
    from backend.app.m12.crosscheck import validate_ai_response
    packet = {"pipeline_state": {"M7": "BLOCKED"}}
    result = validate_ai_response(packet, "The entire pipeline completed successfully and is ready for science.")
    assert any(v["code"] == "BLOCKED_AS_SUCCESS" for v in result["violations"])


def test_b29_terminology_and_source_violations_flagged():
    from backend.app.m12.crosscheck import validate_ai_response
    packet = {"pipeline_state": {"M7": "COMPLETE"}, "geometry_source": "TEST_FIXTURE"}
    text = ("Matcher confidence score 95% proves high accuracy. Real OHRC data observed. "
            "Evidence at C:\\temp\\x.img")
    result = validate_ai_response(packet, text)
    codes = {v["code"] for v in result["violations"]}
    assert {"MATCHER_CONFIDENCE_AS_TRUTH", "SYNTHETIC_AS_REAL",
            "ABSOLUTE_PATH_LINKAGE"} <= codes


def test_b30_packet_integrity_digest_verification(m12_suite):
    from backend.app.ai.evidence import canonical_digest
    from backend.app.m12.crosscheck import validate_packet_integrity
    packet = {"reference": "NOT_AVAILABLE", "pipeline_state": {"M7": "COMPLETE"}}
    digest = canonical_digest(packet)
    assert validate_packet_integrity(packet, digest)["status"] == "VERIFIED"
    assert validate_packet_integrity(packet, "0" * 64)["status"] == "INTEGRITY_MISMATCH"


# ===========================================================================
# B31  measurement/claim separation
# ===========================================================================

def test_b31_physical_accuracy_not_available_and_no_claims(m12_suite):
    from backend.app.metrics.service import MetricsService
    from backend.app.metrics.states import FORBIDDEN_TERMINOLOGY
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    met = MetricsService(m12_suite.data_root_path, m7_cfg=m7_config(), m6_cfg=m6_config(),
                         m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    report = met.report_json(PA)
    reference = report.get("reference") or {}
    assert reference.get("status") in ("NOT_AVAILABLE", "REFERENCE_UNAVAILABLE", None) or (
        "NOT_AVAILABLE" in json.dumps(reference))
    for metric in met.metrics(PA):
        if metric["scientific_status"] == "NOT_SCIENTIFIC":
            continue
        for token in FORBIDDEN_TERMINOLOGY:
            assert token not in (metric.get("calculation_method") or "").lower(), (
                metric["metric_id"], token)
    rec = next(m for m in met.metrics(PA) if m["metric_id"] == "RECOMPUTE_MISMATCH")
    assert int(rec["value"] or 0) == 0


# ===========================================================================
# B32  report/visualization labelling
# ===========================================================================

def test_b32_report_labelled_with_identity_and_synthetic_flag(m12_suite):
    from backend.app.config import m4_config, m5_config, m6_config, m7_config
    from backend.app.metrics.service import MetricsService
    met = MetricsService(m12_suite.data_root_path, m7_cfg=m7_config(), m6_cfg=m6_config(),
                         m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    run = met.find_run_for_pair(PA)
    text = (run / "report.md").read_text(encoding="utf-8")
    assert "EXP-" in text
    assert PA in text
    assert "NOT_AVAILABLE" in text


# ===========================================================================
# B33  relative-only linkage in evidence
# ===========================================================================

def test_b33_no_absolute_paths_in_evidence_package(m12_suite):
    from backend.app.m12.package import build_final_evidence
    settings = clone_settings(m12_suite)
    build_final_evidence(PA, settings, **_package_args(settings, "EXP-B33"))
    root = settings.data_root_path / "final_evidence" / "EXP-B33"
    bad = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "C:\\" in text or re_search_abs(text):
            bad.append(path.name)
    assert not bad


def re_search_abs(text):
    import re
    return bool(re.search(r"(?m)^[A-Za-z]:[\\/]", text))


# ===========================================================================
# B34  package layout completeness
# ===========================================================================

def test_b34_final_evidence_layout_complete(m12_suite):
    from backend.app.m12.package import build_final_evidence
    settings = clone_settings(m12_suite)
    args = _package_args(settings, "EXP-B34")
    build_final_evidence(PA, settings, **args)
    root = settings.data_root_path / "final_evidence" / "EXP-B34"
    expected = {
        "experiment.json", "pair.json", "configurations.json", "provenance.json",
        "audits.json", "crosscheck.json", "report.md", "manifest.json",
        "FINAL_EVIDENCE_SHA256", "security.json",
    }
    present = {p.name for p in root.rglob("*") if p.is_file()}
    assert expected <= present
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["artifact_count"] == len(manifest["artifacts"])


# ===========================================================================
# B35  status matrix / final report render
# ===========================================================================

def test_b35_final_report_renders_status_matrix_and_handoff(m12_suite):
    from backend.app.m12.report import build_final_report_markdown
    from backend.app.m12 import audits, provenance, raw_integrity
    from backend.app.m12.config_freeze import configuration_chain
    from backend.app.m12.crosscheck import validate_ai_response
    from backend.app.m12.reproducibility import compare_signatures, compute_run_signature
    gate = raw_integrity.real_data_gate(PA, m12_suite)
    md = build_final_report_markdown({
        "experiment_id": "EXP-REPORT",
        "pair_id": PA,
        "gate": gate,
        "freeze": configuration_chain(settings=m12_suite),
        "provenance": provenance.build_full_provenance(PA, m12_suite),
        "audits": audits.run_all_audits(PA, m12_suite),
        "crosscheck": validate_ai_response({"pipeline": {"M7": "BLOCKED"}}, "ok 1.0"),
        "reproducibility": compare_signatures({"A": compute_run_signature(m12_suite, PA)}),
        "package": {"status": "FROZEN", "package_dir": "final_evidence/x", "final_evidence_sha256": "0" * 64},
        "security": {"status": "CLEAN"},
        "corpus": {"file": "tests/test_m12.py"},
        "m12_test_results": {"passed": 35, "total": 35},
    })
    for section in ("## 1. Executive summary", "## 4. Real-data gate certification",
                    "## 6. Configuration freeze & experiment identity",
                    "## 7. Provenance chain", "## 16. Reproducibility proof",
                    "## 17. Final evidence package", "### Definition of Done (M12)",
                    "### M13 handoff notes"):
        assert section in md
    assert "PATH B" in md or "SYNTHETIC_DATA_ONLY" in md


# ===========================================================================
# API surface smoke
# ===========================================================================

def test_m12_configuration_freezeg_endpoint(authed_client_factory):
    client = authed_client_factory()
    with client:
        resp = client.get("/api/m12/configuration-freeze")
        assert resp.status_code == 200
        body = resp.json()
        assert body["fingerprint"]
        assert body["schema_version"] == "M12-CONFIG-FREEZE-001"


def test_m12_real_data_gate_endpoint_unregistered(authed_client_factory):
    client = authed_client_factory()
    with client:
        resp = client.get("/api/m12/real-data-gate/CS-UNKNOWN-X")
        assert resp.status_code == 404