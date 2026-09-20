"""M12 raw-data freeze & real-data gate.

Raw files are sacred (M1 policy). M12 re-verifies that the raw products a pair
registered are still byte-identical (SHA-256), still readable, still match the
recorded identity, and — for the real-data gate — that the source archive,
products, geometry evidence and overlap evidence are certified and that the
geometry used downstream was not a synthetic TEST_FIXTURE.

Real-data gate decision statuses:

    * ``REAL_DATA_VERIFIED``   — every check PASS (PATH A enabled)
    * ``SYNTHETIC_DATA_ONLY``  — products/geometry are labelled synthetic
    * ``HOLD``                 — real-data credential evidence is incomplete
    * ``NOT_FOUND``            — pair is not registered
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.loader import load_product
from backend.app.pairs import PairRecord, PairRegistry, resolve_raw_path


def _side_paths(record: PairRecord, settings: Any, side_key: str) -> tuple[Path | None, Path | None]:
    sensor = record.sensor_a if side_key == "image_a" else record.sensor_b
    rel = record.image_a_rel_path if side_key == "image_a" else record.image_b_rel_path
    filename = record.image_a_filename if side_key == "image_a" else record.image_b_filename
    label_key = "label_a_filename" if side_key == "image_a" else "label_b_filename"
    label = getattr(record, label_key, None)
    filename_arg = filename
    if rel not in ("", "UNKNOWN"):
        filename_arg = str(Path(rel) / filename)
    try:
        image = resolve_raw_path(settings, "image_a" if side_key == "image_a" else "image_b",
                                 sensor, filename_arg)
    except ValueError:
        return None, None
    label_path = (image.parent / label) if label else None
    return image, label_path


def raw_integrity(pair_id: str, settings: Any) -> dict[str, Any]:
    """Re-verify raw products byte integrity + readability for a pair."""
    registry = PairRegistry(settings)
    record = registry.get(pair_id)
    if record is None:
        return {"pair_id": pair_id, "status": "NOT_FOUND"}
    sides: list[dict[str, Any]] = []
    all_ok = True
    for side_key, hash_field in (("image_a", "raw_file_hash_a"), ("image_b", "raw_file_hash_b")):
        image, label_path = _side_paths(record, settings, side_key)
        side: dict[str, Any] = {"side": side_key, "checks": []}
        side["image_exists"] = bool(image and image.is_file())
        side["label_exists"] = bool(label_path and label_path.is_file())
        recorded = getattr(record, hash_field, "")
        recomputed = None
        if image and image.is_file():
            from backend.app.loader import sha256_of
            recomputed = sha256_of(image)
        if not side["image_exists"]:
            side["checks"].append({"check": "raw_exists", "status": "FAIL", "detail": "raw file missing"})
        if not side["label_exists"]:
            side["checks"].append({"check": "label_exists", "status": "FAIL", "detail": "PDS4 label missing"})
        if recorded and recomputed and recorded == recomputed:
            side["checks"].append({"check": "sha256", "status": "PASS", "detail": "recomputed == recorded"})
        else:
            side["checks"].append({
                "check": "sha256",
                "status": "FAIL",
                "detail": ("no recorded hash" if not recorded else ("hash mismatch" if recomputed else "file unreadable")),
            })
            all_ok = all_ok and False
        side["recorded_hash"] = recorded
        side["recomputed_hash"] = recomputed
        if not side["image_exists"] or (label_path and not side["label_exists"]):
            all_ok = False
        sides.append(side)
    status = "VERIFIED" if all_ok else "FAILED"
    if not any(side["recorded_hash"] for side in sides):
        status = "FAILED"
    return {
        "pair_id": pair_id,
        "status": status,
        "sides": sides,
        "note": "SHA-256 of raw image files recomputed at evidence time and compared to the registered hashes.",
    }


def _geometry_source(settings: Any, pair_id: str) -> tuple[str | None, str | None]:
    try:
        from backend.app.processing.service import ProcessingService
        manifest = ProcessingService(settings).manifest(pair_id)
    except Exception:  # noqa: BLE001 - best effort
        return None, None
    if not manifest:
        return None, None
    geom = (manifest or {}).get("geometry") or {}
    return geom.get("source"), (manifest or {}).get("configuration_id")


def real_data_gate(pair_id: str, settings: Any) -> dict[str, Any]:
    """Certify the real-data gate for a pair (PATH A check)."""
    registry = PairRegistry(settings)
    record = registry.get(pair_id)
    if record is None:
        return {"pair_id": pair_id, "status": "NOT_FOUND"}
    integrity = raw_integrity(pair_id, settings)

    checks: list[dict[str, str]] = []

    def check(name: str, passed: bool, detail: str, status: str | None = None) -> None:
        checks.append({
            "check": name,
            "status": status or ("PASS" if passed else "FAIL"),
            "detail": detail,
        })

    source = f"{record.source_archive} {record.source_url}".lower()
    check("source_official", "pradan" in source or "issdc" in source,
          f"archive={record.source_archive} url={record.source_url}")
    check("products_identified",
          record.image_a_product_id != "UNKNOWN" and record.image_b_product_id != "UNKNOWN",
          f"A={record.image_a_product_id} B={record.image_b_product_id}")

    for side_key in ("image_a", "image_b"):
        image, label_path = _side_paths(record, settings, side_key)
        readable = False
        prod = None
        if image and image.is_file():
            prod = load_product(image, label_path if label_path and label_path.is_file() else None)
            readable = prod.status == "OK"
        check(f"{side_key}_readable", readable,
              prod.error.get("message", "") if prod is not None and prod.error else
              ("missing" if not image else "unreadable"))
        rec_w = getattr(record, f"{side_key}_width", "UNKNOWN")
        rec_h = getattr(record, f"{side_key}_height", "UNKNOWN")
        dims_ok = readable and prod is not None and prod.width == rec_w and prod.height == rec_h
        check(f"{side_key}_dims_match", dims_ok, f"recorded={rec_w}x{rec_h}")
        gsd = getattr(record, f"nominal_gsd_{side_key[-1]}", "UNKNOWN")
        check(f"{side_key}_gsd_known", gsd != "UNKNOWN", f"gsd={gsd}")
        acq = getattr(record, f"acquisition_datetime_{side_key[-1]}", "UNKNOWN")
        check(f"{side_key}_acquisition_known", acq != "UNKNOWN", f"acquisition={acq}")
        fp = getattr(record, f"footprint_{side_key[-1]}", "UNKNOWN")
        check(f"{side_key}_footprint_evidence", fp != "UNKNOWN", f"footprint={fp}")

    overlap_st = record.overlap_status
    evidence = bool(record.overlap_evidence.strip())
    check("overlap_status_recorded", overlap_st in ("CONFIRMED_OVERLAP", "OVERLAP_UNCONFIRMED", "NO_OVERLAP", "UNKNOWN"), overlap_st)
    check("overlap_evidence",
          overlap_st not in ("CONFIRMED_OVERLAP", "OVERLAP_UNCONFIRMED") or evidence,
          f"status={overlap_st} evidence={'present' if evidence else 'missing'}")

    all_raw = all(s["recorded_hash"] and s["recomputed_hash"] == s["recorded_hash"]
                  for s in integrity["sides"])
    check("raw_integrity_verified", all_raw, integrity["status"])

    geom_source, _geom_cfg = _geometry_source(settings, pair_id)
    if geom_source is None:
        check("geometry_real", False, "processing manifest not available", status="NA")
    else:
        check("geometry_real", geom_source != "TEST_FIXTURE", f"geometry source={geom_source}")

    failed = [c for c in checks if c["status"] == "FAIL"]
    na_only_hold = [c for c in checks if c["status"] == "NA"]
    if failed:
        status = "SYNTHETIC_DATA_ONLY" if any(c["check"] == "geometry_real" and c["status"] == "FAIL" for c in failed) else "HOLD"
    elif na_only_hold:
        status = "HOLD"
    else:
        status = "REAL_DATA_VERIFIED"

    return {
        "pair_id": pair_id,
        "status": status,
        "real_data_available": status == "REAL_DATA_VERIFIED",
        "checks": checks,
        "integrity": integrity,
        "decision": {
            "path_a": status == "REAL_DATA_VERIFIED",
            "path_b": status != "REAL_DATA_VERIFIED",
            "reason": (
                "PATH A enabled: raw data certified."
                if status == "REAL_DATA_VERIFIED" else
                "PATH B: real-data credentials not certified; deterministic synthetic TEST_FIXTURE engineering proof only."
            ),
        },
    }


__all__ = ["raw_integrity", "real_data_gate", "_side_paths"]