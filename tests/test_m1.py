"""M1 tests — pair schema, registry, validation, loader, APIs.

All fixtures are SYNTHETIC TEST FIXTURES (never real mission data).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import fixturegen  # tests/ is on sys.path via conftest + pytest rootdir mode

REPO_ROOT = Path(__file__).resolve().parents[1]


def _settings_with_raw(tmp_path, settings_factory):
    """settings_factory pointed at the directory that holds the raw fixtures."""
    return settings_factory(data_root=str(tmp_path))


def _api_harness(settings_factory):
    """Build a temp data tree + app+client; returns (client, settings, tmp)."""
    from backend.app.config import Settings
    from backend.app.data import ensure_derived_directories
    from backend.app.main import create_app

    tmp = Path(tempfile.mkdtemp(prefix="cs_m1_"))
    fixturegen.write_standard_fixtures(tmp)
    settings = Settings(data_root=str(tmp), _env_file=None)
    ensure_derived_directories(settings)
    app = create_app(settings=settings)
    return TestClient(app), settings, tmp


# --------------------------------------------------------------------------
# 1. pair metadata schema
# --------------------------------------------------------------------------

def test_pair_schema_covers_required_fields():
    from backend.app.pairs import PairRecord

    rec = PairRecord(pair_id="CS-P001", image_a_filename="a.img", image_b_filename="b.img")
    for field in [
        "pair_id", "image_a_filename", "image_a_product_id", "image_b_filename",
        "image_b_product_id", "sensor_a", "sensor_b", "source_archive", "source_url",
        "product_type_a", "product_type_b", "processing_level_a", "processing_level_b",
        "image_a_width", "image_a_height", "image_b_width", "image_b_height",
        "dtype_a", "dtype_b", "nominal_gsd_a", "nominal_gsd_b",
        "acquisition_datetime_a", "acquisition_datetime_b", "footprint_a", "footprint_b",
        "overlap_status", "overlap_evidence", "illumination_info", "viewing_geometry_info",
        "crop_coordinates", "raw_file_hash_a", "raw_file_hash_b", "data_use_notes",
        "attribution_notes", "ingestion_status", "validation_status", "notes",
    ]:
        assert hasattr(rec, field), f"missing schema field {field}"
    # future scientific fields exist but are honest NOT_RUN / empty
    assert rec.final_status == "NOT_RUN"
    assert rec.matcher is None
    assert rec.inlier_ratio is None
    assert rec.rmse is None


def test_unknown_values_default_to_unknown_not_guessed():
    from backend.app.pairs import PairRecord

    rec = PairRecord(pair_id="CS-P001", image_a_filename="a.img", image_b_filename="b.img")
    assert rec.acquisition_datetime_a == "UNKNOWN"
    assert rec.nominal_gsd_a == "UNKNOWN"
    assert rec.overlap_status == "UNKNOWN"


# --------------------------------------------------------------------------
# 2. valid pair registration (raw untouched)
# --------------------------------------------------------------------------

def test_register_valid_pair_and_files_untouched(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import PairRegistry, build_record_from_products

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path)

    raw_a = files["ohrc_img"].read_bytes()
    raw_b = files["tmc2_img"].read_bytes()

    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    assert pa.status == "OK" and pb.status == "OK"

    record = build_record_from_products(
        "CS-P001", pa, pb,
        sensor_a="ohrc", sensor_b="tmc2",
        overlap_status="OVERLAP_UNCONFIRMED",
        overlap_evidence="Synthetic overlap claimed for software test only.",
    )
    PairRegistry(settings).save(record)

    assert files["ohrc_img"].read_bytes() == raw_a, "raw bytes must never change"
    assert files["tmc2_img"].read_bytes() == raw_b, "raw bytes must never change"
    assert (settings.data_root_path / "metadata" / "pairs.json").is_file()
    assert (settings.data_root_path / "metadata" / "pairs.csv").is_file()


# --------------------------------------------------------------------------
# 3/4. missing Image A / Image B files
# --------------------------------------------------------------------------

@pytest.mark.parametrize("side,fname", [("a", "image_a_filename"), ("b", "image_b_filename")])
def test_validation_detects_missing_side(side, fname, tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import build_record_from_products, validate_record

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    record = build_record_from_products("CS-P001", pa, pb, sensor_a="ohrc", sensor_b="tmc2",
                                        overlap_status="OVERLAP_UNCONFIRMED",
                                        overlap_evidence="fixture evidence")
    if side == "a":
        (tmp_path / "raw" / "ohrc" / pa.filename).unlink()
    else:
        (tmp_path / "raw" / "tmc2" / pb.filename).unlink()
    result = validate_record(record, settings)
    assert result["status"] == "INVALID"
    assert any(c["check"] == f"image_{side}_exists" and c["status"] == "FAIL" for c in result["checks"])


# --------------------------------------------------------------------------
# 5. missing label
# --------------------------------------------------------------------------

def test_validation_reports_missing_label(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import build_record_from_products, validate_record

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path, missing_label_a=True, missing_label_b=True)
    pa = load_product(files["ohrc_img"], None)
    pb = load_product(files["tmc2_img"], None)
    assert pa.status == "FAILURE" and pa.error["code"] == "FORMAT_UNSUPPORTED"
    record = build_record_from_products("CS-P005", pa, pb, sensor_a="ohrc", sensor_b="tmc2")
    result = validate_record(record, settings)
    assert result["status"] == "INVALID"
    assert any(c["check"] == "label_a_exists" and c["status"] == "FAIL" for c in result["checks"])


# --------------------------------------------------------------------------
# 6. unreadable / corrupt product
# --------------------------------------------------------------------------

def test_corrupt_product_is_structured_failure(tmp_path):
    from backend.app.loader import load_product

    files = fixturegen.write_standard_fixtures(tmp_path, corrupt_a=True)
    info = load_product(files["ohrc_img"], files["ohrc_label"])
    assert info.status == "FAILURE"
    assert info.error["code"] in ("PRODUCT_READ_FAILED",)
    assert "traceback" not in json.dumps(info.error).lower()


# --------------------------------------------------------------------------
# 7/8. metadata extraction + unknown handling
# --------------------------------------------------------------------------

def test_metadata_extraction_from_label(tmp_path):
    from backend.app.loader import load_product

    files = fixturegen.write_standard_fixtures(tmp_path)
    info = load_product(files["ohrc_img"], files["ohrc_label"])
    assert info.status == "OK"
    assert info.width == fixturegen.OHRC_FIXTURE["samples"] == 256
    assert info.height == fixturegen.OHRC_FIXTURE["lines"] == 200
    assert info.dtype.startswith(">u2")
    assert info.acquisition_datetime.startswith("2021-12-28")
    assert "ohrc" in info.instrument
    assert info.label_filename.endswith(".xml")


def test_unknown_metadata_field_reports_unknown(tmp_path):
    from backend.app.loader import load_product

    files = fixturegen.write_standard_fixtures(tmp_path)
    info = load_product(files["tmc2_img"], files["tmc2_label"])
    # No geometry in the minimal label -> honest UNKNOWN, never a guess
    assert info.footprint in ("UNKNOWN", "N/A")
    assert info.viewing_geometry_info == "UNKNOWN"


# --------------------------------------------------------------------------
# 9. Pair ID stability / determinism
# --------------------------------------------------------------------------

def test_pair_id_is_deterministic_and_stable(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import PairRegistry, build_record_from_products

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])

    reg = PairRegistry(settings)
    r1 = build_record_from_products("CS-P001", pa, pb, sensor_a="ohrc", sensor_b="tmc2")
    reg.save(r1)
    assert reg.next_pair_id() == "CS-P002"
    r2 = build_record_from_products(reg.next_pair_id(), pa, pb, sensor_a="ohrc", sensor_b="tmc2")
    reg.save(r2)
    assert reg.next_pair_id() == "CS-P003"
    reg2 = PairRegistry(settings)
    assert reg2.get("CS-P001").pair_id == "CS-P001"
    assert reg2.get("CS-P002").pair_id == "CS-P002"


def test_duplicate_pair_id_rejected(tmp_path, settings_factory):
    from backend.app.pairs import PairRecord, PairRegistry

    settings = _settings_with_raw(tmp_path, settings_factory)
    reg = PairRegistry(settings)
    assert reg.validate_pair_id("CS-P001") is None
    reg.save(PairRecord(pair_id="CS-P001", image_a_filename="a", image_b_filename="b"))
    assert reg.validate_pair_id("CS-P001") is not None


# --------------------------------------------------------------------------
# 10/11. hash + raw immutability
# --------------------------------------------------------------------------

def test_hash_verification_and_immutability(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import PairRegistry, build_record_from_products, validate_record

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    record = build_record_from_products("CS-P001", pa, pb, sensor_a="ohrc", sensor_b="tmc2")
    PairRegistry(settings).save(record)

    before = {files["ohrc_img"]: files["ohrc_img"].read_bytes(),
              files["tmc2_img"]: files["tmc2_img"].read_bytes()}

    result = validate_record(record, settings)
    assert result["raw_integrity"] == "VERIFIED"
    for p, blob in before.items():
        assert p.read_bytes() == blob


def test_registration_never_creates_files_in_raw(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import PairRegistry, build_record_from_products

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    record = build_record_from_products("CS-P001", pa, pb, sensor_a="ohrc", sensor_b="tmc2")

    raw_before = {f.name for f in (tmp_path / "raw").rglob("*") if f.is_file() and not f.name.startswith(".")}
    PairRegistry(settings).save(record)
    PairRegistry(settings).save(record)
    raw_after = {f.name for f in (tmp_path / "raw").rglob("*") if f.is_file() and not f.name.startswith(".")}
    assert raw_before == raw_after


# --------------------------------------------------------------------------
# 12. overlap status handling
# --------------------------------------------------------------------------

def test_overlap_status_classification_rules():
    from backend.app.pairs import OVERLAP_STATUSES

    assert OVERLAP_STATUSES == ("CONFIRMED_OVERLAP", "OVERLAP_UNCONFIRMED", "NO_OVERLAP", "UNKNOWN")
    # no fabricated middle states
    assert "overlap_looks_similar" not in OVERLAP_STATUSES


def test_overlap_requires_evidence_for_confirmed(tmp_path, settings_factory):
    from backend.app.loader import load_product
    from backend.app.pairs import build_record_from_products, validate_record

    settings = _settings_with_raw(tmp_path, settings_factory)
    files = fixturegen.write_standard_fixtures(tmp_path)
    pa = load_product(files["ohrc_img"], files["ohrc_label"])
    pb = load_product(files["tmc2_img"], files["tmc2_label"])
    record = build_record_from_products(
        "CS-P001", pa, pb, sensor_a="ohrc", sensor_b="tmc2",
        overlap_status="UNKNOWN", overlap_evidence="",
    )
    result = validate_record(record, settings)
    assert result["status"] == "VALID"          # structurally valid
    assert result["overlap"]["benchmark_ready"] is False


# --------------------------------------------------------------------------
# 13/14/15/16. API endpoints
# --------------------------------------------------------------------------

def test_api_list_pairs_empty_and_count(settings_factory):
    client, _settings, _tmp = _api_harness(settings_factory)
    with client:
        resp = client.get("/api/pairs")
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["pairs"] == []
        assert "Metadata only" in body["note"]


def test_api_register_then_list_detail_validate_and_status(settings_factory):
    client, settings, _tmp = _api_harness(settings_factory)
    with client:
        payload = {
            "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
            "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
            "overlap_status": "OVERLAP_UNCONFIRMED",
            "overlap_evidence": "Synthetic fixture overlap claimed for software tests only — not a real benchmark pair.",
        }
        r = client.post("/api/pairs/register", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["registered"] is True
        assert body["pair_id"] == "CS-P001"

        lst = client.get("/api/pairs").json()
        assert lst["count"] == 1
        assert lst["pairs"][0]["pair_id"] == "CS-P001"
        assert lst["pairs"][0]["dimensions_a"] == "256x200"
        assert lst["pairs"][0]["overlap_status"] == "OVERLAP_UNCONFIRMED"

        det = client.get("/api/pairs/CS-P001")
        assert det.status_code == 200
        rec = det.json()["record"]
        assert rec["image_a_width"] == 256 and rec["image_a_height"] == 200
        assert rec["image_b_width"] == 384 and rec["image_b_height"] == 300
        assert rec["sensor_a"] == "ohrc" and rec["sensor_b"] == "tmc2"
        assert len(rec["raw_file_hash_a"]) == 64

        val = client.post("/api/pairs/CS-P001/validate")
        assert val.status_code == 200, val.text
        vbody = val.json()
        assert vbody["status"] == "VALID"
        assert vbody["raw_integrity"] == "VERIFIED"
        assert vbody["scientific_matching"] == "NOT_RUN"
        assert (settings.data_root_path / "metadata" / "pair_validation.json").is_file()

        vrec = json.loads((settings.data_root_path / "metadata" / "pair_validation.json").read_text())
        assert vrec["pair_id"] == "CS-P001"
        assert vrec["scientific_matching"] == "NOT_RUN"

        stat = client.get("/api/data/status").json()
        assert stat["milestone"] == "M5"
        assert stat["pairs_registered"] == 1
        assert stat["pairs_valid"] == 1
        assert stat["available_sensors"] == ["ohrc", "tmc2"]
        assert stat["first_pair_status"]["pair_id"] == "CS-P001"
        assert stat["last_validation_utc"]


def test_api_invalid_pair_id_not_found(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        assert client.get("/api/pairs/CS-P999").status_code == 404
        assert client.get("/api/pairs/CS-P999/validate").status_code == 404
        assert client.post("/api/pairs/CS-P999/validate").status_code == 404


def test_api_rejects_duplicate_pair_id(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        payload = {
            "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
            "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
            "overlap_status": "UNKNOWN",
        }
        # first registration auto-assigns CS-P001
        r = client.post("/api/pairs/register", json=payload)
        assert r.status_code == 200
        # explicit duplicate is rejected deterministically
        dup = dict(payload, pair_id="CS-P001")
        r2 = client.post("/api/pairs/register", json=dup)
        assert r2.status_code == 422
        assert r2.json()["error"]["code"] == "VALIDATION_ERROR"
        # next-id reflects the registry without colliding
        assert client.get("/api/pairs/next-id").json()["pair_id"] == "CS-P002"


def test_api_rejects_path_traversal_and_absolute_paths(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        r = client.post("/api/pairs/register", json={
            "image_a": "../outside.img",
            "image_b": "raw/tmc2/x.img",
            "overlap_status": "UNKNOWN",
        })
        assert r.status_code == 422
        r2 = client.post("/api/pairs/register", json={
            "image_a": "C:\\Windows\\win.ini",
            "image_b": "raw/tmc2/x.img",
            "overlap_status": "UNKNOWN",
        })
        assert r2.status_code == 422


def test_api_register_missing_file_is_404(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        r = client.post("/api/pairs/register", json={
            "image_a": "raw/ohrc/does_not_exist.img",
            "image_b": "raw/tmc2/does_not_exist.img",
            "overlap_status": "UNKNOWN",
        })
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


def test_api_probe_reads_product_metadata(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        resp = client.get(
            "/api/pairs/probe",
            params={"path": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"},
        )
        assert resp.status_code == 200
        prod = resp.json()["product"]
        assert prod["status"] == "OK"
        assert prod["width"] == 256
        assert prod["label_filename"] is not None


def test_api_probe_path_traversal_blocked(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        assert client.get("/api/pairs/probe", params={"path": "../../etc/passwd"}).status_code == 422
        assert client.get("/api/pairs/probe", params={"path": "raw/ohrc/.."}).status_code == 422


def test_api_preview_returns_derived_png_and_raw_untouched(settings_factory):
    client, settings, tmp = _api_harness(settings_factory)
    img_path = tmp / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    with client:
        payload = {
            "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
            "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
            "overlap_status": "UNKNOWN",
        }
        client.post("/api/pairs/register", json=payload)
        before = img_path.read_bytes()
        resp = client.get("/api/pairs/CS-P001/preview/a")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("image/png")
        assert img_path.read_bytes() == before
        previews = list((settings.data_root_path / "derived" / "visualizations" / "previews").glob("*.png"))
        assert previews, "derived preview must be written to derived/visualizations/previews"


def test_api_preview_unknown_side_and_missing_pair(settings_factory):
    client, _s, _t = _api_harness(settings_factory)
    with client:
        payload = {
            "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
            "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
            "overlap_status": "UNKNOWN",
        }
        client.post("/api/pairs/register", json=payload)
        assert client.get("/api/pairs/CS-P001/preview/c").status_code == 422
        assert client.get("/api/pairs/CS-P999/preview/a").status_code == 404


# --------------------------------------------------------------------------
# 17. frontend rendering coverage hooks
# --------------------------------------------------------------------------

def test_frontend_ssr_build_smoke_script_exists():
    assert (REPO_ROOT / "frontend" / "ssr-smoke.mjs").is_file()
    assert (REPO_ROOT / "frontend" / "package.json").is_file()


# --------------------------------------------------------------------------
# route wiring + raw immutability at filesystem level (server flow)
# --------------------------------------------------------------------------

def test_pairs_route_declared_under_api():
    import backend.app.main as main_mod

    assert main_mod.app.url_path_for("list_pairs").endswith("/api/pairs")
    assert main_mod.app.url_path_for("pair_detail", pair_id="CS-P001").endswith("/api/pairs/CS-P001")
    assert main_mod.app.url_path_for("run_validation", pair_id="CS-P001").endswith("/api/pairs/CS-P001/validate")


def test_raw_files_byte_identical_after_full_flow(settings_factory):
    client, settings, tmp = _api_harness(settings_factory)
    img_a = tmp / "raw" / "ohrc" / "ch2_ohr_ncp_20211228T2209123959_d_img_d18.img"
    img_b = tmp / "raw" / "tmc2" / "ch2_tmc_ncn_20200207T0716469418_d_img_d18.img"
    digest_a = hashlib.sha256(img_a.read_bytes()).hexdigest()
    digest_b = hashlib.sha256(img_b.read_bytes()).hexdigest()

    with client:
        client.post("/api/pairs/register", json={
            "image_a": "raw/ohrc/ch2_ohr_ncp_20211228T2209123959_d_img_d18.img",
            "image_b": "raw/tmc2/ch2_tmc_ncn_20200207T0716469418_d_img_d18.img",
            "overlap_status": "UNKNOWN",
        })
        client.post("/api/pairs/CS-P001/validate")
        client.post("/api/pairs/CS-P001/validate")
        client.get("/api/pairs/CS-P001/preview/a")
        client.get("/api/pairs/CS-P001/preview/b")

    stored = json.loads((settings.data_root_path / "metadata" / "pairs.json").read_text())["pairs"][0]
    assert stored["raw_file_hash_a"] == digest_a
    assert stored["raw_file_hash_b"] == digest_b
    assert hashlib.sha256(img_a.read_bytes()).hexdigest() == digest_a
    assert hashlib.sha256(img_b.read_bytes()).hexdigest() == digest_b