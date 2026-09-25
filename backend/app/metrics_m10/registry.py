"""Immutable M10 benchmark run registry.

Every benchmark run (a single pair x variant observation) is persisted as
``data/metadata/m10_metrics/benchmarks/{run_id}.json`` where

    run_id = m10-<8-hex-chars>

The registry is append-only for auditors: a run id is never reused and a
written file is never rewritten in place.  Reads tolerate a missing or
partial registry without raising; writes persist atomically via temp file +
``os.replace``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..config import Settings

_REG_DIR = "metadata/m10_metrics/benchmarks"


def _safe_run_id(run_id: str) -> bool:
    return bool(run_id) and all(c.isalnum() or c in "_-" for c in run_id) and run_id.startswith("m10-")


def new_run_id() -> str:
    digest = hashlib.sha1(os.urandom(8)).hexdigest()[:8]
    return "m10-%s" % digest


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


class BenchmarkRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.root = self.settings.data_root_path / Path(_REG_DIR)

    def artifact_path(self, run_id: str) -> Path:
        if not _safe_run_id(run_id):
            raise ValueError("refusing to build path for unsafe run id %r" % run_id)
        return self.root / ("%s.json" % run_id)

    def write(self, payload: dict[str, Any]) -> str:
        run_id = str(payload.get("run_id") or new_run_id())
        payload = dict(payload)
        payload["run_id"] = run_id
        path = self.artifact_path(run_id)
        if path.exists():
            raise FileExistsError("benchmark run %s already exists; registry is append-only" % run_id)
        payload.setdefault("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        payload.setdefault("registry", "M10-BMK-001")
        _write_json(path, payload)
        return run_id

    def read(self, run_id: str) -> dict[str, Any] | None:
        if not _safe_run_id(run_id):
            return None
        path = self.artifact_path(run_id)
        if not path.is_file():
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def list(self) -> list[dict[str, Any]]:
        if not self.root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for p in sorted(self.root.glob("m10-*.json")):
            rec = self.read(p.stem)
            if rec:
                out.append(rec)
        return out

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        runs = [r for r in self.list() if r.get("pair_id") == pair_id]
        if not runs:
            return None
        return max(runs, key=lambda r: r.get("created_at", ""))