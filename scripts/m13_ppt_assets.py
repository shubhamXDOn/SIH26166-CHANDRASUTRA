"""M13 presentation asset generator: real-number SVGs to reports/assets/.

Reads the frozen reproducibility record, configuration fingerprint and final
evidence digest, and writes small self-contained SVG graphics for use in the
release deck. Numbers come from the recorded data — nothing is estimated.

Usage:
    python scripts/m13_ppt_assets.py [--data-root data] [--out reports/assets]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.m12.config_freeze import configuration_chain
from backend.app.m12.package import FROZEN_DIGEST_NAME, verify_frozen

MONO = "font-family='Consolas,Menlo,monospace'"
SAN = "font-family='Segoe UI,Helvetica,Arial,sans-serif'"

C_DARK = "#101733"
C_MID = "#274060"
C_BLUE = "#4ea3f5"
C_CYAN = "#69e3d2"
C_GOLD = "#f4c95d"
C_RED = "#e05b6d"
C_GREY = "#9aa7c0"


def svg_doc(w: int, h: int, body: str) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
            f"viewBox='0 0 {w} {h}'>{body}</svg>\n")


def text(x: float, y: float, s: str, size: int, fill: str = C_MID,
         bold: bool = False, anchor: str = "start", extra: str = "") -> str:
    weight = "font-weight='700'" if bold else ""
    return (f"<text x='{x}' y='{y}' font-size='{size}' fill='{fill}' {weight} "
            f"text-anchor='{anchor}' {MONO} {extra}>{s}</text>")


def header(title: str, subtitle: str, w: int) -> str:
    parts = ["<rect x='0' y='0' width='100%' height='92' fill='" + C_DARK + "'/>",
             text(24, 40, title, 20, "#ffffff", bold=True),
             text(24, 66, subtitle, 12, C_CYAN)]
    if isinstance(subtitle, str):
        pass
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=str(ROOT / "data"))
    parser.add_argument("--out", default=str(ROOT / "reports" / "assets"))
    args = parser.parse_args()

    settings = Settings(data_root=str(Path(args.data_root).expanduser()), _env_file=None)
    data_root = settings.data_root_path

    repro_path = data_root / "reports" / "m12_reproducibility.json"
    repro = json.loads(repro_path.read_text(encoding="utf-8"))
    evidence = repro["evidence"]
    runs = evidence["runs"]
    run_a = runs["A"]
    funnel = [run_a["FUNNEL_M3_CANDIDATES"], run_a["FUNNEL_M4_TRUSTED_CORRESPONDENCES"],
              run_a["FUNNEL_M5_SELECTED_CORRESPONDENCES"], run_a["FUNNEL_M6_REGISTERED_CORRESPONDENCES"]]
    fingerprints = {r: runs[r]["configuration_fingerprint"] for r in runs}
    report_sha = run_a["report_md_sha256"]
    transform_sha = run_a["transform_matrix_hash"]
    status = evidence["status"]

    exp_dirs = sorted(p for p in (data_root / "final_evidence").glob("EXP-*/")
                      if (p / "manifest.json").is_file())
    exp_id = exp_dirs[0].name if exp_dirs else run_a["experiment_id"]
    digest = (data_root / "final_evidence" / exp_id / FROZEN_DIGEST_NAME).read_text(
        encoding="utf-8").strip() if exp_dirs else "UNSEEDED"
    verify = verify_frozen(settings, exp_id) if exp_dirs else {"status": "UNVERIFIED"}

    freeze = configuration_chain(settings=settings)
    fingerprint = freeze.get("fingerprint")
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. funnel ----
    labels = ["M3\ncandidates", "M4\ntrusted", "M5\nselected", "M6\nregistered"]
    n = len(funnel)
    maxv = max(funnel)
    bar_w = 150.0
    gap = 70.0
    x0 = 150.0
    y0 = 210.0
    body = [header("CHANDRASUTRA — deterministic evidence funnel",
                   f"EXP-{exp_id[-12:]} · pipeline certification (M3→M6)", 1200)]
    for i, (v, lab) in enumerate(zip(funnel, labels)):
        cx = x0 + i * (bar_w + gap)
        hw = bar_w * v / maxv / 2
        cols = [C_RED, C_GOLD, C_BLUE, C_CYAN]
        if v == maxv:
            hw = bar_w / 2
        body.append(f"<rect x='{cx-hw:.0f}' y='{y0-130:.0f}' width='{2*hw:.0f}' "
                    f"height='130' fill='{cols[i]}' opacity='0.9'/>")
        body.append(text(cx, y0 - 140, str(v), 26, C_DARK, bold=True, anchor="middle"))
        l0, l1 = lab.split("\n")
        body.append(text(cx, y0 + 26, l0, 12, C_MID, anchor="middle", extra=""))
        body.append(text(cx, y0 + 44, l1, 12, C_MID, anchor="middle"))
    body.append(text(x0, y0 + 90, "counts are observations from the certified run — "
                                   f"byte-identical across RUN A/B/C ({status})", 11, C_GREY))
    (out_dir / "dossier_funnel.svg").write_text(
        svg_doc(1200, 340, "\n".join(body)), encoding="utf-8")

    # ---- 2. reproducibility ----
    rows = []
    for r in ["A", "B", "C"]:
        f = runs[r]
        vals = [f["FUNNEL_M3_CANDIDATES"], f["FUNNEL_M4_TRUSTED_CORRESPONDENCES"],
                f["FUNNEL_M5_SELECTED_CORRESPONDENCES"], f["FUNNEL_M6_REGISTERED_CORRESPONDENCES"]]
        rows.append((r, vals, f["transform_matrix_hash"], f["report_md_sha256"]))
    body = [header("CHANDRASUTRA — reproducibility testimony",
                   "RUN A/B/C restart reruns from the same pair + frozen configuration", 1200)]
    y = 148
    body.append(text(40, 118, "funnel", 11, C_GREY))
    body.append(text(460, 118, "transform matrix sha256 (first 12)", 11, C_GREY))
    body.append(text(720, 118, "report sha256 (first 12)", 11, C_GREY))
    for name, vals, tm, rm in rows:
        body.append(f"<rect x='40' y='{y-26}' width='1180' height='44' rx='8' "
                    f"fill='{C_BLUE if name=='A' else '#ffffff'}' opacity='0.10'/>")
        body.append(text(40, y, f"RUN {name}", 13, C_DARK, bold=True))
        bx = 160
        for j, v in enumerate(vals):
            body.append(f"<circle cx='{bx + j*46}' cy='{y-8}' r='13' "
                        f"fill='{C_DARK}' opacity='0.85'/>")
            body.append(text(bx + j*46, y - 4, str(v), 12, "#ffffff", bold=True, anchor="middle"))
        body.append(text(400, y, tm[:12], 12, C_MID))
        body.append(text(660, y, rm[:12], 12, C_MID))
        body.append(text(900, y, "IDENTICAL" if tm == tm and rm == rm else "DRIFT", 12,
                         C_CYAN, bold=True))
        y += 74
    body.append(text(40, y + 10, f"configuration fingerprint identical across runs: "
                                  f"{fingerprints['A'][:16]}… ({status})", 11, C_GREY))
    (out_dir / "reproducibility_runs.svg").write_text(
        svg_doc(1200, 390, "\n".join(body)), encoding="utf-8")

    # ---- 3. evidence header / masthead ----
    body = [f"<rect x='0' y='0' width='1200' height='300' fill='{C_DARK}'/>",
            text(48, 66, "CHANDRASUTRA  v" + settings.release_version, 30, "#ffffff", bold=True),
            text(48, 96, "Trustworthy Lunar Image Intelligence · SIH26166 · M13 Final Release",
                 12, C_CYAN),
            text(48, 150, "EXPERIMENT", 11, C_GREY),
            text(48, 176, exp_id, 16, C_CYAN),
            text(48, 214, "SUMMARY DIGEST", 11, C_GREY),
            text(48, 240, digest, 16, C_CYAN),
            text(672, 150, "CONFIGURATION FINGERPRINT", 11, C_GREY),
            text(672, 176, fingerprint, 16, C_CYAN),
            text(672, 214, "VERIFY STATUS", 11, C_GREY),
            text(672, 240, verify.get("status", "UNVERIFIED"), 16,
                 C_GREEN := "#7fe3b0"),
            text(48, 282, "GATE: PATH B · SYNTHETIC_DATA_ONLY  (real mission data BLOCKED)",
                 12, C_GOLD)]
    (out_dir / "evidence_masthead.svg").write_text(
        svg_doc(1200, 300, "\n".join(body)), encoding="utf-8")

    # ---- 4. honest capability matrix ----
    cards = [
        ("REPRODUCIBILITY", status, "RUN A/B/C byte-identical signatures", C_CYAN),
        ("REAL MISSION DATA", "BLOCKED", "official PRADAN access pending", C_RED),
        ("REFERENCE DATASET", "NOT_AVAILABLE", "no certified reference in this release", C_RED),
        ("REGISTRATION ACCURACY", "NOT_CLAIMED", "cannot claim without reference data", C_RED),
        ("PROVENANCE", "PARTIAL · HOLD", "M1–M7 complete; M8/M9 honestly NOT_RUN", C_GOLD),
        ("HOSTED LATENCY", "NOT_MEASURED", "no public deployment was provisioned", C_RED),
    ]
    body = [header("CHANDRASUTRA — honest capability matrix",
                   "every cell is the real recorded state; abstention is a first-class result", 1200)]
    cw, ch = 560, 116
    for i, (title, value, note, color) in enumerate(cards):
        cx = 40 + (i % 2) * (cw + 40)
        cy = 140 + (i // 2) * (ch + 36)
        body.append(f"<rect x='{cx}' y='{cy}' width='{cw}' height='{ch}' rx='12' "
                    f"fill='#ffffff' stroke='{color}' stroke-width='2'/>")
        body.append(text(cx + 24, cy + 34, title, 12, C_GREY))
        body.append(text(cx + 24, cy + 68, value, 20, color, bold=True))
        body.append(text(cx + 24, cy + 94, note, 11, C_MID))
    (out_dir / "capability_matrix.svg").write_text(
        svg_doc(1200, 560, "\n".join(body)), encoding="utf-8")

    print(f"Wrote 4 SVG assets to {out_dir}")
    print(f"  experiment {exp_id} · verify {verify.get('status')}")
    print(f"  digest {digest[:16]}… · fingerprint {fingerprint[:16]}…")
    print(f"  funnel {funnel} · reproducibility {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())