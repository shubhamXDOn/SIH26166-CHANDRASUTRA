"""M12 final evidence package: directory, manifest, frozen digest, verification.

Produces ``<data_root>/final_evidence/<experiment_id>/`` containing the frozen
scientific evidence for a pair: experiment identity, real-data gate, config
freeze, provenance chain, independent audits, AI cross-check, the M12 report,
and a relative-path copy of every referenced pipeline artifact (raw images are
never copied — they stay referenced by the pair record + SHA-256).

``manifest.json`` lists every package file with its SHA-256; the frozen digest
``FINAL_EVIDENCE_SHA256`` is the hash of the manifest itself so any post-freeze
modification of the package (including the manifest) is detected by
``verify_frozen``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from backend.app.config import rfc3339_now
from backend.app.m12.config_freeze import write_configuration_freeze

_SECRET_PATTERNS = (
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}\b"), "google_api_key"),
    (re.compile(r"(?i)(api[_-]?key|access[_-]?token|auth[_-]?token|secret)\s*[:=]\s*\S+"), "credential"),
    (re.compile(r"(?i)authorization\s*[:=]\s*bearer\s+\S+"), "bearer_token"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private_key"),
)

MANIFEST_NAME = "manifest.json"
FROZEN_DIGEST_NAME = "FINAL_EVIDENCE_SHA256"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_secrets(root: Path) -> dict[str, Any]:
    """Scan a directory tree for secret material (for the security scan)."""
    hits: list[dict[str, str]] = []
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name in (MANIFEST_NAME,):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern, kind in _SECRET_PATTERNS:
                if pattern.search(text):
                    hits.append({
                        "kind": kind,
                        "file": path.relative_to(root).as_posix(),
                    })
                    break
    return {"status": "CLEAN" if not hits else "SECRET_FOUND", "hits": hits}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _copy_artifacts(provenance: dict[str, Any], data_root: Path, package_dir: Path) -> list[tuple[Path, str]]:
    copied: list[tuple[Path, str]] = []
    for stage in (provenance or {}).get("chain", []):
        for artifact in stage.get("artifacts", []):
            rel = artifact.get("path")
            if not rel:
                continue
            src = data_root / rel
            if not src.is_file():
                continue
            dst = package_dir / "pipeline" / stage.get("milestone", "STAGE") / Path(rel).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists():
                shutil.copyfile(src, dst)
            copied.append((dst, rel))
    return copied


def build_final_evidence(
    pair_id: str,
    settings: Any,
    *,
    experiment_id: str,
    gate: dict[str, Any],
    freeze: dict[str, Any],
    provenance: dict[str, Any],
    audits: dict[str, Any],
    crosscheck: dict[str, Any],
    report_md: str,
    notes: str = "",
) -> dict[str, Any]:
    """Assemble and freeze the final evidence package for a pair."""
    from backend.app.pairs import PairRegistry

    data_root: Path = settings.data_root_path
    record = PairRegistry(settings).get(pair_id)
    ev_root = data_root / "final_evidence" / experiment_id
    shutil.rmtree(ev_root, ignore_errors=True)

    (ev_root / "pipeline").mkdir(parents=True, exist_ok=True)

    _write_json(ev_root / "experiment.json", {
        "application": "CHANDRASUTRA (SIH26166)",
        "schema_version": "M12-EVIDENCE-001",
        "experiment_id": experiment_id,
        "pair_id": pair_id,
        "gate": gate,
        "notes": notes,
        "generated_at_utc": rfc3339_now(),
    })
    _write_json(ev_root / "pair.json", record.model_dump() if record else {})
    write_configuration_freeze(freeze, settings, experiment_id, ev_root)
    ev_root.joinpath("provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    _write_json(ev_root / "audits.json", audits)
    _write_json(ev_root / "crosscheck.json", crosscheck)
    (ev_root / "report.md").write_text(report_md, encoding="utf-8")

    copied = _copy_artifacts(provenance, data_root, ev_root)
    copied_map = {str(dst): src_rel for dst, src_rel in copied}

    security = scan_secrets(ev_root)
    _write_json(ev_root / "security.json", security)

    entries: list[dict[str, Any]] = []
    for path in sorted(ev_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ev_root).as_posix()
        if rel == MANIFEST_NAME:
            continue
        entries.append({
            "path": rel,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
            "copied_from": copied_map.get(str(path), "generated-in-package"),
        })

    manifest = {
        "schema_version": "M12-EVIDENCE-MANIFEST-001",
        "application": "CHANDRASUTRA (SIH26166)",
        "experiment_id": experiment_id,
        "pair_id": pair_id,
        "artifact_count": len(entries),
        "pipeline_artifact_count": len(copied),
        "artifacts": entries,
        "note": (
            "Raw images are referenced by the pair record + registered SHA-256 and are "
            "never copied. The FINAL_EVIDENCE_SHA256 digest is the hash of this manifest; "
            "any post-freeze modification changes the digest."
        ),
    }
    manifest_path = _write_json(ev_root / MANIFEST_NAME, manifest)
    frozen = sha256_file(manifest_path)
    (ev_root / FROZEN_DIGEST_NAME).write_text(frozen + "\n", encoding="utf-8")

    return {
        "experiment_id": experiment_id,
        "pair_id": pair_id,
        "status": "FROZEN",
        "package_dir": ev_root.relative_to(data_root).as_posix(),
        "final_evidence_sha256": frozen,
        "manifest_file": MANIFEST_NAME,
        "artifact_count": len(entries),
        "security_scan": security["status"],
    }


def verify_frozen(settings: Any, experiment_id: str) -> dict[str, Any]:
    """Re-verify a frozen evidence package: digests + no unexpected changes."""
    ev_root: Path = settings.data_root_path / "final_evidence" / experiment_id
    if not ev_root.is_dir():
        return {"status": "NOT_FOUND", "experiment_id": experiment_id}
    manifest_path = ev_root / MANIFEST_NAME
    frozen_path = ev_root / FROZEN_DIGEST_NAME
    if not manifest_path.is_file() or not frozen_path.is_file():
        return {"status": "INCOMPLETE", "experiment_id": experiment_id,
                "reason": "manifest.json or FINAL_EVIDENCE_SHA256 missing"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    missing_files: list[str] = []
    modified_files: list[str] = []
    extra_files: list[str] = []
    listed = set()
    for entry in manifest.get("artifacts", []):
        rel = entry["path"]
        listed.add(rel)
        path = ev_root / rel
        if not path.is_file():
            missing_files.append(rel)
        elif sha256_file(path) != entry["sha256"]:
            modified_files.append(rel)
    for path in ev_root.rglob("*"):
        if not path.is_file() or path.name == MANIFEST_NAME or path.name == FROZEN_DIGEST_NAME:
            continue
        rel = path.relative_to(ev_root).as_posix()
        if rel not in listed:
            extra_files.append(rel)

    current_manifest_sha = sha256_file(manifest_path)
    recorded_frozen = frozen_path.read_text(encoding="utf-8").strip()
    manifest_modified = current_manifest_sha != recorded_frozen

    if missing_files or modified_files or extra_files or manifest_modified:
        return {
            "status": "INTEGRITY_DEGRADED",
            "experiment_id": experiment_id,
            "missing_files": missing_files,
            "modified_files": modified_files,
            "extra_files": extra_files,
            "manifest_modified_after_freeze": bool(manifest_modified),
            "recorded_final_evidence_sha256": recorded_frozen,
            "recomputed_final_evidence_sha256": current_manifest_sha,
        }
    return {
        "status": "VERIFIED",
        "experiment_id": experiment_id,
        "recorded_final_evidence_sha256": recorded_frozen,
        "recomputed_final_evidence_sha256": current_manifest_sha,
        "artifact_count": len(manifest.get("artifacts", [])),
    }


__all__ = [
    "sha256_file",
    "scan_secrets",
    "build_final_evidence",
    "verify_frozen",
    "MANIFEST_NAME",
    "FROZEN_DIGEST_NAME",
]