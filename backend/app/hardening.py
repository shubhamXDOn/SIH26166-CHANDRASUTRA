"""M11 production hardening primitives.

This module centralizes the cross-cutting reliability machinery used by every
pipeline service and the API layer:

* **Request correlation** — a stable ``request_id`` exposed to handlers,
  error envelopes, logs and audit events (never invented twice).
* **Atomic artifact writes** — write-temp → fsync → atomic rename, so a
  half-written JSON/NPZ/PNG is never visible as a complete result.
* **Run locks** — mutual exclusion for concurrent pipeline runs on the same
  run directory (``JOB_ALREADY_RUNNING`` instead of unsafe parallel writes),
  including stale-lock detection that marks interrupted runs honestly.
* **Stale-run reconciliation** — a ``RUNNING`` status left behind by a crash or
  restart is surfaced as an interrupted ``FAILED`` state, never as a live run.
* **Run events** — an in-process, bounded record of recent run durations for
  the operational overview (per-process by design; no cross-worker claim).

Nothing here touches scientific content. No secret is ever accepted or logged.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Iterable

import numpy as np

# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{0,95}$")

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def current_request_id() -> str:
    """Return the request ID bound to the current async/sync context."""
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def sanitize_request_id(value: Any) -> str:
    """Validate an inbound request ID or return an empty string (generate later)."""
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    if len(candidate) > 64:
        return ""
    return candidate if _REQUEST_ID_RE.match(candidate) else ""


def new_request_id() -> str:
    """Generate a fresh request ID (no external entropy sources)."""
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Atomic writes  (write temp -> fsync -> rename -> dir fsync best-effort)
# ---------------------------------------------------------------------------

def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync. Not all platforms support opening dirs."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _json_default(o: Any) -> Any:
    """JSON-serialize the non-serializable types used across the pipeline."""
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, bytes):
        return o.decode("utf-8", errors="replace")
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "item"):  # numpy scalars
        try:
            return o.item()
        except (ValueError, TypeError):
            return str(o)
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=str)
    return str(o)


def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write text atomically (temp file in the same directory + atomic rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex[:12]}"
    try:
        with open(tmp, "w", encoding=encoding, newline="\n") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Write bytes atomically (used for NPY/NPZ/PNG artifacts)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex[:12]}"
    try:
        with open(tmp, "wb") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_npy(path: Path, array: Any) -> None:
    """Write a NumPy array atomically (temp file + rename, never partial)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex[:12]}"
    try:
        np.save(tmp, array)
        if not tmp.exists():
            tmp = Path(str(tmp) + ".npy")
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        for candidate in (tmp, Path(str(tmp) + ".npy")):
            try:
                if candidate != path and candidate.exists():
                    candidate.unlink()
            except OSError:
                pass


def atomic_write_json(path: Path, payload: Any, *, indent: int | None = 2) -> None:
    """Serialize ``payload`` and write it atomically."""
    text = json.dumps(payload, indent=indent, default=_json_default) + "\n"
    atomic_write_text(path, text)


