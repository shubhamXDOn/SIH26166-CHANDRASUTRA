"""M7 reproducible experiment reports — report.json + deterministic report.md."""

from __future__ import annotations

from backend.app.config import rfc3339_now
from backend.app.metrics.reference import reference_dataset_status


def build_report_json(
    experiment: dict,
    pair_id: str,
    configuration_chain: dict,
    validation: dict,
    metrics: list[dict],
    recompute: dict,
    attrition: dict,
    run_state: str,
    generated_at: str | None = None,
) -> dict:
    return {
        "schema_version": "1.0",
        "application": "CHANDRASUTRA (SIH26166)",
        "experiment_id": experiment.get("experiment_id"),
        "pair_id": pair_id,
        "configuration_chain": configuration_chain,
        "reference": reference_dataset_status(),
        "run_state": run_state,
        "validation": validation,
        "attrition": attrition,
        "recompute": recompute,
        "metrics": metrics,
        "generated_at_utc": generated_at or rfc3339_now(),
        "note": (
            "All metrics are measurements of pipeline evidence, never a claim of "
            "scientific alignment accuracy. Blocked stages report NOT_RUN/BLOCKED; "
            "physical_accuracy is NOT_AVAILABLE because no reference dataset exists."
        ),
    }


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, dict):
        return " ".join(f"{k}={_fmt(v)}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(_fmt(v) for v in value)
    return str(value)


def build_report_markdown(report: dict) -> str:
    """Deterministic markdown — no timestamps, byte-identical for equal inputs."""
    exp_id = report.get("experiment_id", "EXP-????")
    chain = report.get("configuration_chain") or {}
    metrics = report.get("metrics") or []

    def _metric_rows(category: str) -> list[dict]:
        return [m for m in metrics if m.get("category") == category]

    lines: list[str] = []
    lines.append("# CHANDRASUTRA M7 — Reproducible Experiment Report")
    lines.append("")
    lines.append("> Metrics are measurements of pipeline evidence, never a claim of")
    lines.append("> scientific alignment accuracy. Blocked stages report NOT_RUN/BLOCKED.")
    lines.append("")
    lines.append(f"- Experiment ID: `{exp_id}`")
    lines.append(f"- Pair: `{report.get('pair_id', '')}`")
    lines.append(f"- Run state: `{report.get('run_state', '')}`")
    if chain:
        lines.append("- Configuration chain:")
        for key, value in sorted(chain.items()):
            lines.append(f"  - `{key}`: `{_fmt(value)}`")
    lines.append("")
    lines.append("## Reference / physical truth")
    lines.append("")
    ref = report.get("reference") or {}
    lines.append(f"- Reference dataset: `{ref.get('reference_dataset', 'NOT_AVAILABLE')}`")
    lines.append(f"- {ref.get('note', '')}")
    lines.append("")
    lines.append("- physical_accuracy: NOT_AVAILABLE (never 0 or 100%)")
    lines.append("")

    lines.append("## Evidence funnel")
    lines.append("")
    funnel_ids = [
        "FUNNEL_M3_TILES", "FUNNEL_M3_CANDIDATES", "FUNNEL_M3_SUCCESS_TILES",
        "FUNNEL_M4_TRUSTED_TILES", "FUNNEL_M4_REJECTED_TILES",
        "FUNNEL_M4_TRUSTED_CORRESPONDENCES", "FUNNEL_M5_SELECTED_CORRESPONDENCES",
        "FUNNEL_M6_REGISTERED_CORRESPONDENCES",
    ]
    lines.append("| metric | value | unit | status |")
    lines.append("|---|---|---|---|")
    for mid in funnel_ids:
        m = next((x for x in metrics if x.get("metric_id") == mid), None)
        if m:
            lines.append(
                f"| {m['metric_id']} — {m['name']} | {_fmt(m['value'])} | {m.get('unit') or '—'} | {m.get('status')} |")
    lines.append("")
    lines.append("### Retention ratios (engineering diagnostics)")
    lines.append("")
    lines.append("| metric | value | unit | status |")
    lines.append("|---|---|---|---|")
    for mid in ("FUNNEL_M3_TO_M4_RETENTION", "FUNNEL_M4_TO_M5_RETENTION", "FUNNEL_M5_TO_M6_RETENTION"):
        m = next((x for x in metrics if x.get("metric_id") == mid), None)
        if m:
            lines.append(
                f"| {m['metric_id']} — {m['name']} | {_fmt(m['value'])} | {m.get('unit') or '—'} | {m.get('status')} |")
    lines.append("")

    attrition = report.get("attrition") or {}
    if attrition:
        lines.append("### Rejection / attrition by reason code (real artefacts only)")
        lines.append("")
        lines.append("| reason code | count |")
        lines.append("|---|---|")
        for code, count in sorted(attrition.items()):
            lines.append(f"| `{code}` | {count} |")
        lines.append("")

    lines.append("## Measured metrics")
    lines.append("")
    for category in ("OBSERVATION", "MEASUREMENT", "VALIDATION", "DIAGNOSTIC"):
        rows = _metric_rows(category)
        if not rows:
            continue
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| metric_id | value | unit | scientific status | status |")
        lines.append("|---|---|---|---|---|")
        for m in sorted(rows, key=lambda x: x.get("metric_id", "")):
            lines.append(
                f"| {m['metric_id']} | {_fmt(m['value'])} | {m.get('unit') or '—'} | "
                f"{m.get('scientific_status')} | {m.get('status')} |")
        lines.append("")

    lines.append("## Independent recomputation")
    lines.append("")
    recompute = report.get("recompute") or {}
    lines.append("| statistic | recomputed | recorded | consistent |")
    lines.append("|---|---|---|---|")
    if recompute.get("recomputed"):
        rec_mean = recompute.get("residual_mean_px")
        lines.append(f"| forward residual mean (px) | {_fmt(rec_mean)} | — | {recompute.get('consistent_with_fit')} |")
        lines.append(f"| recomputed inlier count | {_fmt(recompute.get('inlier_count'))} | — | — |")
        lines.append(f"| valid projection count | {_fmt(recompute.get('valid_projection_count'))} | — | — |")
        for item in recompute.get("match_mismatch") or []:
            lines.append(f"- `{item}`")
    else:
        lines.append(f"- recomputation not run: {recompute.get('reason', '') or recompute.get('status', '')}")
    lines.append("")

    lines.append("## Methodology notes")
    lines.append("")
    lines.append(
        "- Independent recomputation re-derives forward residuals, symmetric transfer,"
        " inlier count (policy threshold) and valid projection count directly from the"
        " fitted matrix and the selected evidence using M4 trust primitives."
    )
    lines.append("- This report is generated deterministically from artefacts; "
                 "see report.json for the generation timestamp.")
    lines.append("")
    lines.append("---")
    lines.append("CHANDRASUTRA M7 · metrics are measurements, not proof.")
    lines.append("")
    return "\n".join(lines)