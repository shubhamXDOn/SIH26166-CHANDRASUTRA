"""M12 reproducibility proof — RUN A / RUN B / RUN C (CHANDRASUTRA SIH).

Proves that a canonical experiment workspace produces byte-level identical
evidence no matter which workspace or how many times it is re-run:

  * RUN A  — pipeline executed from scratch in workspace A
            (M2 prepare -> M3 match -> M4 trust -> M5 spatial ->
             M6 registration -> M7 metrics), then RUN A is re-run
  * RUN B  — identical re-run of RUN A inside the SAME workspace
            (recompute and overwrite)
  * RUN C  — identical pipeline executed from scratch in a FRESH
            clean-room workspace (different random tmp dir, same seeds)

A deterministic signature is computed for each run from on-disk artifacts
(experiment id, funnel metrics, recomputed residuals, transform hash, report
hash) and compared. The configuration freeze fingerprint must agree across all
three runs. A copy of the full final evidence package is frozen over RUN A.

Run:  .\\.venv\\Scripts\\python.exe scripts\\m12_reproducibility.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))
os.environ.setdefault("LOG_LEVEL", "ERROR")

import test_m6 as m6h  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.config import m4_config, m5_config, m6_config, m7_config  # noqa: E402
from backend.app.data import ensure_derived_directories  # noqa: E402
from backend.app.m12.config_freeze import configuration_chain  # noqa: E402
from backend.app.m12.reproducibility import compare_signatures  # noqa: E402
from backend.app.m12.reproducibility import compute_run_signature  # noqa: E402
from backend.app.metrics.service import MetricsService  # noqa: E402
from backend.app.registration.service import RegistrationService  # noqa: E402

PA = "CS-P001"


def _run_pipeline(root: Path, *, build_tree: bool) -> dict:
    settings = Settings(data_root=str(root), _env_file=None)
    ensure_derived_directories(settings)
    if build_tree:
        m6h._build_m6_ready_tree(settings, PA)
    RegistrationService(
        root, m6_cfg=m6_config(), m5_cfg=m5_config(),
        m4_defaults=m4_config()["defaults"]).run(PA)
    met = MetricsService(
        root, m7_cfg=m7_config(), m6_cfg=m6_config(),
        m5_cfg=m5_config(), m4_defaults=m4_config()["defaults"])
    status = met.run(PA)
    if not isinstance(status, dict) or status.get("state") != "COMPLETE":
        raise RuntimeError(f"M7 not COMPLETE: {status}")
    sig = compute_run_signature(settings, PA)
    freeze = configuration_chain(settings=settings)
    sig["configuration_fingerprint"] = freeze["fingerprint"]
    sig["workspace"] = str(root)
    return sig


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    base = Path(tempfile.mkdtemp(prefix="cs_m12_repro_"))
    work_a = base / "workspace_A"
    work_c = base / "workspace_C"
    work_a.mkdir(parents=True)
    work_c.mkdir(parents=True)

    print("[M12] RUN A: pipeline from scratch in workspace A ...")
    sig_a = _run_pipeline(work_a, build_tree=True)
    print("[M12] RUN B: identical re-run in the SAME workspace A ...")
    sig_b = _run_pipeline(work_a, build_tree=False)
    print("[M12] RUN C: pipeline from scratch in fresh workspace C ...")
    sig_c = _run_pipeline(work_c, build_tree=True)

    for key in ("workspace",):
        sig_a.pop(key, None)
        sig_b.pop(key, None)
        sig_c.pop(key, None)
    verdict = compare_signatures({"A": sig_a, "B": sig_b, "C": sig_c})
    print("[M12] verdict:", verdict["status"])
    for subject, status in verdict["subjects"].items():
        print(f"      {subject:36s} {status}")

    reports = REPO_ROOT / "reports"
    reports.mkdir(exist_ok=True)
    out = {
        "schema_version": "M12-REPRO-RUN",
        "evidence": verdict,
        "note": "Synthetic correlated pair; engineering determinism proof only — no scientific claim. "
                "Configuration freeze fingerprint equal across all three runs is the primary check.",
    }
    out["evidence"]["runs"] = {
        n: {k: v for k, v in runs.items() if k != "workspace"}
        for n, runs in out["evidence"]["runs"].items()
    }
    (reports / "m12_reproducibility.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    md = REPO_ROOT / "IP_REPRODUCIBILITY.md"
    section = (
        "\n---\n\n## M12 runtime reproducibility (RUN A / RUN B / RUN C)\n\n"
        f"- Verdict: **{verdict['status']}**\n"
        f"- Subject keys compared: {len(verdict['subjects'])}\n"
        f"- Configuration freeze fingerprint equal across A/B/C: "
        f"{sig_a['configuration_fingerprint'] == sig_b['configuration_fingerprint'] == sig_c['configuration_fingerprint']}"
        f" (`{sig_a['configuration_fingerprint'][:16]}...`)\n"
        f"- Drifted subjects: {verdict['drifted_subjects'] or 'none'}\n"
        f"- Detail: `reports/m12_reproducibility.json` (regenerated by "
        f"`scripts/m12_reproducibility.py`; synthetic correlated pair, no scientific claim).\n"
    )
    with open(md, "a", encoding="utf-8") as f:
        f.write(section)

    print("[M12] wrote reports/m12_reproducibility.json and updated IP_REPRODUCIBILITY.md")
    return 0 if verdict["status"] == "REPRODUCIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())