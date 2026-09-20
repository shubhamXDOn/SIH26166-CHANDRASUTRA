"""M13 release manifest generator.

Builds ``release_manifest.json`` at the repository root as a machine-readable,
honest aggregate of the frozen release: application identity, experiment and
evidence digests, configuration fingerprint, reproducibility summary and —
when available — regression and bug-hunt counts from ``perf`` records.

Usage:
    python scripts/m13_manifest.py [--data-root data] [--out release_manifest.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings, rfc3339_now
from backend.app.m12.config_freeze import configuration_chain
from backend.app.m12.package import FROZEN_DIGEST_NAME, MANIFEST_NAME, verify_frozen


def _read_json(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--out", default=str(ROOT / "release_manifest.json"))
    args = parser.parse_args()

    settings = Settings(data_root=str(Path(args.data_root).expanduser()), _env_file=None)
    data_root = settings.data_root_path

    packages = sorted((data_root / "final_evidence").glob("EXP-*/")) \
        if (data_root / "final_evidence").is_dir() else []
    evidence = []
    for pkg in packages:
        if not pkg.is_dir() or not (pkg / MANIFEST_NAME).is_file():
            continue
        manifest = _read_json(pkg / MANIFEST_NAME) or {}
        verify = verify_frozen(settings, pkg.name)
        digest = None
        if (pkg / FROZEN_DIGEST_NAME).is_file():
            digest = (pkg / FROZEN_DIGEST_NAME).read_text(encoding="utf-8").strip()
        evidence.append({
            "experiment_id": pkg.name,
            "pair_id": manifest.get("pair_id"),
            "artifact_count": manifest.get("artifact_count"),
            "final_evidence_sha256": digest,
            "verify_status": verify.get("status"),
        })

    fingerprint_record = _read_json(data_root / "reports" / "m12_reproducibility.json")
    freeze = configuration_chain(settings=settings)
    recomputed_fingerprint = freeze.get("fingerprint")

    repro = None
    if fingerprint_record and isinstance(fingerprint_record, dict):
        evidence_rec = fingerprint_record.get("evidence") or {}
        repro = {
            "status": evidence_rec.get("status"),
            "runs": list(evidence_rec.get("runs", {}).keys()),
            "subject_verdicts": evidence_rec.get("subjects", {}),
            "recorded_fingerprint": next(
                (r.get("configuration_fingerprint")
                 for r in (evidence_rec.get("runs") or {}).values()), None),
        }

    regression = _read_json(ROOT / "perf" / "m13_regression.json")
    perf_record = _read_json(ROOT / "perf" / "m13_performance.json")

    payload = {
        "schema_version": "M13-RELEASE-MANIFEST-001",
        "application": "CHANDRASUTRA (SIH26166)",
        "release_version": settings.release_version,
        "release_milestone": settings.release_milestone,
        "engineering_version": settings.app_version,
        "engineering_milestone": settings.milestone,
        "generated_at_utc": rfc3339_now(),
        "evidence": evidence,
        "configuration": {
            "recorded_fingerprint": repro["recorded_fingerprint"] if repro else None,
            "recomputed_fingerprint": recomputed_fingerprint,
            "fingerprint_matches": bool(repro and repro["recorded_fingerprint"] == recomputed_fingerprint),
        },
        "reproducibility": repro or {"status": "NOT_RECORDED"},
        "regression": regression,
        "measurements": {
            "status": (perf_record or {}).get("status", "NOT_MEASURED"),
            "hosted": (perf_record or {}).get("hosted", "NOT_MEASURED"),
        },
        "honest_limits": {
            "real_data": "BLOCKED", "reference": "NOT_AVAILABLE",
            "physical_accuracy": "NOT_CLAIMED", "provenance": "PARTIAL_HOLD",
            "hosted_url": "NOT_AVAILABLE",
        },
    }

    out = Path(args.out).expanduser()
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {out}")
    print(f"  evidence packages: {len(evidence)}")
    for e in evidence:
        print(f"    {e['experiment_id']}: {e['verify_status']} sha={e['final_evidence_sha256']}")
    print(f"  recorded fingerprint matches recomputed: "
          f"{payload['configuration']['fingerprint_matches']}")
    print(f"  reproducibility: {repro['status'] if repro else 'NOT_RECORDED'}")
    print(f"  regression record present: {regression is not None}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())