"""M8 expansion service — benchmark, adaptive routing and trustworthy matcher
selection (SIH26166).

Flow (all recorded in ``m8_status.json``):
    CHECK_PREREQUISITES -> RESOLVE_CAPABILITIES -> ROUTING -> RUNNING_MATCHERS
    -> WRITING_CANDIDATES / BENCHMARK -> COMPLETE | INSUFFICIENT | BLOCKED | FAILED

Artifacts live ONLY under
``derived/matches/<pair>/<proc_cfg>/m8/<cfg>/`` and are never picked up by the
M3/M4 read paths. Deep matcher availability is a live capability probe; no
model output is ever fabricated; no accuracy/winner claim is ever made
(``REFERENCE_DATASET = NOT_AVAILABLE``).
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from ...config import Settings
from ...logging_conf import get_logger
from ..service import MatchingService, _load_mask
from ...processing.manifest import rel_string
from ...trust.service import TrustService
from .base import BaseMatcherAdapter, M8AdapterOutput, timed_match
from .benchmark import BenchmarkRow, benchmark_row_for, eligible_matchers
from .capabilities import configurations_public, device_public, reset_registry, resolve_registry
from .config import DeepMatcherConfig, load_deep_matcher_config
from .contract import ValidatedCandidates, validate_and_normalize, write_candidates_artifact
from .experiment import build_m8_experiment_json
from .manifest import M8ManifestBuilder, load_m8_manifest
from .provenance import build_m8_provenance
from .routing import M8StrategyOrder, route_tile
from .states import (
    BLOCK_CODE_LABELS,
    M8BenchmarkMode,
    M8BlockCode,
    M8RunState,
    STATE_LABELS,
    TileRunOutcome,
)

logger = get_logger(__name__)

M8_CONFIGURATION_ID = "DM-M8-001"


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


class M8Service:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_root_path
        self.base = self.root / "derived" / "matches"
        self.m3_service = MatchingService(settings)

    # ------------------------------------------------------------------
    # paths
    # ------------------------------------------------------------------
    def run_dir(self, pair_id: str, proc_cfg: str = "PC-M2-001",
                configuration_id: str = M8_CONFIGURATION_ID) -> Path:
        return self.base / pair_id / proc_cfg / "m8" / configuration_id

    def status_path(self, pair_id: str, proc_cfg: str = "PC-M2-001",
                    configuration_id: str = M8_CONFIGURATION_ID) -> Path:
        return self.run_dir(pair_id, proc_cfg, configuration_id) / "m8_status.json"

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        pair_dir = self.base / pair_id
        if not pair_dir.is_dir():
            return None
        for proc in sorted(d for d in pair_dir.glob("*") if d.is_dir()):
            for m8root in sorted(d for d in proc.glob("m8") if d.is_dir()):
                for cfg in sorted(d for d in m8root.glob("*") if d.is_dir()):
                    if (cfg / "m8_status.json").is_file():
                        return cfg
        return None

    def reset(self, pair_id: str) -> None:
        proc_root = self.base / pair_id
        if not proc_root.is_dir():
            return
        for proc in proc_root.glob("*"):
            if proc.is_dir():
                m8root = proc / "m8"
                if m8root.is_dir():
                    shutil.rmtree(m8root, ignore_errors=True)
        # also clear paired downstream copies that reference M8 runs
        trust_root = self.root / "derived" / "trust" / pair_id
        if trust_root.is_dir():
            for proc in trust_root.glob("*"):
                for matcher in proc.iterdir():
                    if matcher.name == "m8":
                        shutil.rmtree(matcher, ignore_errors=True)

    # ------------------------------------------------------------------
    # status / synthetic
    # ------------------------------------------------------------------
    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)

    def synthetic_status(self, pair_id: str, configuration_id: str = M8_CONFIGURATION_ID,
                         blocked: dict | None = None, note: str = "") -> dict:
        status = {
            "pair_id": pair_id,
            "configuration_id": configuration_id,
            "state": M8RunState.NOT_STARTED.value,
            "state_label": STATE_LABELS[M8RunState.NOT_STARTED.value],
            "progress": 0,
            "started_at": None,
            "finished_at": None,
            "blocked": blocked,
            "error": None,
            "summary": None,
            "capabilities": None,
            "device": None,
            "note": note or "Nothing was run yet.",
        }
        if blocked:
            status["state"] = M8RunState.BLOCKED.value
            status["state_label"] = STATE_LABELS[M8RunState.BLOCKED.value]
        return status

    def read_status(self, pair_id: str, configuration_id: str = M8_CONFIGURATION_ID) -> dict:
        run = self.find_run_for_pair(pair_id)
        path = None
        if run is not None:
            path = run / "m8_status.json"
        if path is None or not path.is_file():
            # Derive blocking from M3 prerequisites when nothing was run yet.
            pre = self.m3_service.prerequisites(pair_id) if pair_id else {"ok": False, "code": "PAIR_NOT_FOUND"}
            blocked = None
            note = "No M8 run exists for this pair."
            if not pre["ok"]:
                blocked = {"stage": "prerequisites", "code": pre["code"],
                           "reason": pre["reason"], "details": pre.get("details")}
                note = f"Nothing was run — {pre['reason']}"
            return self.synthetic_status(pair_id, configuration_id=configuration_id, blocked=blocked, note=note)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.synthetic_status(pair_id, configuration_id=configuration_id,
                                         blocked={"stage": "read", "code": "MATCHING_FAILED",
                                                  "reason": "M8 status file is unreadable."})

    # ------------------------------------------------------------------
    # run
    # ------------------------------------------------------------------
    def run(self, pair_id: str, *, configuration_id: str | None = None,
            mode: str = "AUTO", benchmark: bool = False) -> dict:
        reset_registry()
        configuration_id = (configuration_id or M8_CONFIGURATION_ID).strip()
        try:
            cfg = load_deep_matcher_config(configuration_id)
        except ValueError as exc:
            return self.synthetic_status(pair_id, configuration_id=configuration_id,
                                         blocked={"stage": "configuration", "code": "MATCHING_FAILED",
                                                  "reason": str(exc)})

        pre = self.m3_service.build_match_tiles(pair_id)
        if not pre["ok"]:
            return self.synthetic_status(pair_id, configuration_id=configuration_id,
                                         blocked={"stage": "prerequisites", "code": pre["code"],
                                                  "reason": pre["reason"], "details": pre.get("details")},
                                         note=f"Nothing was run — {pre['reason']}")
        details = pre["details"]
        match_tiles = pre["match_tiles"]
        proc_cfg = str(details["processing_configuration_id"])
        run = self.run_dir(pair_id, proc_cfg, configuration_id)
        run.mkdir(parents=True, exist_ok=True)
        (run / "routing").mkdir(parents=True, exist_ok=True)
        (run / "candidates").mkdir(parents=True, exist_ok=True)
        (run / "events").mkdir(parents=True, exist_ok=True)

        status = {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "m3_configuration_id": details["processing_configuration_id"],
            "mode": mode,
            "benchmark_enabled": bool(benchmark),
            "state": M8RunState.RUNNING.value,
            "state_label": STATE_LABELS[M8RunState.RUNNING.value],
            "progress": 5,
            "started_at": _now(),
            "finished_at": None,
            "blocked": None,
            "error": None,
            "summary": None,
            "note": "",
        }

        registry = resolve_registry()
        capabilities = [reg.capability() for mid in _cfg_ordered(cfg) if (reg := registry.get(mid))]
        status["capabilities"] = capabilities
        status["device"] = device_public()
        self._write_json(self.status_path(pair_id, proc_cfg, configuration_id), status)

        # ---------- ROUTING ----------
        m3_decision_map = self._load_m3_decisions(pair_id)
        routing_rows: list[dict[str, Any]] = []
        orders: list[M8StrategyOrder] = []
        available_classical = [mid for mid, reg in registry.items()
                               if reg.family == "classical" and reg.is_available()]
        available_deep = [mid for mid, reg in registry.items()
                          if reg.family == "deep" and reg.is_available()]
        for mt in match_tiles:
            m3_dec = m3_decision_map.get(mt["match_tile_id"])
            order = route_tile(
                tile_id=mt["match_tile_id"],
                m3_decision=m3_dec,
                condition_view=mt["condition_view"],
                available_classical=available_classical,
                available_deep=available_deep,
                preferred_matcher=cfg.preferred_matcher,
                mode=mode,
                allow_classical=cfg.allow_classical,
                allow_deep=cfg.allow_deep,
                fallback_to_classical=cfg.fallback_to_classical,
                feature_scarcity_threshold=max(0.05, float(mt["condition_view"].get("valid_fraction_a", 1.0)) - 0.3),
            )
            orders.append(order)
            routing_rows.append(order.to_dict())
        self._write_json(run / "routing" / "routing.json", {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "mode": mode,
            "benchmark": bool(benchmark),
            "rows": routing_rows,
            "note": "Routing decisions are what-to-try orders, never confidence or quality verdicts.",
        })
        status["progress"] = 20
        self._write_json(self.status_path(pair_id, proc_cfg, configuration_id), status)

        # ---------- RUNNING MATCHERS ----------
        manifest = self._manifest_builder(details, cfg, run)
        manifest.begin_step("running_matchers", "Running eligible matchers over each matched tile")
        tile_records: list[dict[str, Any]] = []
        benchmark_rows: list[BenchmarkRow] = []
        outcome_counts: dict[str, int] = {}
        total_candidates = 0
        matchers_used: dict[str, int] = {}
        prepared: set[str] = set()
        try:
            for idx, mt in enumerate(match_tiles):
                tile_record, rows = self._run_tile(mt, run, cfg, registry, orders[idx], mode,
                                                    benchmark, details, prepared, pair_id)
                tile_records.append(tile_record)
                benchmark_rows.extend(rows)
                outcome_counts[tile_record["outcome"]] = outcome_counts.get(tile_record["outcome"], 0) + 1
                total_candidates += tile_record["candidates"]
                if tile_record.get("matchers_used"):
                    for mid in tile_record["matchers_used"]:
                        matchers_used[mid] = matchers_used.get(mid, 0) + 1
                status["progress"] = 20 + int(70 * (idx + 1) / len(match_tiles))
                status["tiles_partial"] = {
                    "processed": idx + 1, "total": len(match_tiles),
                    "total_candidates": total_candidates, "outcomes": outcome_counts,
                }
                self._write_json(self.status_path(pair_id, proc_cfg, configuration_id), status)
        except Exception as exc:  # noqa: BLE001
            return self._fail(status, run, f"Running matchers failed: {exc}",
                              M8BlockCode.MATCHING_FAILED, cfg, proc_cfg, configuration_id)

        for adapter in registry.values():
            try:
                adapter.cleanup()
            except Exception:  # noqa: BLE001
                pass
        prepared = set()

        stages = {"running_matchers": {"count": len(tile_records), "total_candidates": total_candidates}}
        manifest.finish_step(outputs=[])

        # ---------- WRITING CANDIDATES / BENCHMARK ----------
        manifest.begin_step("writing_candidates", "Aggregating candidate/benchmark summaries")
        candidates_index = {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "processing_configuration_id": proc_cfg,
            "tiles": tile_records,
            "counts": outcome_counts,
            "total_candidates": total_candidates,
            "note": "Candidate correspondences are matcher observations, not verified truth — Trust Gate is M4.",
        }
        self._write_json(run / "candidates" / "candidates.json", candidates_index)

        downstream = self._downstream_matrix(pair_id)
        summary = {
            "pair_id": pair_id,
            "tiles": len(tile_records),
            "outcomes": outcome_counts,
            "matchers_used": matchers_used,
            "total_candidates": total_candidates,
            "per_tile": [
                {k: t[k] for k in ("match_tile_id", "outcome", "candidates", "matchers_used", "requested_strategy", "fallback_used")}
                for t in tile_records
            ],
            "downstream": downstream,
            "note": ("M8 candidate sets are raw matcher observations from one expansion run per tile; "
                     "independent geometric verification is NOT_RUN unless M4/M5/M6 have run."),
        }
        self._write_json(run / "summary.json", summary)

        if benchmark:
            benchmark_payload = {
                "pair_id": pair_id,
                "configuration_id": cfg.configuration_id,
                "mode": mode,
                "reference_dataset": "NOT_AVAILABLE",
                "rows": [r.to_dict() for r in benchmark_rows],
                "note": "Benchmark table is a measurement comparison — no winner, no accuracy claim.",
            }
            self._write_json(run / "benchmark.json", benchmark_payload)
            manifest.record(benchmark=benchmark_payload)

        manifest.record(
            routing={"rows": routing_rows, "file": rel_string(self.root, run / "routing" / "routing.json")},
            candidates={"tiles": len(tile_records), "total_candidates": total_candidates,
                        "outcomes": outcome_counts,
                        "files": [{"rel_path": rel_string(self.root, run / "candidates" / f"{t['match_tile_id']}.json")} for t in tile_records]},
            summary=summary,
        )
        manifest.finish_step(outputs=[run / "candidates" / "candidates.json", run / "summary.json"])
        manifest.write(run / "m8_manifest.json")

        # ---------- provenance + experiment ----------
        m3_run = self.m3_service.find_run_for_pair(pair_id)
        provenance = build_m8_provenance(pair_id, self.root, m3_run_dir=m3_run,
                                         m8_run_dir=run, m8_status=status, m8_summary=summary)
        if provenance:
            self._write_json(run / "provenance.json", provenance)
        experiment = build_m8_experiment_json(pair_id, self._config_chain(cfg), cfg.as_manifest_snapshot(),
                                              run, self.root)
        self._write_json(run / "experiment.json", experiment)

        final_state = M8RunState.COMPLETE.value if total_candidates > 0 else M8RunState.INSUFFICIENT.value
        status["state"] = final_state
        status["state_label"] = STATE_LABELS[final_state]
        status["progress"] = 100
        status["finished_at"] = _now()
        status["summary"] = summary
        status["tiles_partial"] = None
        status["note"] = (
            "M8 candidate correspondences are matcher observations localised by the selected matchers; "
            "they are NOT verified correspondences and carry no accuracy/trust verdict (Trust Gate = M4)."
        )
        self._write_json(self.status_path(pair_id, proc_cfg, configuration_id), status)
        logger.info("M8 %s complete -> %d candidates", pair_id, total_candidates,
                    extra={"operation": "m8_expansion", "status": "done"})
        return status

    # ------------------------------------------------------------------
    # per-tile matcher execution
    # ------------------------------------------------------------------
    def _run_tile(self, mt, run, cfg, registry, order: M8StrategyOrder, mode, benchmark,
                  details, prepared: set[str], pair_id: str):
        tile_id = mt["match_tile_id"]
        ta, tb = mt["tile_a_record"], mt["tile_b_record"]
        window_a = np.asarray(np.load(self.root / ta["array_rel"], mmap_mode="r"))
        window_b = np.asarray(np.load(self.root / tb["array_rel"], mmap_mode="r"))
        mask_a = _load_mask(details, ta, window_a.shape)
        mask_b = _load_mask(details, tb, window_b.shape)

        max_dim = int(cfg.max_image_dimension)
        window_a, mask_a, downscaled_a = _maybe_downscale(window_a, mask_a, max_dim)
        window_b, mask_b, downscaled_b = _maybe_downscale(window_b, mask_b, max_dim)

        tile_pair = {
            "match_tile_id": tile_id,
            "window_a": window_a, "window_b": window_b,
            "mask_a": mask_a, "mask_b": mask_b,
            "height_a": window_a.shape[0], "width_a": window_a.shape[1],
            "height_b": window_b.shape[0], "width_b": window_b.shape[1],
            "tile_a": ta, "tile_b": tb,
            "downscaled_a": downscaled_a, "downscaled_b": downscaled_b,
        }

        if window_a.size == 0 or window_b.size == 0:
            return self._tile_record(mt, order, outcome=TileRunOutcome.INPUT_INVALID.value, candidates=0,
                                     attempts=[], matchers_used=[], synthetic=False), []

        strategy_order = order.strategy_order if not benchmark else \
            eligible_matchers(registry, mode) if bench_mode_is(mode) else order.strategy_order

        attempts: list[dict[str, Any]] = []
        rows: list[BenchmarkRow] = []
        executed = ""
        matchers_used: list[str] = []
        budget = float(cfg.max_runtime_seconds)
        started = time.perf_counter()

        for mid in strategy_order:
            adapter = registry.get(mid)
            if adapter is None:
                continue
            if not adapter.is_available():
                code = "DEEP_MATCHER_UNAVAILABLE" if adapter.family == "deep" else "MATCHER_UNAVAILABLE"
                attempts.append({"matcher": mid, "status": "UNAVAILABLE",
                                 "code": code,
                                 "reason": adapter.reason_if_unavailable() or "adapter not available"})
                continue
            if time.perf_counter() - started > budget:
                attempts.append({"matcher": mid, "status": "TIMEOUT",
                                 "code": "TIMEOUT", "reason": "per-tile runtime budget exceeded"})
                rows.append(benchmark_row_for(adapter, None, None, tile_id))
                break
            if mid not in prepared:
                try:
                    adapter.prepare()
                    prepared.add(mid)
                except RuntimeError as exc:
                    code = "MODEL_WEIGHTS_NOT_CONFIGURED" if "MODEL_WEIGHTS" in str(exc) else "MATCHER_FAILED"
                    attempts.append({"matcher": mid, "status": "UNAVAILABLE", "code": code,
                                     "reason": str(exc)})
                    continue
            output = timed_match(adapter, tile_pair)
            output = adapter.normalize_result(tile_pair, output)
            if not output.ok:
                attempts.append({"matcher": mid, "status": "FAILED",
                                 "code": output.failure_code or "MATCHER_FAILED",
                                 "reason": output.failure_detail, "runtime_ms": output.runtime_ms})
                rows.append(benchmark_row_for(adapter, None, output, tile_id))
                continue
            candidates = validate_and_normalize(
                output, tile_id=tile_id,
                width_a=tile_pair["width_a"], height_a=tile_pair["height_a"],
                width_b=tile_pair["width_b"], height_b=tile_pair["height_b"],
                mask_a=mask_a, mask_b=mask_b,
                max_correspondences=int(cfg.max_correspondences),
                require_finite=cfg.require_finite,
                require_mask_valid=cfg.require_mask_valid,
            )
            obj = write_candidates_artifact(
                run / "candidates" / f"{tile_id}__{mid}.json", candidates)
            self._write_json(run / "events" / f"{tile_id}__{mid}.json", {
                "match_tile_id": tile_id, "matcher_id": mid,
                "runtime_ms": output.runtime_ms, "outcome": candidates.outcome,
                "funnel": candidates.funnel, "synthetically_derived": candidates.synthetically_derived,
                "note": "Candidate correspondences are matcher observations.",
            })
            synthetic = bool(candidates.synthetically_derived or getattr(adapter, "synthetically_derived", False))
            attempts.append({
                "matcher": mid, "status": "OK", "candidates": candidates.count,
                "outcome": candidates.outcome, "runtime_ms": output.runtime_ms,
                "funnel": candidates.funnel, "synthetic": synthetic,
            })
            rows.append(benchmark_row_for(adapter, candidates, output, tile_id,
                                          m4_state=self._m4_state(pair_id),
                                          m5_state=self._m5_state(pair_id),
                                          m6_state=self._m6_state(pair_id)))
            matchers_used.append(mid)
            if candidates.count > 0:
                executed = executed or mid
            # normal (non-benchmark) expansion: stop at first candidate-bearing matcher
            if not benchmark and candidates.count > 0:
                break

        if executed:
            outcome = TileRunOutcome.CANDIDATES.value
            count = sum(a.get("candidates", 0) for a in attempts if a.get("outcome") == TileRunOutcome.CANDIDATES.value) \
                if benchmark else (attempts[-1].get("candidates") or 0)
        elif any(a.get("status") == "TIMEOUT" for a in attempts):
            outcome, count = TileRunOutcome.TIMEOUT.value, 0
        elif attempts and all(a.get("status") == "UNAVAILABLE" for a in attempts):
            outcome, count = TileRunOutcome.MATCHER_UNAVAILABLE.value, 0
        elif attempts and all(a.get("outcome") == TileRunOutcome.NO_CANDIDATES.value for a in attempts):
            outcome, count = TileRunOutcome.NO_CANDIDATES.value, 0
        else:
            outcome, count = TileRunOutcome.MATCHER_FAILED.value, 0

        if count > 0 and not benchmark:
            pass  # per-matcher candidate artifacts already written above

        fallback_used = bool(executed and executed != order.requested_strategy)
        fallback_reason = "PRIMARY_UNAVAILABLE_OR_FAILED" if fallback_used else ""
        return self._tile_record(mt, order, outcome=outcome, candidates=count,
                                 attempts=attempts, matchers_used=matchers_used,
                                 synthetic=bool(count and any(a.get("synthetic") for a in attempts)),
                                 fallback_used=fallback_used, fallback_reason=fallback_reason), rows

    def _tile_record(self, mt, order, *, outcome, candidates, attempts, matchers_used,
                     synthetic: bool, fallback_used: bool = False, fallback_reason: str = "") -> dict:
        return {
            "match_tile_id": mt["match_tile_id"],
            "sequence": mt["sequence"],
            "tile_a": mt["tile_a"], "tile_b": mt["tile_b"],
            "sensor_a": mt["sensor_a"], "sensor_b": mt["sensor_b"],
            "iou": mt["iou"],
            "requested_strategy": order.requested_strategy,
            "strategy_order": list(order.strategy_order),
            "executed_strategies": matchers_used,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "outcome": outcome,
            "candidates": candidates,
            "matchers_used": matchers_used,
            "attempts": attempts,
            "synthetically_derived": synthetic,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _load_m3_decisions(self, pair_id: str) -> dict[str, dict]:
        m3_run = self.m3_service.find_run_for_pair(pair_id)
        if m3_run is None:
            return {}
        path = m3_run / "strategy" / "decisions.json"
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out: dict[str, dict] = {}
        for decision in payload.get("decisions", []):
            tid = decision.get("match_tile_id")
            if tid:
                out[tid] = decision
        return out

    def _manifest_builder(self, details, cfg: DeepMatcherConfig, run: Path) -> M8ManifestBuilder:
        processing_run = Path(str(details["processing_run_dir"]))
        return M8ManifestBuilder(
            data_root=self.root,
            application=self.settings.product_name,
            app_version=self.settings.app_version,
            milestone=self.settings.milestone,
            configuration=cfg.as_manifest_snapshot(),
            pair_id=details["pair_id"],
            matcher_model_identity={
                "superpoint_superglue": {
                    "runtime": "torch+torchvision", "weights_file": None,
                    "status": "RUNTIME_UNAVAILABLE or MODEL_WEIGHTS_NOT_CONFIGURED unless provisioned",
                },
                "loftr": {"runtime": "kornia", "status": "RUNTIME_UNAVAILABLE in this build"},
            },
            processing_inputs={
                "processing_configuration_id": details["processing_configuration_id"],
                "processing_run_rel": rel_string(self.root, processing_run),
                "artifacts": [
                    {"kind": "tiles_index", "rel_path": rel_string(self.root, processing_run / "crops" / "tiles.json")},
                    {"kind": "conditions", "rel_path": rel_string(self.root, processing_run / "diagnostics" / "conditions.json")},
                    {"kind": "overlap", "rel_path": rel_string(self.root, processing_run / "diagnostics" / "overlap.json")},
                ],
            },
        )

    def _config_chain(self, cfg: DeepMatcherConfig) -> dict:
        return {
            "m2": "PC-M2-001",
            "m3": "MC-M3-001",
            "m8": {
                "configuration_id": cfg.configuration_id,
                "configuration_version": cfg.configuration_version,
                "mode": "M8",
            },
        }

    def _label(self, code: str) -> str:
        return BLOCK_CODE_LABELS.get(code, code)

    def _fail(self, status, run: Path, message: str, code: str, cfg: DeepMatcherConfig,
              proc_cfg: str, configuration_id: str) -> dict:
        status["state"] = M8RunState.FAILED.value
        status["state_label"] = STATE_LABELS[M8RunState.FAILED.value]
        status["finished_at"] = _now()
        status["error"] = {"code": code, "message": message, "severity": "error", "retryable": True}
        status["note"] = "M8 run failed — nothing was falsified; state records the failure truthfully."
        self._write_json(self.status_path(status["pair_id"], proc_cfg, configuration_id), status)
        logger.error("M8 expansion failed: %s", message, extra={"operation": "m8_expansion", "status": "failed"})
        return status

    # ------------------------------------------------------------------
    # downstream state matrix (categorical)
    # ------------------------------------------------------------------
    def _downstream_matrix(self, pair_id: str) -> dict[str, str]:
        return {
            "m4_trust": self._m4_state(pair_id),
            "m5_spatial_reliability": self._m5_state(pair_id),
            "m6_registration": self._m6_state(pair_id),
            "note": "Downstream columns are categorical: COMPLETE / RUNNING / BLOCKED / NOT_RUN.",
        }

    def _m4_state(self, pair_id: str) -> str:
        try:
            run = TrustService(self.root, {}).find_run_for_pair(pair_id)
        except Exception:  # noqa: BLE001
            run = None
        if run is None:
            return "NOT_RUN"
        path = run / "trust_status.json"
        if not path.is_file():
            return "NOT_RUN"
        try:
            return str(json.loads(path.read_text(encoding="utf-8")).get("gate_state", "NOT_RUN"))
        except (OSError, ValueError):
            return "NOT_RUN"

    def _m5_state(self, pair_id: str) -> str:
        return self._scan_state(self.root / "derived" / "spatial" / pair_id)

    def _m6_state(self, pair_id: str) -> str:
        return self._scan_state(self.root / "derived" / "registration" / pair_id)

    def _scan_state(self, pair_dir: Path) -> str:
        if not pair_dir.is_dir():
            return "NOT_RUN"
        for proc in sorted(pair_dir.iterdir()):
            if not proc.is_dir():
                continue
            for matcher in sorted(proc.iterdir()):
                if not matcher.is_dir():
                    continue
                for sub in sorted(matcher.iterdir()):
                    if not sub.is_dir():
                        continue
                    state_path = sub / "status.json"
                    if not state_path.is_file():
                        state_path = sub / "summary.json"
                    if state_path.is_file():
                        try:
                            return str(json.loads(state_path.read_text(encoding="utf-8")).get("state", "NOT_RUN"))
                        except (OSError, ValueError):
                            return "NOT_RUN"
        return "NOT_RUN"

    # ------------------------------------------------------------------
    # read endpoints
    # ------------------------------------------------------------------
    def candidate_index(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "candidates" / "candidates.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def routing(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "routing" / "routing.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def benchmark(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "benchmark.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def tile(self, pair_id: str, match_tile_id: str) -> dict | None:
        index = self.candidate_index(pair_id)
        if not index:
            return None
        for t in index.get("tiles", []):
            if t.get("match_tile_id") == match_tile_id:
                return t
        return None

    def tile_candidates(self, pair_id: str, match_tile_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        cand_dir = (run / "candidates").resolve()
        out = {"match_tile_id": match_tile_id, "tiles": []}
        for json_path in sorted(cand_dir.glob(f"{match_tile_id}__*.json")):
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out["tiles"].append(payload)
        return out if out["tiles"] else None

    def manifest(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        return load_m8_manifest(run / "m8_manifest.json")

    def summary(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "summary.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def experiment(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "experiment.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def provenance(self, pair_id: str) -> dict | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "provenance.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None


def _cfg_ordered(cfg: DeepMatcherConfig) -> list[str]:
    return list(cfg.classical_strategies) + list(cfg.deep_strategies)


def bench_mode_is(mode: str) -> bool:
    return mode in (M8BenchmarkMode.AUTO.value, M8BenchmarkMode.CLASSICAL_ONLY.value,
                    M8BenchmarkMode.DEEP_ONLY.value)


def _maybe_downscale(window: np.ndarray, mask: np.ndarray | None, max_dim: int):
    """Downscale windows that exceed ``max_dim`` on any side (2:1 steps).

    Returns the (possibly resized) window, matching mask sample, and a flag.
    The mask is sampled with nearest-neighbour on the same grid.
    """
    h, w = window.shape
    scale = 1.0
    while max(h / scale, w / scale) > max_dim:
        scale *= 2.0
    if scale == 1.0 or h <= 0 or w <= 0:
        return window, mask, False
    import cv2

    new_h, new_w = max(1, int(round(h / scale))), max(1, int(round(w / scale)))
    if window.dtype != np.uint8:
        out = cv2.resize(window.astype(np.float32), (new_w, new_h), interpolation=cv2.INTER_AREA)
    else:
        out = cv2.resize(window, (new_w, new_h), interpolation=cv2.INTER_AREA)
    out_mask = None
    if mask is not None:
        out_mask = cv2.resize(np.asarray(mask, dtype=np.uint8), (new_w, new_h),
                              interpolation=cv2.INTER_NEAREST)
    return np.asarray(out), out_mask, True