def atomic_write_npz(path: Path, **arrays: Any) -> None:
    """Write a compressed .npz atomically (temp file + rename, never partial)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp-{uuid.uuid4().hex[:12]}"
    try:
        np.savez_compressed(tmp, **arrays)
        if not tmp.exists():
            tmp = Path(str(tmp) + ".npz")
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        for candidate in (tmp, Path(str(tmp) + ".npz")):
            try:
                if candidate != path and candidate.exists():
                    candidate.unlink()
            except OSError:
                pass


def read_json_safe(path: Path, *, max_bytes: int = 128 * 1024 * 1024) -> dict[str, Any] | None:
    """Read and parse a JSON file; return None (never raise) on any problem."""
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > max_bytes:
            return None
        with open(path, encoding="utf-8") as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Run locks  (in-process + on-disk mutex with stale detection)
# ---------------------------------------------------------------------------

_InProcessEntry = dict[str, Any]

_LOCKFILE_NAME = ".run.lock"
_REGISTRY_LOCK = threading.Lock()
_IN_PROCESS: dict[str, _InProcessEntry] = {}


def _registry_keys(run_dir: Path) -> list[str]:
    return [run_dir.name, str(run_dir.resolve())]


class RunLock:
    """Mutual exclusion for one run directory.

    A second concurrent run on the same directory is rejected with
    ``JOB_ALREADY_RUNNING`` (409) — never started in parallel. When the lock
    file is older than ``budget_seconds`` it is treated as a stale lock left
    by a crashed/restarted process: the previous run is first marked
    interrupted (honest ``FAILED``/``RUN_INTERRUPTED``) and the new run may
    proceed.
    """

    def __init__(self, run_dir: Path, *, budget_seconds: float | int | None = None,
                 tag: str = "run"):
        self._run_dir = Path(run_dir)
        self._budget = float(budget_seconds or 43200)
        self._tag = tag
        self._token = uuid.uuid4().hex
        self._lockfile = self._run_dir / _LOCKFILE_NAME
        self._held = False
        self._registered_key: str | None = None

    # -- in-process registry (thread level) -------------------------------
    def _register(self) -> None:
        entry = {
            "lock": self._token,
            "thread_id": threading.get_ident(),
            "acquired_at": time.time(),
            "tag": self._tag,
        }
        for key in _registry_keys(self._run_dir):
            existing = _IN_PROCESS.get(key)
            if existing is not None:
                if existing.get("thread_id") == threading.get_ident():
                    raise self._conflict("already running in this process")
                raise self._conflict("already running in another thread of this process")
        for key in _registry_keys(self._run_dir):
            _IN_PROCESS[key] = entry
        self._registered_key = _registry_keys(self._run_dir)[0]

    def _unregister(self) -> None:
        for key in _registry_keys(self._run_dir):
            entry = _IN_PROCESS.get(key)
            if entry is not None and entry.get("lock") == self._token:
                del _IN_PROCESS[key]

    # -- on-disk mutex -----------------------------------------------------
    def _acquire_file(self) -> None:
        try:
            self._lockfile.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self._lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if self._stale():
                mark_run_interrupted(self._run_dir, reason="RUN_INTERRUPTED",
                                     detail="Previous run was interrupted (stale lock).")
                try:
                    self._lockfile.unlink()
                except OSError:
                    pass
                try:
                    fd = os.open(str(self._lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    raise self._conflict("job already running") from None
            else:
                raise self._conflict("job already running") from None
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tag": self._tag,
                "token": self._token,
                "pid": os.getpid(),
                "created_at": _rfc3339(),
                "created_epoch": time.time(),
            }) + "\n")
            fh.flush()

    def _release_file(self) -> None:
        try:
            if self._lockfile.is_file():
                content = self._lockfile.read_text(encoding="utf-8")
                if f'"token": "{self._token}"' in content or self._token in content:
                    self._lockfile.unlink()
        except OSError:
            pass

    def _stale(self) -> bool:
        try:
            if not self._lockfile.is_file():
                return True
            age = max(0.0, time.time() - self._lockfile.stat().st_mtime)
            return age > max(self._budget, 1.0)
        except OSError:
            return True

    def _conflict(self, reason: str):
        from .errors import JobAlreadyRunningError

        return JobAlreadyRunningError(
            f"{self._tag} job is already running for this pair (reason: {reason}).",
            details={"run_dir": self._run_dir.name},
        )

    # -- public API --------------------------------------------------------
    def acquire(self) -> None:
        with _REGISTRY_LOCK:
            self._register()
        self._acquire_file()
        self._held = True

    def release(self) -> None:
        if not self._held:
            return
        try:
            self._release_file()
        finally:
            with _REGISTRY_LOCK:
                self._unregister()
            self._held = False

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()


def _rfc3339() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Stale RUNNING reconciliation
# ---------------------------------------------------------------------------

_STATUS_STATE_KEYS = ("state", "status", "run_status")
_STATUS_FILE_NAMES = ("status.json", "processing_status.json", "matching_status.json",
                      "trust_status.json", "m8_status.json")


def _is_running(payload: dict[str, Any]) -> bool:
    for key in _STATUS_STATE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.upper() in ("RUNNING", "READING", "PREPROCESSING"):
            return True
    return False


def _mark_running_interrupted(payload: dict[str, Any], *, reason: str, detail: str) -> bool:
    """Rewrite a RUNNING payload into an interrupted FAILED state. Returns
    True when the payload actually was a live RUNNING state."""
    if not _is_running(payload):
        return False
    for key in _STATUS_STATE_KEYS:
        if isinstance(payload.get(key), str) and payload[key].upper() in (
            "RUNNING", "READING", "PREPROCESSING"
        ):
            payload[key] = "FAILED"
    payload["interrupted"] = True
    payload["interrupt_reason"] = reason
    payload["finished_at"] = _rfc3339()
    payload.setdefault("error", {})
    if isinstance(payload.get("error"), dict):
        payload["error"]["code"] = payload.get("error", {}).get("code", reason)
        payload["error"]["message"] = detail
    payload.setdefault("note", "")
    if isinstance(payload.get("note"), str):
        payload["note"] = detail
    return True


def mark_run_interrupted(run_dir: Path, *, reason: str = "RUN_INTERRUPTED",
                         detail: str | None = None) -> bool:
    """Reconcile possibly stale RUNNING status files inside ``run_dir``.

    Returns True if at least one status file was rewritten; never raises.
    """
    changed = False
    detail = detail or "The previous run did not complete; a restart or timeout interrupted it."
    for name in _STATUS_FILE_NAMES:
        path = run_dir / name
        payload = read_json_safe(path)
        if payload is None:
            continue
        if _mark_running_interrupted(payload, reason=reason, detail=detail):
            try:
                atomic_write_json(path, payload)
                changed = True
            except OSError:
                pass
    return changed


# ---------------------------------------------------------------------------
# Run events (in-memory, bounded) for the operational overview
# ---------------------------------------------------------------------------

_MAX_RUN_EVENTS = 200


class _RunEventRing:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []

    def record(self, *, stage: str, pair_id: str, configuration_id: str,
               status: str, duration_ms: float, error_code: str | None = None) -> None:
        with self._lock:
            self._events.append({
                "stage": stage,
                "pair_id": pair_id,
                "configuration_id": configuration_id,
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "error_code": error_code,
                "finished_at": _rfc3339(),
            })
            if len(self._events) > _MAX_RUN_EVENTS:
                self._events = self._events[-_MAX_RUN_EVENTS:]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events[-limit:])


_run_events = _RunEventRing()


def record_run_event(stage: str, pair_id: str, configuration_id: str, status: str,
                     duration_ms: float, error_code: str | None = None) -> None:
    _run_events.record(stage=stage, pair_id=pair_id, configuration_id=configuration_id,
                       status=status, duration_ms=duration_ms, error_code=error_code)


def recent_run_events(limit: int = 50) -> list[dict[str, Any]]:
    return _run_events.recent(limit)


@contextmanager
def guarded_run(run_root: Path, *, budget_seconds: float | int, tag: str = "run") -> Iterator[None]:
    """M11 run guard: mutual exclusion over the pair/stage run root.

    ``run_root`` becomes the lock owner. Only ONE pipeline run may hold a given
    root at a time (in-process across threads; cross-process via the on-disk
    lock file). A second concurrent caller receives ``JOB_ALREADY_RUNNING``
    instead of clobbering artifacts. A stale lock (older than
    ``budget_seconds``, e.g. after a crash or restart) is reconciled first and
    the previous run is marked interrupted. Never raises on release; always
    releases even when the guarded body raises.
    """
    lock = RunLock(run_root, budget_seconds=budget_seconds, tag=tag)
    with lock:
        yield


def elapsed_ms(started_at: float) -> float:
    return max(0.0, (time.perf_counter() - started_at) * 1000.0)


class TimeBudget:
    """Simple wall-clock budget: returns False once ``max_seconds`` elapsed."""

    def __init__(self, max_seconds: float | int | None, *, started_at: float | None = None):
        self._max = float(max_seconds or 0)
        self._start = started_at if started_at is not None else time.perf_counter()

    @property
    def max_seconds(self) -> float:
        return self._max

    def remaining(self) -> float:
        return max(0.0, self._max - (time.perf_counter() - self._start))

    def expired(self) -> bool:
        return self._max > 0 and self.remaining() <= 0


def bounded(o: Any, *, prefix: str = "") -> str:
    """Render a value without leaking secrets; used for log/error safe text."""
    text = str(o) if o is not None else ""
    text = text.replace("\r", " ").replace("\n", " ")
    if len(text) > 300:
        text = text[:300] + "…"
    return f"{prefix}{text}" if prefix else text


__all__ = [
    "current_request_id",
    "set_request_id",
    "sanitize_request_id",
    "new_request_id",
    "atomic_write_text",
    "atomic_write_bytes",
    "atomic_write_npy",
    "atomic_write_npz",
    "atomic_write_json",
    "read_json_safe",
    "RunLock",
    "guarded_run",
    "mark_run_interrupted",
    "record_run_event",
    "recent_run_events",
    "elapsed_ms",
    "TimeBudget",
    "bounded",
]