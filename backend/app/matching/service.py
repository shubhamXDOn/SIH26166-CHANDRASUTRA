"""Matching service — orchestrates a full M3 MATCH run (SIH26166).

Flow (all recorded in matching_status.json):
    BUILDING_MATCH_TILES -> ROUTING_STRATEGY -> RUNNING_MATCHERS
    -> WRITING_CANDIDATES -> COMPLETE | BLOCKED | FAILED

Derived artifacts live ONLY under ``data/derived/matches/<pair>/<proc_cfg>/<matcher_cfg>/``.
A MATCH run consumes M2 artifacts (tiles + conditions + masks + geometry) and
never, ever claims that candidate correspondences are verified truth.

Blocking rules (stable codes, all reported truthfully):
    PAIR_NOT_FOUND, PAIR_NOT_VALID, PROCESSING_NOT_RUN, PROCESS_NOT_READY,
    MATCHER_READINESS_BLOCKED, ARTIFACT_MISSING, MATCHER_UNAVAILABLE,
    BUILD_MATCH_TILES_EMPTY, MATCHING_FAILED.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Settings
from ..errors import AppError, NotFoundError, ValidationError
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..processing.manifest import load_manifest, rel_string
from ..processing.service import ProcessingService
from .adapters import _as_u8, available_matchers, get_adapter
from .candidates import CandidateSet, filter_candidates, write_candidate_artifacts
from .config import MatcherConfig, load_matcher_config
from .engine import AdaptiveStrategyEngine, classify_scale_gap
from .manifest import MatchingManifestBuilder, load_matching_manifest
from .states import (
    MatchingState,
    OUTCOME_LABELS,
    STATE_LABELS,
    STAGE_ORDER,
    TileOutcome,
    initial_stages,
    make_stage_mapping,
    synthetic_status,
)

logger = get_logger(__name__)

MATCHER_CFG_ID = "MC-M3-001"


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def default_matcher_configuration_id() -> str:
    return load_matcher_config().configuration_id


class MatchingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_root_path
        self.base = self.root / "derived" / "matches"

    # ------------------------------------------------------------------
    # paths + state persistence
    # ------------------------------------------------------------------
    def run_dir(self, pair_id: str, proc_cfg: str = "PC-M2-001", matcher_cfg: str = MATCHER_CFG_ID) -> Path:
        return self.base / pair_id / proc_cfg / matcher_cfg

    def status_path(self, pair_id: str, proc_cfg: str = "PC-M2-001", matcher_cfg: str = MATCHER_CFG_ID) -> Path:
        return self.run_dir(pair_id, proc_cfg, matcher_cfg) / "matching_status.json"

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)

    # ------------------------------------------------------------------
    # prerequisites (honest blockers)
    # ------------------------------------------------------------------
    def prerequisites(self, pair_id: str) -> dict[str, Any]:
        registry = PairRegistry(self.settings)
        record = registry.get(pair_id)
        if record is None:
            return {"ok": False, "code": "PAIR_NOT_FOUND",
                    "reason": f"No pair with ID {pair_id} is registered.", "details": {}}

        ps = ProcessingService(self.settings)
        run = ps.find_run_for_pair(pair_id)
        if run is None:
            return {"ok": False, "code": "PROCESSING_NOT_RUN",
                    "reason": "No M2 PREPARE run exists for this pair — run PREPARE first.",
                    "details": {"processing_configuration_id": None, "pair_id": pair_id, "record": record}}
        proc_status = ps.read_status(pair_id, run.name)
        if proc_status.get("state") != "READY_FOR_MATCHING":
            return {"ok": False, "code": "PROCESS_NOT_READY",
                    "reason": f"M2 processing state is {proc_status.get('state', 'UNKNOWN')}, not READY_FOR_MATCHING.",
                    "details": {"processing_configuration_id": run.name, "processing_state": proc_status.get("state"),
                                "record": record, "pair_id": pair_id}}
        readiness = proc_status.get("matcher_readiness") or {}
        if not readiness.get("ready", False):
            unmet = [r.get("id") for r in (readiness.get("requirements") or []) if not r.get("met")]
            return {"ok": False, "code": "MATCHER_READINESS_BLOCKED",
                    "reason": "Matcher readiness is not satisfied.",
                    "details": {"unmet": unmet, "level": readiness.get("level"),
                                "processing_configuration_id": run.name, "record": record, "pair_id": pair_id}}

        tiles = ps.tiles(pair_id)
        conditions = ps.conditions(pair_id)
        overlap_path = run / "diagnostics" / "overlap.json"
        manifest = load_manifest(run / "processing_manifest.json")
        missing = [name for name, obj in [
            ("tiles.json", tiles), ("conditions.json", conditions),
            ("overlap.json", overlap_path if overlap_path.is_file() else None),
            ("processing_manifest.json", manifest),
        ] if obj is None]
        if missing:
            return {"ok": False, "code": "ARTIFACT_MISSING",
                    "reason": f"Required M2 artifacts are missing: {', '.join(missing)}.",
                    "details": {"missing": missing, "processing_configuration_id": run.name,
                                "record": record, "pair_id": pair_id}}

        geom = (manifest or {}).get("geometry")
        geometry_source = (geom or {}).get("source") or (proc_status.get("geometry_source") or "")
        products_geom = ((geom or {}).get("products") or {})
        gsds = {}
        for sensor in (record.sensor_a, record.sensor_b):
            pg = products_geom.get(sensor)
            gsds[sensor] = float(pg["gsd_m"]) if pg and isinstance(pg.get("gsd_m"), (int, float)) else None

        products = []
        for p in (manifest or {}).get("products") or []:
            products.append({
                "side": p.get("side"), "sensor": p.get("sensor"), "filename": p.get("filename"),
                "label_filename": p.get("label_filename"), "raw_sha256": p.get("raw_sha256"),
            })

        return {
            "ok": True,
            "code": "READY",
            "reason": "Pair is matcher-ready; MATCH can run.",
            "details": {
                "pair_id": pair_id,
                "record": record,
                "processing_configuration_id": run.name,
                "processing_run_dir": run,
                "tiles": tiles,
                "conditions": conditions,
                "overlap": json.loads(overlap_path.read_text(encoding="utf-8")) if overlap_path.is_file() else None,
                "manifest": manifest,
                "gsds": gsds,
                "geometry_source": geometry_source,
                "products": products,
            },
        }

    # ------------------------------------------------------------------
    def read_status(self, pair_id: str) -> dict[str, Any]:
        pre = self.prerequisites(pair_id)
        if not pre["ok"]:
            return synthetic_status(
                pair_id, MATCHER_CFG_ID,
                blocked={"stage": "match", "code": pre["code"], "reason": pre["reason"], "details": pre["details"]},
                note=f"Nothing was run — {pre['reason']}",
            )
        proc_cfg = str(pre["details"]["processing_configuration_id"])
        path = self.status_path(pair_id, proc_cfg)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return synthetic_status(
            pair_id, MATCHER_CFG_ID,
            note="Pair is matcher-ready. Run MATCH to produce candidate correspondences.",
        )

    def write_status(self, status: dict[str, Any]) -> None:
        pair_id = status.get("pair_id", "")
        proc_cfg = str(status.get("processing_configuration_id") or "PC-M2-001")
        matcher_cfg = str(status.get("configuration_id") or MATCHER_CFG_ID)
        self._write_json(self.status_path(pair_id, proc_cfg, matcher_cfg), status)

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        if not (self.base / pair_id).is_dir():
            return None
        for proc in sorted(d for d in (self.base / pair_id).glob("*") if d.is_dir()):
            for matcher in sorted(d for d in proc.glob("*") if d.is_dir()):
                if matcher.name == "m8":
                    # M8 deep-match expansion runs live under their own layout
                    # (derived/matches/<pair>/<proc_cfg>/m8/<cfg>/); they must
                    # NEVER be picked up as an M3 matcher run.
                    continue
                return matcher
        return None

    def build_match_tiles(self, pair_id: str) -> dict[str, Any]:
        """Public M2->match-tile builder shared with the M8 expansion service.

        Returns ``{ok, prereq, match_tiles, details}``; ``ok`` is False with a
        blocker code/reason when the pair cannot produce match tiles.
        """
        pre = self.prerequisites(pair_id)
        if not pre["ok"]:
            return {
                "ok": False,
                "code": pre["code"],
                "reason": pre["reason"],
                "details": pre["details"],
                "match_tiles": [],
                "prereq": pre,
            }
        cfg = load_matcher_config()
        try:
            match_tiles = self._build_match_tiles(pre["details"], cfg)
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "code": "BUILD_MATCH_TILES_EMPTY",
                "reason": f"Failed to build match tiles: {exc}",
                "details": pre["details"],
                "match_tiles": [],
                "prereq": pre,
            }
        if not match_tiles:
            return {
                "ok": False,
                "code": "BUILD_MATCH_TILES_EMPTY",
                "reason": "No usable sensor-aligned tile pairs could be assembled.",
                "details": pre["details"],
                "match_tiles": [],
                "prereq": pre,
            }
        return {
            "ok": True,
            "code": "READY",
            "reason": "Match tiles are ready for the M8 expansion run.",
            "details": pre["details"],
            "match_tiles": match_tiles,
            "prereq": pre,
        }

    def reset(self, pair_id: str) -> None:
        pair_dir = self.base / pair_id
        if pair_dir.is_dir():
            shutil.rmtree(pair_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # MATCH run
    # ------------------------------------------------------------------
    def run(self, pair_id: str, configuration_id: str | None = None) -> dict[str, Any]:
        pre = self.prerequisites(pair_id)
        if not pre["ok"]:
            return synthetic_status(
                pair_id, MATCHER_CFG_ID,
                blocked={"stage": "match", "code": pre["code"], "reason": pre["reason"], "details": pre["details"]},
                note=f"Nothing was run — {pre['reason']}",
            )
        try:
            cfg = load_matcher_config(configuration_id)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        details = pre["details"]
        record = details["record"]
        proc_cfg = str(details["processing_configuration_id"])
        run = self.run_dir(pair_id, proc_cfg, cfg.configuration_id)
        run.mkdir(parents=True, exist_ok=True)

        status = {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "processing_configuration_id": proc_cfg,
            "state": MatchingState.RUNNING.value,
            "state_label": STATE_LABELS[MatchingState.RUNNING.value],
            "progress": 5,
            "started_at": _now(),
            "finished_at": None,
            "stages": initial_stages(),
            "blocked": None,
            "error": None,
            "summary": None,
            "note": "",
        }
        stages = make_stage_mapping(status["stages"])

        manifest = MatchingManifestBuilder(
            data_root=self.root,
            application=self.settings.product_name,
            app_version=self.settings.app_version,
            milestone=self.settings.milestone,
            configuration=cfg.as_manifest_snapshot(),
            pair_id=pair_id,
            processing_inputs={
                "processing_configuration_id": proc_cfg,
                "processing_run_rel": rel_string(self.root, details["processing_run_dir"]),
                "geometry_source": details["geometry_source"],
                "products": details["products"],
                "artifacts": [
                    {"kind": "tiles_index", "rel_path": rel_string(self.root, details["processing_run_dir"] / "crops" / "tiles.json")},
                    {"kind": "conditions", "rel_path": rel_string(self.root, details["processing_run_dir"] / "diagnostics" / "conditions.json")},
                    {"kind": "overlap", "rel_path": rel_string(self.root, details["processing_run_dir"] / "diagnostics" / "overlap.json")},
                    {"kind": "processing_manifest", "rel_path": rel_string(self.root, details["processing_run_dir"] / "processing_manifest.json")},
                ],
            },
        )

        (run / "strategy").mkdir(parents=True, exist_ok=True)
        (run / "candidates").mkdir(parents=True, exist_ok=True)
        (run / "events").mkdir(parents=True, exist_ok=True)

        # ---------------- stage: BUILDING_MATCH_TILES ------------------
        stages["building_match_tiles"]["started_at"] = _now()
        stages["building_match_tiles"]["state"] = "running"
        manifest.begin_step("building_match_tiles", "Building sensor-aligned match tiles")
        self.write_status(status)
        try:
            match_tiles = self._build_match_tiles(details, cfg)
        except Exception as exc:  # noqa: BLE001
            return self._fail(status, stages, "building_match_tiles", f"Failed to build match tiles: {exc}", manifest, run, cfg)
        if not match_tiles:
            stages["building_match_tiles"]["finished_at"] = _now()
            stages["building_match_tiles"]["state"] = "blocked"
            status["state"] = MatchingState.BLOCKED.value
            status["state_label"] = STATE_LABELS[MatchingState.BLOCKED.value]
            status["blocked"] = {"stage": "building_match_tiles", "code": "BUILD_MATCH_TILES_EMPTY",
                                 "reason": "No usable sensor-aligned tile pairs could be assembled from the overlap region."}
            status["finished_at"] = _now()
            status["note"] = "Nothing was matched."
            stages["run"]["state"] = "blocked"
            stages["run"]["finished_at"] = status["finished_at"]
            manifest.record(summary={"tiles": 0, "outcomes": {}, "strategies_used": {}, "total_candidates": 0})
            self.write_status(status)
            return status
        stages["building_match_tiles"]["finished_at"] = _now()
        stages["building_match_tiles"]["state"] = "complete"
        stages["building_match_tiles"]["detail"] = f"{len(match_tiles)} match tile(s) assembled."
        manifest.finish_step(outputs=[])
        status["progress"] = 20
        self.write_status(status)

        # ---------------- stage: ROUTING_STRATEGY ----------------------
        stages["routing_strategy"]["started_at"] = _now()
        stages["routing_strategy"]["state"] = "running"
        manifest.begin_step("routing_strategy", "Adaptive strategy selection per match tile")
        engine = AdaptiveStrategyEngine(cfg)
        decisions = []
        for mt in match_tiles:
            decision = engine.decide(
                pair_id=pair_id,
                match_tile_id=mt["match_tile_id"],
                tile_a=mt["tile_a"],
                tile_b=mt["tile_b"],
                sensor_a=record.sensor_a,
                sensor_b=record.sensor_b,
                condition_view=mt["condition_view"],
                scale_gap=mt["scale_gap"],
            )
            mt["proposed_strategy"] = decision["selected_strategy"]
            mt["decision_id"] = decision["decision_id"]
            mt["fallback_order"] = [s for s in decision["rank_by_score"] if s != decision["selected_strategy"]]
            decisions.append(decision)
        self._write_json(run / "strategy" / "decisions.json", {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "decisions": decisions,
            "note": "Each decision is a routing decision (what to try), never a scientific confidence or quality verdict.",
        })
        stages["routing_strategy"]["finished_at"] = _now()
        stages["routing_strategy"]["state"] = "complete"
        stages["routing_strategy"]["detail"] = f"{len(decisions)} explainable strategy decision(s) recorded."
        manifest.finish_step(outputs=[run / "strategy" / "decisions.json"])
        status["progress"] = 35
        self.write_status(status)

        # ---------------- stage: RUNNING_MATCHERS -----------------------
        stages["running_matchers"]["started_at"] = _now()
        stages["running_matchers"]["state"] = "running"
        manifest.begin_step("running_matchers", "Matching tile pairs and recording candidate correspondences")
        tile_records: list[dict[str, Any]] = []
        proposed_counts: dict[str, int] = {}
        used_counts: dict[str, int] = {}
        outcome_counts: dict[str, int] = {}
        total_candidates = 0
        finished = 0
        try:
            for mt in match_tiles:
                tile_record = self._run_one_tile(run, mt, cfg, details)
                tile_records.append(tile_record)
                proposed_counts[tile_record["proposed_strategy"]] = proposed_counts.get(tile_record["proposed_strategy"], 0) + 1
                used_counts[tile_record["strategy_used"]] = used_counts.get(tile_record["strategy_used"], 0) + 1
                outcome_counts[tile_record["outcome"]] = outcome_counts.get(tile_record["outcome"], 0) + 1
                total_candidates += tile_record["candidates"]
                finished += 1
                status["progress"] = 35 + int(60 * finished / len(match_tiles))
                stages["running_matchers"]["detail"] = f"{finished}/{len(match_tiles)} tiles processed."
                status["tiles_partial"] = {
                    "processed": finished, "total": len(match_tiles),
                    "total_candidates": total_candidates, "outcomes": outcome_counts,
                }
                self.write_status(status)
        except Exception as exc:  # noqa: BLE001
            return self._fail(status, stages, "running_matchers", f"Matching failed unexpectedly: {exc}", manifest, run, cfg,
                              partial={**outcome_counts, "_candidates": total_candidates})

        stages["running_matchers"]["finished_at"] = _now()
        stages["running_matchers"]["state"] = "complete"
        stages["running_matchers"]["detail"] = (
            f"{len(tile_records)} tile(s) processed; {total_candidates} candidate(s) recorded."
        )
        manifest.finish_step(outputs=[])
        status["progress"] = 95
        self.write_status(status)

        # ---------------- stage: WRITING_CANDIDATES ---------------------
        stages["writing_candidates"]["started_at"] = _now()
        stages["writing_candidates"]["state"] = "running"
        manifest.begin_step("writing_candidates", "Aggregating candidate summaries and writing manifest")
        cand_index = {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "processing_configuration_id": proc_cfg,
            "tiles": tile_records,
            "counts": outcome_counts,
            "total_candidates": total_candidates,
            "note": "Candidate correspondences are observations, not verified truth — Trust Gate is M4.",
        }
        self._write_json(run / "candidates" / "candidates.json", cand_index)

        summary = {
            "pair_id": pair_id,
            "tiles": len(tile_records),
            "outcomes": outcome_counts,
            "strategies_proposed": proposed_counts,
            "strategies_used": used_counts,
            "total_candidates": total_candidates,
            "per_tile": [
                {k: t[k] for k in ("match_tile_id", "outcome", "candidates", "strategy_used", "proposed_strategy")}
                for t in tile_records
            ],
            "note": ("Candidate sets are raw observations from one matcher run per tile; "
                     "independent geometric verification is NOT_RUN (M4 Trust Gate)."),
        }
        self._write_json(run / "summary.json", summary)

        outputs = [cand_index_path := run / "candidates" / "candidates.json", run / "summary.json"]
        for tr in tile_records:
            if tr.get("candidate_artifact"):
                outputs.append(tr["candidate_artifact"])
        manifest.record(
            strategy={
                "decisions_total": len(decisions),
                "strategies_proposed": proposed_counts,
                "strategies_used": used_counts,
                "per_tile": {t["match_tile_id"]: t["strategy_used"] for t in tile_records},
                "decision_file": rel_string(self.root, run / "strategy" / "decisions.json"),
            },
            candidates={
                "tiles": len(tile_records),
                "total_candidates": total_candidates,
                "outcomes": outcome_counts,
                "files": [
                    {"rel_path": rel_string(self.root, run / "candidates" / f"{t['match_tile_id']}.json")}
                    for t in tile_records
                ],
            },
            summary=summary,
        )
        manifest.finish_step(outputs=[cand_index_path, run / "summary.json"])
        manifest.write(run / "matching_manifest.json")

        stages["writing_candidates"]["finished_at"] = _now()
        stages["writing_candidates"]["state"] = "complete"
        stages["writing_candidates"]["detail"] = f"{total_candidates} candidate(s) across {len(tile_records)} tile(s)."

        status["state"] = MatchingState.COMPLETE.value
        status["state_label"] = STATE_LABELS[MatchingState.COMPLETE.value]
        status["finished_at"] = _now()
        status["progress"] = 100
        status["summary"] = summary
        status["tiles_partial"] = None
        stages["run"]["state"] = "complete"
        stages["run"]["finished_at"] = status["finished_at"]
        stages["run"]["detail"] = "MATCH run completed."
        status["note"] = (
            "Candidate correspondences are observations localised by the selected matchers. "
            "They are NOT verified correspondences and carry no accuracy/trust verdict (Trust Gate = M4)."
        )
        self.write_status(status)
        logger.info("Matching %s complete -> %d candidates", pair_id, total_candidates,
                    extra={"operation": "m3_match", "status": "done"})
        return status

    # ------------------------------------------------------------------
    def _build_match_tiles(self, details: dict[str, Any], cfg: MatcherConfig) -> list[dict[str, Any]]:
        tiles = details["tiles"]["tiles"]
        conditions = details["conditions"]
        cond_map: dict[tuple[str, str], dict] = {}
        for tr in (conditions or {}).get("tiles", []):
            cond_map[(str(tr.get("sensor")), str(tr.get("tile_id")))] = tr

        tiles = [_norm_tile(t) for t in tiles]
        a_tiles = [t for t in tiles if t.get("side") == "a" and not t["too_small"]]
        b_tiles = [t for t in tiles if t.get("side") == "b" and not t["too_small"]]
        gsds = details["gsds"]
        record = details["record"]

        pair_tiles: list[dict[str, Any]] = []
        seq = 0
        for ta in a_tiles:
            best = None
            best_iou = -1.0
            for tb in b_tiles:
                iou = _box_iou(ta.get("ground_box") or {}, tb.get("ground_box") or {})
                if iou > best_iou:
                    best_iou, best = iou, tb
            if best is None or best_iou <= 0.0:
                continue
            seq += 1
            mix = f"{record.pair_id}-M{seq:03d}"
            cond_a = cond_map.get((str(ta.get("sensor")), str(ta.get("tile_id"))), {})
            cond_b = cond_map.get((str(best.get("sensor")), str(best.get("tile_id"))), {})
            scale_gap = classify_scale_gap(gsds.get(record.sensor_a), gsds.get(record.sensor_b))
            pair_tiles.append({
                "match_tile_id": mix,
                "sequence": seq,
                "tile_a": ta["tile_id"],
                "tile_b": best["tile_id"],
                "sensor_a": record.sensor_a,
                "sensor_b": record.sensor_b,
                "iou": round(float(best_iou), 6),
                "tile_a_record": ta,
                "tile_b_record": best,
                "condition_a": cond_a,
                "condition_b": cond_b,
                "condition_view": _condition_view(ta, best, cond_a, cond_b),
                "scale_gap": scale_gap,
                "gsd_a": gsds.get(record.sensor_a),
                "gsd_b": gsds.get(record.sensor_b),
            })
        return pair_tiles

    # ------------------------------------------------------------------
    def _run_one_tile(self, run: Path, mt: dict[str, Any], cfg: MatcherConfig,
                      details: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        budget = cfg.max_runtime_seconds
        tile_id = mt["match_tile_id"]
        ta = mt["tile_a_record"]
        tb = mt["tile_b_record"]

        window_a = np.load(self.root / ta["array_rel"], mmap_mode="r")
        window_b = np.load(self.root / tb["array_rel"], mmap_mode="r")
        mask_a = _load_mask(details, ta, window_a.shape)
        mask_b = _load_mask(details, tb, window_b.shape)

        if window_a.size == 0 or window_b.size == 0:
            return self._tile_record(mt, run, outcome=TileOutcome.INPUT_INVALID.value, candidates=0,
                                     strategy_used=mt["proposed_strategy"], attempts=[],
                                     candidate_summary={"outcome": TileOutcome.INPUT_INVALID.value, "count": 0})

        avail = {m.strategy_id: m.is_available() for m in available_matchers()}
        fallback = list(mt.get("fallback_order") or [])
        order = [mt["proposed_strategy"]]
        for alt in fallback:
            if alt not in order:
                order.append(alt)
        if not any(avail.get(s, False) for s in order):
            return self._tile_record(mt, run, outcome=TileOutcome.MATCHER_UNAVAILABLE.value, candidates=0,
                                     strategy_used=mt["proposed_strategy"], attempts=[],
                                     candidate_summary={"outcome": TileOutcome.MATCHER_UNAVAILABLE.value, "count": 0})

        attempts: list[dict[str, Any]] = []
        best_candidate: CandidateSet | None = None
        last_matcher_ok = True
        last_failure = ""
        steps: list[str] = []

        max_attempts = cfg.fallback_max_attempts if cfg.fallback_enabled else 1
        for strategy in order:
            if not avail.get(strategy, False):
                attempts.append({"strategy": strategy, "attempt": len(attempts) + 1,
                                 "status": "UNAVAILABLE", "note": "adapter not available in this build"})
                continue
            if time.perf_counter() - started > budget:
                attempts.append({"strategy": strategy, "attempt": len(attempts) + 1,
                                 "status": "TIMEOUT", "note": "per-tile runtime budget exceeded"})
                break
            adapter = get_adapter(strategy)
            detector_params = cfg.detector_params(strategy)
            matching_params = cfg.matching_params(strategy)
            output = adapter.match(
                np.asarray(window_a), np.asarray(window_b),
                mask_a, mask_b,
                detector_params=detector_params,
                matching_params=matching_params,
            )
            candidate = None
            elapsed_ms = round(output.runtime_ms, 3)
            if output.matcher_ok:
                candidate = filter_candidates(output, mask_a, mask_b, tile_a=ta, tile_b=tb, cfg=cfg)
                attempts.append({
                    "strategy": strategy, "attempt": len(attempts) + 1, "status": "OK",
                    "candidates": candidate.count, "outcome": candidate.outcome,
                    "matching_ms": elapsed_ms,
                    "matching": {k: v for k, v in output.to_dict()["matching"].items()},
                })
                if candidate.count > 0:
                    best_candidate = candidate
                    steps.append("GENERATING_CANDIDATES")
                last_matcher_ok = True
            else:
                attempts.append({
                    "strategy": strategy, "attempt": len(attempts) + 1, "status": "FAILED",
                    "note": output.failure_detail, "matching_ms": elapsed_ms,
                })
                last_matcher_ok = False
                last_failure = output.failure_detail
                steps.append("EXTRACTING_FEATURES")
            if best_candidate is not None or len(attempts) >= max_attempts:
                break

        if best_candidate is not None:
            outcome = best_candidate.outcome
            count = best_candidate.count
        elif any(a["status"] == "TIMEOUT" for a in attempts):
            outcome = TileOutcome.TIMEOUT.value
            count = 0
        elif attempts and all(a["status"] == "UNAVAILABLE" for a in attempts):
            outcome = TileOutcome.MATCHER_UNAVAILABLE.value
            count = 0
        elif last_matcher_ok and attempts:
            outcome = TileOutcome.NO_CANDIDATES.value
            count = 0
        else:
            outcome = TileOutcome.NO_FEATURES.value if "features" in last_failure.lower() else TileOutcome.MATCHER_FAILED.value
            count = 0

        artifact = None
        if count > 0:
            decision = {"selected_strategy": mt["proposed_strategy"], **({"decision_id": mt.get("decision_id")} if mt.get("decision_id") else {})}
            paths = write_candidate_artifacts(
                run / "candidates", match_tile_id=tile_id,
                candidates=best_candidate, decision=decision,
            )
            artifact = paths["npz"]
            candidate_summary = best_candidate.summary()
            candidate_summary["attempts"] = attempts
        else:
            candidate_summary = ({
                "strategy": mt["proposed_strategy"], "family": "", "license": "",
                "count": 0, "outcome": outcome,
                "threshold_counts": {}, "attempts": attempts,
            })

        if count == 0:
            self._write_json(run / "candidates" / f"{tile_id}.json", {
                "match_tile_id": tile_id,
                "summary": candidate_summary,
                "decision": {"decision_id": mt.get("decision_id"), "selected_strategy": mt["proposed_strategy"]},
                "note": "No candidate correspondences survived the explicit filters for this tile.",
            })

        self._write_json(run / "events" / f"{tile_id}.json", {
            "match_tile_id": tile_id,
            "started_at_ms": 0,
            "finished_at_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "budget_seconds": budget,
            "proposed_strategy": mt["proposed_strategy"],
            "strategy_used": best_candidate.strategy if best_candidate is not None else attempts[0]["strategy"] if attempts else mt["proposed_strategy"],
            "outcome": outcome,
            "attempts": attempts,
            "steps": steps,
            "note": "Candidate correspondences are observations; they carry no accuracy or trust verdict.",
        })

        strategy_used = best_candidate.strategy if best_candidate is not None else (attempts[0]["strategy"] if attempts else mt["proposed_strategy"])
        return self._tile_record(mt, run, outcome=outcome, candidates=count,
                                 strategy_used=strategy_used, attempts=attempts,
                                 candidate_summary=candidate_summary,
                                 candidate_artifact=artifact, events_file=run / "events" / f"{tile_id}.json")

    # ------------------------------------------------------------------
    def _tile_record(self, mt, run, *, outcome: str, candidates: int, strategy_used: str,
                     attempts: list, candidate_summary: dict, candidate_artifact: Path | None = None,
                     events_file: Path | None = None) -> dict[str, Any]:
        return {
            "match_tile_id": mt["match_tile_id"],
            "sequence": mt["sequence"],
            "tile_a": mt["tile_a"],
            "tile_b": mt["tile_b"],
            "sensor_a": mt["sensor_a"],
            "sensor_b": mt["sensor_b"],
            "iou": mt["iou"],
            "proposed_strategy": mt["proposed_strategy"],
            "strategy_used": strategy_used,
            "outcome": outcome,
            "outcome_label": OUTCOME_LABELS.get(outcome, outcome),
            "candidates": candidates,
            "attempts": attempts,
            "diagnostics": candidate_summary.get("diagnostics"),
            "candidate_artifact": rel_string(self.root, candidate_artifact) if candidate_artifact else None,
            "events_file": rel_string(self.root, events_file) if events_file else None,
        }

    # ------------------------------------------------------------------
    # read endpoints
    # ------------------------------------------------------------------
    def candidate_index(self, pair_id: str) -> dict[str, Any] | None:
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

    def decisions(self, pair_id: str) -> dict[str, Any] | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "strategy" / "decisions.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def match_tiles(self, pair_id: str) -> list[dict[str, Any]] | None:
        index = self.candidate_index(pair_id)
        return index.get("tiles") if index else None

    def tile(self, pair_id: str, match_tile_id: str) -> dict[str, Any] | None:
        index = self.candidate_index(pair_id)
        if not index:
            return None
        for t in index.get("tiles", []):
            if t.get("match_tile_id") == match_tile_id:
                return t
        return None

    def tile_candidates(self, pair_id: str, match_tile_id: str) -> dict[str, Any] | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        if not run.is_relative_to(self.base / pair_id):
            return None
        cand_dir = (run / "candidates").resolve()
        json_path = (cand_dir / f"{match_tile_id}.json").resolve()
        npz_path = (cand_dir / f"{match_tile_id}.npz").resolve()
        if not json_path.is_relative_to(cand_dir) or not npz_path.is_relative_to(cand_dir):
            return None
        if not json_path.is_file():
            return None
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        points = None
        if npz_path.is_file():
            with np.load(npz_path) as data:
                points = {k: np.round(np.asarray(data[k]), 4).tolist() for k in ("x_a", "y_a", "x_b", "y_b")}
                if "descriptor_distance" in data:
                    payload["descriptor_distance"] = np.round(np.asarray(data["descriptor_distance"]), 4).tolist()
                if "matcher_score" in data:
                    payload["matcher_score"] = np.round(np.asarray(data["matcher_score"]), 4).tolist()
        payload["points"] = points
        return payload

    def manifest(self, pair_id: str) -> dict[str, Any] | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        return load_matching_manifest(run / "matching_manifest.json")

    def summary(self, pair_id: str) -> dict[str, Any] | None:
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

    # ------------------------------------------------------------------
    def _fail(self, status, stages, stage_id: str, message: str, manifest, run: Path, cfg, partial=None) -> dict:
        stage = stages.get(stage_id)
        if stage is not None:
            stage["state"] = "failed"
            stage["detail"] = (stage.get("detail") or "") + message
        status["state"] = MatchingState.FAILED.value
        status["state_label"] = STATE_LABELS[MatchingState.FAILED.value]
        status["error"] = {
            "code": "MATCHING_FAILED",
            "message": message,
            "severity": "error",
            "retryable": True,
            "details": {"stage": stage_id, "partial": partial},
        }
        status["finished_at"] = _now()
        stages["run"]["state"] = "failed"
        self.write_status(status)
        logger.error("Matching failed at %s: %s", stage_id, message,
                     extra={"operation": "m3_match", "status": "failed"})
        exc = AppError(message, details={"stage": stage_id})
        exc.code = "MATCHING_FAILED"
        raise exc


def _load_mask(details: dict[str, Any], tile: dict[str, Any], shape) -> np.ndarray | None:
    """Load the invalid mask sliced to exactly the tile window used for crops.

    The mask lives next to the sensor's preprocessed display product in the M2
    run; ``tile`` carries the absolute window (row_start/col_start/height/width)
    that the crop array and the keypoint coordinates are expressed in.
    """
    proc_run = Path(str(details["processing_run_dir"]))
    path = proc_run / str(tile.get("sensor")) / "invalid_mask_u8.npy"
    if not path.is_file():
        return None
    full = np.asarray(np.load(path, mmap_mode="r"))
    row0 = int(tile.get("row_start", 0))
    col0 = int(tile.get("col_start", 0))
    return full[row0:row0 + int(tile.get("height", 0)), col0:col0 + int(tile.get("width", 0))]


def _norm_tile(tile: dict[str, Any]) -> dict[str, Any]:
    """Normalise M2 tile JSON fields that may carry numpy types serialised as strings."""
    t = dict(tile)

    def _b(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes")
        return bool(value)

    t["side"] = str(t.get("side", ""))
    t["sensor"] = str(t.get("sensor", ""))
    t["row_start"] = int(t.get("row_start", 0))
    t["col_start"] = int(t.get("col_start", 0))
    t["width"] = int(t.get("width", 0))
    t["height"] = int(t.get("height", 0))
    t["too_small"] = _b(t.get("too_small", False))
    t["clipped"] = _b(t.get("clipped", False))
    try:
        t["valid_fraction"] = float(t.get("valid_fraction", 0.0))
    except (TypeError, ValueError):
        t["valid_fraction"] = 0.0
    return t


def _box_iou(box_a: dict, box_b: dict) -> float:
    if not box_a or not box_b:
        return 0.0
    try:
        r0 = max(box_a["row_min_m"], box_b["row_min_m"])
        r1 = min(box_a["row_max_m"], box_b["row_max_m"])
        c0 = max(box_a["col_min_m"], box_b["col_min_m"])
        c1 = min(box_a["col_max_m"], box_b["col_max_m"])
    except KeyError:
        return 0.0
    inter = max(0.0, r1 - r0) * max(0.0, c1 - c0)
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, box_a["row_max_m"] - box_a["row_min_m"]) * max(0.0, box_a["col_max_m"] - box_a["col_min_m"])
    area_b = max(0.0, box_b["row_max_m"] - box_b["row_min_m"]) * max(0.0, box_b["col_max_m"] - box_b["col_min_m"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _condition_view(ta: dict, tb: dict, cond_a: dict, cond_b: dict) -> dict[str, Any]:
    def per_tile(tile: dict, cond: dict) -> dict[str, Any]:
        indicators = (cond or {}).get("indicators") or {}
        vc = indicators.get("valid_coverage") or {}
        tex = indicators.get("texture") or {}
        illum = indicators.get("illumination_range") or {}
        span = None
        value = illum.get("value")
        if isinstance(value, dict):
            span = (value.get("max") - value.get("min")) if (value.get("max") is not None and value.get("min") is not None) else None
        contrast = _contrast_level(span)
        valid = vc.get("value")
        if not isinstance(valid, (int, float)):
            valid = 0.0
        return {
            "valid_fraction": round(float(valid), 6),
            "texture": str(tex.get("status", "UNKNOWN")),
            "contrast": contrast,
            "contrast_span_dn": (float(span) if span is not None else None),
            "dynamic_range": round(float(span) / 65535.0, 6) if span is not None else 0.0,
        }

    va = per_tile(ta, cond_a)
    vb = per_tile(tb, cond_b)
    return {
        "valid_fraction_a": va["valid_fraction"],
        "valid_fraction_b": vb["valid_fraction"],
        "texture_a": va["texture"],
        "texture_b": vb["texture"],
        "contrast_a": va["contrast"],
        "contrast_b": vb["contrast"],
        "dynamic_range_a": va["dynamic_range"],
        "dynamic_range_b": vb["dynamic_range"],
    }


def _contrast_level(span) -> str:
    if span is None:
        return "UNKNOWN"
    if span < 9000:
        return "LOW"
    if span < 30000:
        return "NORMAL"
    return "HIGH"


def matching_overview(settings: Settings) -> dict[str, Any]:
    """Bulk matching readiness summary for the Overview page / API."""
    service = MatchingService(settings)
    registry = PairRegistry(settings)
    pairs = registry.list()
    rows = []
    for record in pairs:
        status = service.read_status(record.pair_id)
        summary = status.get("summary") or {}
        rows.append({
            "pair_id": record.pair_id,
            "state": status.get("state", "NOT_STARTED"),
            "configuration_id": status.get("configuration_id") or default_matcher_configuration_id(),
            "level": "COMPLETE" if status.get("state") == "COMPLETE" else "READY" if status.get("state") in ("NOT_STARTED", None) and not status.get("blocked") else "BLOCKED",
            "candidates": int(summary.get("total_candidates", 0)),
            "blocked_code": (status.get("blocked") or {}).get("code"),
        })
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    total_candidates = sum(int(r["candidates"]) for r in rows)
    return {
        "pairs": rows,
        "counts": counts,
        "total_candidates": total_candidates,
        "blocked": not any(r["candidates"] > 0 for r in rows),
        "reason": (
            "No real validated lunar pair is available, so real-data matching is BLOCKED."
            if not rows or all(r["blocked_code"] for r in rows)
            else f"{total_candidates} candidate correspondences recorded across registered pairs."
        ),
    }