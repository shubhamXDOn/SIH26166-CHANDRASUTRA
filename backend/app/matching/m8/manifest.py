"""M8 expansion provenance manifest.

An M8 run writes ``m8_manifest.json`` next to its artifacts. It records relative
paths + SHA-256 (never absolute paths) for every consumed M2/M3 artifact and the
produced M8 artifacts, plus the matcher/model identities used. Reproducible from
the manifest alone within the same data root.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..manifest import rel_string


def _now() -> str:
    import datetime

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


def _artifact(path: Path | None, data_root: Path) -> dict[str, Any] | None:
    if path is None or not Path(path).is_file():
        return None
    return {
        "rel_path": rel_string(data_root, Path(path)),
        "sha256": sha256_of(path),
    }


class M8ManifestBuilder:
    def __init__(self, *, data_root: Path, application: str, app_version: str, milestone: str,
                 configuration: dict[str, Any], pair_id: str,
                 matcher_model_identity: dict[str, Any],
                 processing_inputs: dict[str, Any]):
        self.data_root = data_root
        self.payload: dict[str, Any] = {
            "schema_version": 1,
            "pipeline": {
                "application": application,
                "version": app_version,
                "milestone": milestone,
                "created_at_utc": _now(),
                "note": "M8 expansion manifest — matcher observations only; never a truth/accuracy verdict.",
            },
            "configuration": configuration,
            "pair": {"pair_id": pair_id},
            "matcher_model_identity": matcher_model_identity,
            "processing_inputs": processing_inputs,
            "steps": [],
            "routing": None,
            "candidates": None,
            "benchmark": None,
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
            art = _artifact(path, self.data_root)
            if art:
                step["outputs"].append(art)
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


def load_m8_manifest(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None