"""M13 release preparation: seed frozen evidence + report centre into a data root.

This is a release staging step, not a scientific computation. It copies the
already-frozen M12 evidence packages byte-for-byte into the target data root
(``<data_root>/final_evidence/``) and the milestone report centre
(``<data_root>/reports/``), then RE-VERIFIES every seeded package so that a
release can never ship a package whose recorded FINAL_EVIDENCE_SHA256 no longer
matches its contents. No artifact is regenerated or recomputed here.

The copy/prune strategy is OneDrive-safe: existing files are overwritten in
place and stale files are removed file-by-file (with retries) instead of
recursively deleting directories, which cloud-sync watchers can lock.

Usage:
    python scripts/m13_release_prep.py [--data-root <path>]
                                       [--evidence-src <path>]
                                       [--reports-src <path>]

Defaults: data-root ``data``, evidence sourced from the frozen M12 master
workspace, reports sourced from the repository ``reports/`` directory.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings
from backend.app.m12.package import verify_frozen


RETRIES = 4


def _unlink(path: Path) -> bool:
    for attempt in range(RETRIES):
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            if attempt == RETRIES - 1:
                return False
            time.sleep(0.4)
    return False


def _file_manifest(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _sync_copy(src_root: Path, dst_root: Path) -> int:
    """Bring ``dst_root`` tree into exact agreement with ``src_root`` (OneDrive-safe)."""
    if not src_root.is_dir():
        return 0
    dst_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_root, dst_root, dirs_exist_ok=True)
    _prune_to(dst_root, _file_manifest(src_root))
    for p in sorted(dst_root.rglob("*"), key=lambda q: -len(q.parts)):
        if p.is_dir() and not any(p.iterdir()):
            _unlink_tree_dir(p)
    return sum(1 for _ in dst_root.rglob("*") if _.is_file())


def _prune_to(root: Path, keep: set[str]) -> None:
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*"), key=lambda q: -len(q.parts)):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel not in keep and not _unlink(p):
            print(f"  warning: could not remove leftover {rel} (locked)", file=sys.stderr)


def _unlink_tree_dir(path: Path) -> None:
    for attempt in range(RETRIES):
        try:
            path.rmdir()
            return
        except OSError:
            if attempt == RETRIES - 1:
                return
            time.sleep(0.4)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the M13 release staging area.")
    parser.add_argument("--data-root", default=str(Path("data")))
    parser.add_argument("--evidence-src", default=str(ROOT / "perf" / "m12_master_workspace" / "final_evidence"))
    parser.add_argument("--reports-src", default=str(ROOT / "reports"))
    args = parser.parse_args()

    data_root = Path(args.data_root).expanduser()
    data_root.mkdir(parents=True, exist_ok=True)

    ev_src = Path(args.evidence_src).expanduser()
    reps_src = Path(args.reports_src).expanduser()

    # Only packages that verify cleanly in the source workspace may ship. This
    # deliberately excludes superseded or incomplete experiment folders that can
    # exist in a development workspace (e.g. replaced intermediates).
    src_settings = Settings(data_root=str(ev_src.parent), _env_file=None)
    candidates = sorted((ev_src).glob("*/")) if ev_src.is_dir() else []
    chosen: list[Path] = []
    for pkg in candidates:
        if not pkg.is_dir() or not (pkg / "manifest.json").is_file():
            continue
        result = verify_frozen(src_settings, pkg.name)
        if result.get("status") == "VERIFIED":
            chosen.append(pkg)
        else:
            print(f"  ignoring unverified source package {pkg.name} "
                  f"({result.get('status')} {result.get('reason', '')})")

    n_ev = 0
    if chosen:
        final_evidence = data_root / "final_evidence"
        final_evidence.mkdir(parents=True, exist_ok=True)
        keep: set[str] = set()
        n_ev = 0
        for pkg in chosen:
            target = final_evidence / pkg.name
            shutil.copytree(pkg, target, dirs_exist_ok=True)
            keep |= {f"{pkg.name}/{rel}" for rel in _file_manifest(pkg)}
            n_ev += len(_file_manifest(pkg))
        _prune_to(final_evidence, keep)
        for p in sorted(final_evidence.rglob("*"), key=lambda q: -len(q.parts)):
            if p.is_dir() and not any(p.iterdir()):
                _unlink_tree_dir(p)

    n_reps = _sync_copy(reps_src, data_root / "reports")

    src_perf = next(ROOT.glob("perf/m13_performance.json"), None)
    perf_payload = False
    if src_perf and src_perf.is_file():
        dst = data_root / "reports" / "m13_performance.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not _unlink(dst):
            try:
                dst.unlink()
            except OSError:
                pass
        shutil.copyfile(src_perf, dst)
        perf_payload = True

    settings = Settings(data_root=str(data_root), _env_file=None)
    verified = []
    degraded = []
    for pkg in sorted((data_root / "final_evidence").glob("*/")):
        if not pkg.is_dir() or not (pkg / "manifest.json").is_file():
            continue
        result = verify_frozen(settings, pkg.name)
        (verified if result.get("status") == "VERIFIED" else degraded).append((pkg.name, result))
        print(f"  [{result.get('status'):<18}] {pkg.name}  sha={result.get('recorded_final_evidence_sha256')}")

    print(f"Seeded {n_ev} evidence files across {len(verified) + len(degraded)} package(s), "
          f"{n_reps} report files into {data_root}.")
    print(f"measurements served: {bool(perf_payload)}")
    if degraded:
        print("ERROR: the following seeded packages failed re-verification:", file=sys.stderr)
        for exp_id, result in degraded:
            print(f"  {exp_id}: {result.get('status')} {result.get('reason', '')}", file=sys.stderr)
        return 1
    if not verified:
        print("WARNING: no evidence packages were seeded; release data root has no frozen evidence.",
              file=sys.stderr)
        return 2
    print("OK: every seeded evidence package re-verified cleanly.")
    return 0


def _dummy_src(chosen: Iterable[Path]) -> Path:
    """Compatibility shim — not used; _sync_copy is invoked per package below."""
    del chosen
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())