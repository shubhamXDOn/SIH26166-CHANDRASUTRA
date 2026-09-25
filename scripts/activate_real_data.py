"""Real-data activation for CHANDRASUTRA (SIH26166) — PATH A ingestion.

Scans data/raw, classifies every product honestly (REAL_PRADAN /
TEST_FIXTURE / UNKNOWN), selects the first genuine OHRC and the first genuine
TMC-2 product (calibrated > derived > raw), computes overlap from structural
footprint evidence and registers the pair in the canonical registry.

Honesty rules enforced here:
  * synthetic fixtures are never promoted to real data (exit 2 = BLOCKED);
  * nothing under data/raw is copied, moved, or modified;
  * overlap is derived from label footprint boxes or recorded as
    OVERLAP_UNCONFIRMED with the reason — never invented.

Run:
    .\\.venv\\Scripts\\python.exe scripts\\activate_real_data.py [--data-root data]

Exit codes: 0 = real pair registered; 1 = real products found but failed
during registration/validation; 2 = real data not present yet (BLOCKED).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("LOG_LEVEL", "ERROR")

from backend.app.config import Settings  # noqa: E402
from backend.app.loader import SOURCE_REAL_PRADAN  # noqa: E402
from backend.app.pairs import (  # noqa: E402
    PairRegistry,
    apply_validation,
    register_real_pair,
    scan_raw_products,
    select_real_pair,
)


def _load_settings(data_root: str | None) -> Settings:
    if data_root:
        return Settings(data_root=data_root, _env_file=None)
    env_root = os.environ.get("CHANDRASUTRA_DATA_ROOT")
    return Settings(data_root=env_root or "", _env_file="../.env" if (REPO_ROOT / ".env").is_file() else None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Register a genuine PRADAN pair (PATH A).")
    parser.add_argument("--data-root", default=None, help="data root (default: repo data/)")
    parser.add_argument("--image-a", default=None, help="explicit OHRC raw path relative to the data root")
    parser.add_argument("--image-b", default=None, help="explicit TMC-2 raw path relative to the data root")
    parser.add_argument("--notes", default="", help="optional notes attached to the pair record")
    parser.add_argument("--json", action="store_true", help="emit a machine-readable JSON report")
    args = parser.parse_args()

    settings = _load_settings(args.data_root)
    inventory = scan_raw_products(settings)
    real = [e for e in inventory if e["source_class"] == SOURCE_REAL_PRADAN]
    fixture = [e for e in inventory if e["source_class"] == "TEST_FIXTURE"]
    unknown = [e for e in inventory if e["source_class"] not in (SOURCE_REAL_PRADAN, "TEST_FIXTURE")]

    report = {
        "command": "activate_real_data",
        "status": "PENDING",
        "data_root": str(settings.data_root_path),
        "products_scanned": len(inventory),
        "source_breakdown": {
            "REAL_PRADAN": len(real),
            "TEST_FIXTURE": len(fixture),
            "UNKNOWN": len(unknown),
        },
        "selected_ohrc": None,
        "selected_tmc2": None,
        "registered": False,
        "pair_id": None,
        "gate": None,
        "blocker": None,
    }

    ohrc, tmc2 = select_real_pair(settings) if (not args.image_a or not args.image_b) else (
        {"rel_path": args.image_a}, {"rel_path": args.image_b}
    )
    if ohrc is None or tmc2 is None:
        missing = []
        if ohrc is None:
            missing.append("no genuine OHRC product under data/raw/ohrc")
        if tmc2 is None:
            missing.append("no genuine TMC-2 product under data/raw/tmc2")
        report["status"] = "BLOCKED"
        report["blocker"] = "Real PRADAN data is not present yet: " + "; ".join(missing)
        _finish(report, args.json)
        return 2

    report["selected_ohrc"] = ohrc
    report["selected_tmc2"] = tmc2
    print(f"[activate] OHRC : {ohrc['rel_path']} ({ohrc.get('product_id', '?')})")
    print(f"[activate] TMC-2: {tmc2['rel_path']} ({tmc2.get('product_id', '?')})")

    try:
        record = register_real_pair(
            settings,
            image_a_rel=ohrc["rel_path"],
            image_b_rel=tmc2["rel_path"],
            notes=args.notes,
        )
        record = apply_validation(record, settings)
    except (ValueError, OSError, RuntimeError) as exc:
        report["status"] = "FAILED"
        report["blocker"] = f"Registration or validation failed: {exc}"
        _finish(report, args.json)
        return 1

    report["status"] = "REGISTERED"
    report["registered"] = True
    report["pair_id"] = record.pair_id
    report["gate"] = record.data_source_gate
    report["overlap_status"] = record.overlap_status
    report["overlap_evidence"] = record.overlap_evidence
    report["validation_status"] = record.validation_status
    report["pair_record"] = {
        "pair_id": record.pair_id,
        "image_a": record.image_a_rel_path,
        "image_b": record.image_b_rel_path,
        "sensor_a": record.sensor_a,
        "sensor_b": record.sensor_b,
        "source_class_a": record.source_class_a,
        "source_class_b": record.source_class_b,
        "overlap_status": record.overlap_status,
        "processing_level_a": record.processing_level_a,
        "processing_level_b": record.processing_level_b,
    }

    _finish(report, args.json)
    return 0


def _finish(report: dict, as_json: bool) -> None:
    out = REPO_ROOT / "data" / "metadata" / "real_data_activation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if as_json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for key in ("status", "blocker", "pair_id", "gate", "validation_status"):
            if report.get(key):
                print(f"[activate] {key}: {report[key]}")
    print(f"[activate] report written to {out.name}")


if __name__ == "__main__":
    raise SystemExit(main())