"""Provenance manifest writer for M2 processing runs.

Every PREPARE run produces ``processing_manifest.json`` next to its derived
artifacts. The manifest is the single source of truth for *what* the run did,
*with which* configuration, *from* which raw bytes (SHA-256 re-verified) and
*to* which derived files (also hashed). Paths that are necessarily absolute
in Python are recorded as relative paths under the data root so the manifest
is portable, inspectable and reproducible.
"""

from __future__ import annotations

import hashlib
import json
import datetime
from pathlib import Path
from typing import Any

from ..config import m2_config


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(1 << 20)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def rel_string(data_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(data_root.resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return path.name


class ManifestBuilder:
    """Incremental provenance manifest for one processing run."""

    def __init__(self, *, data_root: Path, application: str, app_version: str, milestone: str,
                 configuration: dict[str, Any], pair_id: str, products: list[dict[str, Any]]):
        self.data_root = data_root
        self.payload: dict[str, Any] = {
            "schema_version": 1,
            "pipeline": {
                "application": application,
                "version": app_version,
                "milestone": milestone,
                "created_at_utc": _now(),
                "note": "Provenance manifest — derived products only; raw products are immutable and never recorded as derived.",
            },
            "configuration": configuration,
            "pair": {
                "pair_id": pair_id,
            },
            "products": products,  # [{side, sensor, filename, label_filename, raw_sha256, ...}]
            "steps": [],
            "geometry": None,
            "overlap": None,
            "normalization": None,
            "tiles": None,
            "conditions": None,
            "matcher_readiness": None,
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
                "sha256": _sha256(path),
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


def load_manifest(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None