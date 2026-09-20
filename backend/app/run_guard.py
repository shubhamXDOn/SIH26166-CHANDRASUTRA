"""M11 run-guard helper for pipeline API endpoints.

One pipeline run per pair per stage at a time: the run root is locked for the
whole run (in-process + on-disk mutex with stale reconciliation), duplicate
concurrent runs fail with ``JOB_ALREADY_RUNNING`` instead of clobbering
artifacts, and every run is recorded in the bounded in-process run-events ring
used by the operational overview.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .hardening import elapsed_ms, guarded_run, record_run_event


def guard_run(settings: Any, *, derived_stage: str, pair_id: str,
              configuration_id: str | None, tag: str,
              fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Execute ``fn()`` under the pair/stage run lock; record the run event.

    ``derived_stage`` is the directory name under ``data/derived`` that holds
    this stage's runs (processing | matches | trust | spatial | registration
    | metrics). ``settings`` needs ``data_root_path`` and
    ``run_stale_budget_seconds``.
    """
    run_root: Path = settings.data_root_path / "derived" / derived_stage / pair_id
    started = time.perf_counter()
    cfg_id = configuration_id or ""
    try:
        with guarded_run(run_root, budget_seconds=settings.run_stale_budget_seconds, tag=tag):
            result = fn()
    except Exception as exc:  # noqa: BLE001
        record_run_event(tag, pair_id, cfg_id, "FAILED", elapsed_ms(started),
                         error_code=getattr(exc, "code", None))
        raise
    state = result.get("state") if isinstance(result, dict) else "DONE"
    record_run_event(tag, pair_id, cfg_id, str(state), elapsed_ms(started))
    return result