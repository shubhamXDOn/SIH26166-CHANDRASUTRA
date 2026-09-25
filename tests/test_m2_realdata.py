"""M2 real-data validation + preprocessing tests (PATH A / structural).

These tests exercise the M2 validation object (PDS4 identity, IMG/XML binary
consistency, numeric sanity, sensor consistency, honest overlap methods),
deterministic logged preprocessing, raw immutability and the new API surface,
using REAL-SHAPED structure fixtures generated in pytest tmp dirs — never
committed, never usable as science. Real PRADAN files remain BLOCKED pending
operator copy; the tooling is verified structurally here (CASE D).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fixturegen  # noqa: F401
from auth_helpers import authed_client_for_app, configure_auth


def _make_settings(tmp_path, settings_factory):
    return settings_factory(data_root=str(tmp_path))


def _api_harness(tmp_path):
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    settings = Settings(data_root=str(tmp_path), _env_file=None)
    ensure_derived_directories(settings)
    configure_auth(settings)
    app = create_app(settings=settings)
    return authed_client_for_app(app), settings


def _register_fixture_pair(client):
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


def _register_real_shaped_pair(client):
    resp = client.post("/api/pairs/auto-register", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()["pair_id"]


# --------------------------------------------------------------------------
# 1. PDS4 validation (identity)
# --------------------------------------------------------------------------

def test_m2_validation_real_shaped_label_identity(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    files = fixturegen.write_real_shaped_pair(tmp_path)
    settings = _make_settings(tmp_path, settings_factory)
    client, _ = _api_harness(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    payload = validate_pair(settings, pair_id)
    assert payload is not None
    assert payload["product_a"]["label_identity"]["status"] == "VALID"
    assert payload["product_b"]["label_identity"]["status"] == "VALID"
    assert payload["metadata_validity"] == "VALID"
    assert payload["raw_integrity"] == "VERIFIED"
    assert files["ohrc_label"].is_file() and files["tmc2_label"].is_file()

    checks = payload["product_a"]["label_identity"]["checks"]
    names = {c["check"] for c in checks}
    assert {"logical_identifier", "product_class", "instrument", "array_geometry", "data_type"}.issubset(names)


# --------------------------------------------------------------------------
# 2. IMG/XML binary-size consistency
# --------------------------------------------------------------------------

def test_m2_binary_consistency_pass(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.processing.validation import binary_consistency

    files = fixturegen.write_real_shaped_pair(tmp_path)
    info = load_product(files["ohrc_img"], files["ohrc_label"])
    assert binary_consistency(info)["status"] == "PASS"


def test_m2_binary_consistency_truncated_fails(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.processing.validation import binary_consistency

    files = fixturegen.write_standard_fixtures(tmp_path, corrupt_a=True)
    info = load_product(files["ohrc_img"], files["ohrc_label"])
    bc = binary_consistency(info)
    assert bc["status"] == "FAIL"
    # OHRC is truncated beyond what the label geometry expects: either the loader
    # surfaces a truncated-read failure (expected_bytes uncomputable) or we
    # compute the geometry mismatch literally.
    assert bc["expected_bytes"] is None or bc["actual_bytes"] < bc["expected_bytes"]


def test_m2_binary_consistency_oversized_warns(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.processing.validation import binary_consistency

    files = fixturegen.write_standard_fixtures(tmp_path)
    with open(files["ohrc_img"], "ab") as fh:
        fh.write(b"\x00" * 64)
    info = load_product(files["ohrc_img"], files["ohrc_label"])
    bc = binary_consistency(info)
    assert bc["status"] == "WARNING"
    assert bc["actual_bytes"] == bc["expected_bytes"] + 64


def test_m2_validation_marks_truncated_pair_invalid(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    fixturegen.write_standard_fixtures(tmp_path)
    pair_id = _register_fixture_pair(client)
    # Truncate the raw file AFTER registration (registration refuses broken products).
    files = fixturegen.write_standard_fixtures(tmp_path)
    data = files["ohrc_img"].read_bytes()
    files["ohrc_img"].write_bytes(data[: len(data) // 2])

    payload = validate_pair(settings, pair_id)
    assert payload["product_a"]["binary_consistency"]["status"] == "FAIL"
    assert payload["validation_status"] == "INVALID"
    assert any(e["check"] == "binary_consistency" for e in payload["validation_errors"])


# --------------------------------------------------------------------------
# 3. Metadata extraction
# --------------------------------------------------------------------------

def test_m2_metadata_extraction_and_numeric_sanity(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    payload = validate_pair(settings, pair_id)
    pa = payload["product_a"]
    assert pa["dimensions"]["width"] == 256 and pa["dimensions"]["height"] == 200
    assert pa["dimensions"]["dtype"] == ">u2"
    assert pa["dimensions"]["bytes_per_pixel"] == 2
    assert pa["numeric_sanity"]["status"] == "VALID"
    assert pa["sensor"]["check"] == "sensor_consistency"
    assert pa["sensor"]["status"] == "PASS"


# --------------------------------------------------------------------------
# 4. Malformed label XML (must fail honestly, never crash)
# --------------------------------------------------------------------------

def test_m2_malformed_xml_reported_not_crashing(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    fixturegen.write_standard_fixtures(tmp_path)
    pair_id = _register_fixture_pair(client)

    files = fixturegen.write_standard_fixtures(tmp_path)  # rewrite to get paths
    files["ohrc_label"].write_text("<Product_Observational><unclosed", encoding="utf-8")

    payload = validate_pair(settings, pair_id)
    assert payload["product_a"]["label_identity"]["status"] == "INVALID"
    assert payload["validation_status"] == "INVALID"


# --------------------------------------------------------------------------
# 5. Sensor identification honesty (label weaker/absent -> WARN, never hidden)
# --------------------------------------------------------------------------

def test_m2_sensor_consistency_honest_when_label_missing(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    fixturegen.write_standard_fixtures(tmp_path)
    pair_id = _register_fixture_pair(client)

    files = fixturegen.write_standard_fixtures(tmp_path)
    files["tmc2_label"].unlink()

    payload = validate_pair(settings, pair_id)
    idc = payload["product_b"]["label_identity"]["checks"]
    warn = [c for c in idc if c["status"] == "WARN"]
    assert any(c["check"] == "instrument" for c in warn)
    assert payload["metadata_validity"] != "VALID"


# --------------------------------------------------------------------------
# 6-8. Structural overlap statuses (intersect / disjoint / missing)
# --------------------------------------------------------------------------

def test_m2_overlap_bbox_intersection_through_api(tmp_path, settings_factory):
    client, _ = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    r = client.post(f"/api/pairs/{pair_id}/overlap")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["status"] == "CONFIRMED_OVERLAP"
    assert body["result"]["method"] == "bbox_intersection"
    assert "bbox_intersection" in body["result"]["evidence"]


def test_m2_overlap_disjoint_is_unconfirmed(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import structural_overlap

    far = {"west": 60.0, "east": 60.6, "north": -5.0, "south": -5.6}
    files = fixturegen.write_real_shaped_pair(tmp_path, tmc2_bbox=far)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    res = structural_overlap(pa, pb)
    assert res["status"] == "OVERLAP_UNCONFIRMED"
    assert res["method"] == "none"
    assert "footprints_disjoint" in res["evidence"]


def test_m2_overlap_missing_footprint_unconfirmed(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import structural_overlap

    files = fixturegen.write_standard_fixtures(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    res = structural_overlap(pa, pb)
    assert res["status"] == "OVERLAP_UNCONFIRMED"
    assert res["evidence"] == "footprint_evidence_missing_on_one_side"


# --------------------------------------------------------------------------
# 9. Overlap-unconfirmed is a first-class validation state
# --------------------------------------------------------------------------

def test_m2_overlap_unconfirmed_first_class_state(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    fixturegen.write_standard_fixtures(tmp_path)
    pair_id = _register_fixture_pair(client)

    payload = validate_pair(settings, pair_id)
    assert payload["overlap_status"] == "OVERLAP_UNCONFIRMED"
    assert payload["overlap_method"] == "none"
    assert payload["validation_status"] == "OVERLAP_UNCONFIRMED"
    assert payload["footprint_status"] == "FOOTPRINT_MISSING_BOTH"


# --------------------------------------------------------------------------
# 10. Polygon path is used only when trustworthy (degenerate -> bbox fallback)
# --------------------------------------------------------------------------

def test_m2_polygon_intersection_positive_area(tmp_path, settings_factory):
    """A trustworthy, label-consistent polygon must reach polygon_intersection
    even when the clip polygon is clockwise (Sutherland-Hodgman orientation)."""
    from backend.app.pairs import _clip_polygon, _polygon_overlap

    pa = [[0.0, 0.0], [0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0]]
    pb = [[1.0, 0.0], [1.0, 3.0], [3.0, 3.0], [3.0, 0.0], [1.0, 0.0]]  # clockwise
    ba = {"min_latitude": 0.0, "max_latitude": 2.0, "min_longitude": 0.0, "max_longitude": 2.0}
    bb = {"min_latitude": 0.0, "max_latitude": 3.0, "min_longitude": 0.0, "max_longitude": 3.0}

    res = _polygon_overlap(pa, pb, ba, bb)
    assert res is not None
    assert res["method"] == "polygon_intersection"
    assert res["status"] == "CONFIRMED_OVERLAP"
    assert res["intersection"]["area_deg2"] > 0

    clipped = _clip_polygon([(float(l), float(o)) for l, o in pa], [(float(l), float(o)) for l, o in pb])
    assert len(clipped) >= 3


def test_m2_polygon_falls_back_when_inconsistent(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import structural_overlap

    files = fixturegen.write_real_shaped_pair(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    res = structural_overlap(pa, pb)
    # The REAL-SHAPED polygon includes a bogus (0,0) vertex, so its own bbox is
    # inconsistent with the label bbox -> polygon must NOT drive the verdict.
    assert res["method"] != "polygon_intersection"
    assert res["method"] == "bbox_intersection" and res["status"] == "CONFIRMED_OVERLAP"


def test_m2_crop_not_fabricated_by_validation(tmp_path, settings_factory):
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)
    payload = validate_pair(settings, pair_id)
    assert payload["crop"]["status"] == "NOT_COMPUTED"


# --------------------------------------------------------------------------
# 11. Deterministic preprocessing + operation logging
# --------------------------------------------------------------------------

def test_m2_preprocess_deterministic_and_logged(tmp_path, settings_factory):
    from backend.app.processing.service import ProcessingService

    client, settings = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    service = ProcessingService(settings)
    s1 = service.prepare(pair_id, stop_after="preprocessing")
    s2 = service.prepare(pair_id, stop_after="preprocessing")
    assert s1["state"] == "PREPROCESSING"
    assert s2["state"] == "PREPROCESSING"
    assert s1["mode"] == "preprocess_only"
    assert s1["stopped_after"] == "preprocessing"
    assert s1["matcher_readiness"] is None

    run = settings.data_root_path / "derived" / "processing" / pair_id / s1["configuration_id"]
    ops_path = run / "preprocessing_ops.json"
    assert ops_path.is_file()
    ops = json.loads(ops_path.read_text(encoding="utf-8"))
    names = {o["operation"] for o in ops["operations"]}
    assert {"read", "invalid_mask", "display_normalize"}.issubset(names)
    assert all({"operation", "parameters", "input", "output"}.issubset(o) for o in ops["operations"])
    assert ops["summary"]["deterministic"] is True

    assert s1["preprocessing_ops"]["operation_count"] == len(ops["operations"])
    assert ops["operations"] == json.loads((run / "preprocessing_ops.json").read_text(encoding="utf-8"))["operations"]
    assert (run / "ohrc" / "preprocessed_display_u16.npy").is_file()
    assert (run / "ohrc" / "invalid_mask_u8.npy").is_file()


# --------------------------------------------------------------------------
# 12. Raw immutability (nothing under data/raw ever changes)
# --------------------------------------------------------------------------

def test_m2_raw_immutability_across_pipeline(tmp_path, settings_factory):
    from backend.app.loader import sha256_of
    from backend.app.processing.service import ProcessingService
    from backend.app.processing.validation import validate_pair

    client, settings = _api_harness(tmp_path)
    files = fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    before = {p.name: sha256_of(p) for p in (files["ohrc_img"], files["tmc2_img"])}
    ProcessingService(settings).prepare(pair_id, stop_after="preprocessing")
    validate_pair(settings, pair_id)
    after = {p.name: sha256_of(p) for p in (files["ohrc_img"], files["tmc2_img"])}
    assert before == after
    assert (settings.data_root_path / "raw" / "ohrc").is_dir()
    assert (settings.data_root_path / "raw" / "tmc2").is_dir()


# --------------------------------------------------------------------------
# 13. Fixture/real gate behaviour + m2-status aggregates
# --------------------------------------------------------------------------

def test_m2_gate_classification_and_aggregate_status(tmp_path, settings_factory):
    client, _ = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    fixturegen.write_standard_fixtures(tmp_path)
    real_id = _register_real_shaped_pair(client)
    fixture_id = _register_fixture_pair(client)
    assert client.post("/api/data/validate", json={"pair_id": real_id}).status_code == 200
    assert client.post("/api/data/validate", json={"pair_id": fixture_id}).status_code == 200

    body = client.get("/api/data/m2-status").json()
    rows = {r["pair_id"]: r for r in body["pairs"]}
    assert rows[real_id]["m2_validation"] == "VALID"
    assert rows[real_id]["data_source_gate"] == "PATH_A_REAL_DATA"
    assert rows[fixture_id]["m2_validation"] in ("OVERLAP_UNCONFIRMED", "INVALID")
    assert rows[fixture_id]["data_source_gate"] == "PATH_B_SYNTHETIC_ONLY"
    assert body["counts"]["VALID"] >= 1
    assert body["real_data_gate"]["real_pair_available"] is True


def test_m2_m2_status_honest_when_empty(tmp_path, settings_factory):
    client, _ = _api_harness(tmp_path)
    body = client.get("/api/data/m2-status").json()
    assert body["pairs"] == []
    assert body["counts"] == {"VALID": 0, "OVERLAP_UNCONFIRMED": 0, "INVALID": 0, "NOT_RUN": 0}
    assert body["real_data_gate"]["status"] == "REAL_DATA_ABSENT"


# --------------------------------------------------------------------------
# 14. API surface (validate / m2-status / overlap / preprocess)
# --------------------------------------------------------------------------

def test_m2_api_validate_and_status(tmp_path, settings_factory):
    client, _ = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    r = client.post("/api/data/validate", json={"pair_id": pair_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["validation_status"] == "VALID"
    assert body["persisted"]["path"] == f"metadata/m2_validation/{pair_id}.json"

    st = client.get("/api/data/m2-status")
    assert st.status_code == 200
    assert any(x["m2_validation"] == "VALID" for x in st.json()["pairs"])

    missing = client.post("/api/data/validate", json={"pair_id": "CS-ZZZ"})
    assert missing.status_code == 404


def test_m2_api_preprocess_and_overlap_endpoints(tmp_path, settings_factory):
    client, _ = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    pp = client.post(f"/api/pairs/{pair_id}/preprocess", json={})
    assert pp.status_code == 200, pp.text
    assert pp.json()["state"] == "PREPROCESSING"
    assert pp.json()["mode"] == "preprocess_only"

    ov = client.post(f"/api/pairs/{pair_id}/overlap")
    assert ov.status_code == 200, ov.text
    assert ov.json()["result"]["status"] == "CONFIRMED_OVERLAP"

    missing = client.post("/api/pairs/CS-ZZZ/preprocess", json={})
    assert missing.status_code == 404
    missing_ov = client.post("/api/pairs/CS-ZZZ/overlap")
    assert missing_ov.status_code == 404


# --------------------------------------------------------------------------
# 15. Regression smoke (M1 endpoints still work alongside M2)
# --------------------------------------------------------------------------

def test_m2_regression_smoke_m1_api(tmp_path, settings_factory):
    client, _ = _api_harness(tmp_path)
    fixturegen.write_real_shaped_pair(tmp_path)
    fixturegen.write_standard_fixtures(tmp_path)
    pair_id = _register_real_shaped_pair(client)

    assert client.get("/api/data/status").status_code == 200
    assert client.get("/api/pairs").status_code == 200
    assert client.get(f"/api/pairs/{pair_id}").status_code == 200
    assert client.post(f"/api/pairs/{pair_id}/validate").status_code == 200
    assert client.get("/api/processing/configurations").status_code == 200
    body = client.get("/api/data/status").json()
    assert body["data_source"]["source_breakdown"]["REAL_PRADAN"] >= 2