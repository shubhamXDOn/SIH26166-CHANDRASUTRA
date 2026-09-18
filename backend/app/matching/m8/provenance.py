"""M8 provenance chain segment.

M8 sits on top of M2 (tiles/conditions), M3 (classical candidate evidence) and
extends into the correspondence evidence pool. It never writes absolute paths
and never claims a scientific accuracy verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...registration.provenance import _artifact, _json_abs


def build_m8_provenance(
    pair_id: str,
    data_root: Path,
    *,
    m3_run_dir: Path | None,
    m8_run_dir: Path | None,
    m8_status: dict[str, Any] | None = None,
    m8_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """A provenance chain node for an M8 expansion run (or None when absent)."""
    if m8_run_dir is None:
        return None
    artifacts = [
        _artifact(m8_run_dir / "m8_status.json", "m8_status", data_root)
        if (m8_run_dir / "m8_status.json").is_file() else None,
        _artifact(m8_run_dir / "summary.json", "m8_summary", data_root)
        if (m8_run_dir / "summary.json").is_file() else None,
    ]
    return {
        "milestone": "M8",
        "role": "deep-matcher expansion (benchmarking + adaptive routing evidence pool)",
        "configuration_id": (m8_status or {}).get("configuration_id")
        or (m8_summary or {}).get("configuration_id"),
        "m3_configuration_id": (m8_status or {}).get("m3_configuration_id")
        or ((m3_run_dir and _json_abs(str(m3_run_dir / "summary.json"))) or {}).get("configuration_id"),
        "artifacts": [a for a in artifacts if a],
        "note": (
            "M8 candidates are matcher observations against the same tiles, "
            "never verified truth — M4 Trust Gate remains the verification authority."
        ),
    }