"""Matching provenance manifest (M3).

A MATCH run writes ``matching_manifest.json`` next to its artifacts. It states
exactly which matcher configuration produced which candidates from which
preprocessing inputs (by relative path + SHA-256 of the consumed M2
artifacts) — so the match run is reproducible from the manifest alone within
the same data root. No absolute paths are recorded.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from ..processing.manifest import rel_string


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class MatchingManifestBuilder:
    def __init__(self, *, data_root: Path, application: str, app_version: str, milestone: str,
                 configuration: dict[str, Any], pair_id: str,
                 processing_inputs: dict[str, Any]):
        self.data_root = data_root
        self.payload: dict[str, Any] = {
            "schema_version": 2,
            "pipeline": {
                "application": application,
                "version": app_version,
                "milestone": milestone,
                "created_at_utc": _now(),
                "note": "Matching provenance manifest — candidate correspondences only; never a verified truth/trust verdict.",
            },
            "configuration": configuration,
            "pair": {"pair_id": pair_id},
            "processing_inputs": processing_inputs,
            "steps": [],
            "strategy": None,
            "candidates": None,
            "summary": None,
        }
        self._current_step: dict[str, Any] | None = None

    def begin_step(self, step_id: str, label: str) -> None:
        self._current_step = {
            "id": step_id,
            "label": label,
            "started_at_utc": _now(),
            "finished_at_utc": None,
            "status": "RUNNING",
            "outputs": [],
        }

    def finish_step(self, *, outputs: list[Path], status: str = "OK") -> None:
        if self._current_step is None:
            return
        step = self._current_step
        step["finished_at_utc"] = _now()
        step["status"] = status
        for path in outputs:
            step["outputs"].append({
                "rel_path": rel_string(self.data_root, path),
                "sha256": sha256_of(path),
            })
        self.payload["steps"].append(step)
        self._current_step = None

    def record(self, **fields: Any) -> None:
        for key, value in fields.items():
            if key in self.payload and value is not None:
                self.payload[key] = value

    def write(self, manifest_path: Path) -> Path:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.payload, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(manifest_path)
        return manifest_path


def load_matching_manifest(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None