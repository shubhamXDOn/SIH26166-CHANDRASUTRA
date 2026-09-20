"""Processing service — orchestrates a full M2 PREPARE run (SIH26166).

Flow (all stages recorded in processing_status.json):
    READING -> PREPROCESSING -> PREPARING_OVERLAP -> GENERATING_CROPS
            -> ANALYZING_CONDITION -> READY_FOR_MATCHING | BLOCKED | FAILED

Derived artifacts live ONLY under ``data/derived/processing/<pair>/<config>/``.
Raw products are only ever read/hashed, never written.

Truthfulness:
    * real pairs without documented geometry BLOCK at overlap prep;
    * TEST_FIXTURE geometry (explicitly labelled) exercises the full path
      for software validation only;
    * matcher-readiness is computed from the registered requirement list
      against actual evidence (tiles + conditions), never a guess.
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
from ..hardening import (
    RunLock,
    TimeBudget,
    atomic_write_json,
    atomic_write_npy,
    elapsed_ms,
    record_run_event,
)
from ..loader import load_product
from ..logging_conf import get_logger
from ..pairs import PairRegistry, _rel_or_filename, resolve_raw_path, validate_record
from .conditions import analyze_tile as analyze_tile_cond, summarize
from .config import ProcessingConfig, configurations_public, load_processing_config
from .crops import generate_tiles, tile_to_dict
from .geometry import GeometryBlock, GEOMETRY_SOURCE_FIXTURE, resolve_geometry
from .manifest import ManifestBuilder, load_manifest
from .masking import build_invalid_mask
from .normalize import display_normalize
from .overlap import compute_overlap
from .states import (
    ProcessingState,
    STAGE_ORDER,
    STATE_LABELS,
    initial_stages,
    synthetic_status,
)

logger = get_logger(__name__)
UNKNOWN = "UNKNOWN"


def rel_string(data_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(data_root.resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return path.name


class ProcessingService:
    """Backend orchestration + on-disk state for M2 processing runs."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_root_path
        self.base = self.root / "derived" / "processing"

    # ------------------------------------------------------------------
    # paths + state persistence
    # ------------------------------------------------------------------
    def run_dir(self, pair_id: str, configuration_id: str) -> Path:
        return self.base / pair_id / configuration_id

    def status_path(self, pair_id: str, configuration_id: str) -> Path:
        return self.run_dir(pair_id, configuration_id) / "processing_status.json"

    def manifest_path(self, pair_id: str, configuration_id: str) -> Path:
        return self.run_dir(pair_id, configuration_id) / "processing_manifest.json"

    def _write_json(self, path: Path, payload: dict) -> None:
        atomic_write_json(path, payload)

    def read_status(self, pair_id: str, configuration_id: str = "") -> dict[str, Any]:
        cfg_id = configuration_id or default_configuration_id()
        path = self.status_path(pair_id, cfg_id)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        return synthetic_status(cfg_id, pair_id=pair_id)

    def write_status(self, status: dict[str, Any]) -> None:
        pair_id = status.get("pair_id", "")
        cfg_id = status.get("configuration_id") or default_configuration_id()
        self._write_json(self.status_path(pair_id, cfg_id), status)

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        """Return the most recent run dir for a pair (any configuration)."""
        pair_dirs = sorted(d for d in (self.base / pair_id).glob("*") if d.is_dir()) if (self.base / pair_id).is_dir() else []
        return pair_dirs[-1] if pair_dirs else None

    def reset(self, pair_id: str) -> None:
        """Remove derived processing artifacts for a pair (never raw)."""
        pair_dir = self.base / pair_id
        if pair_dir.is_dir():
            shutil.rmtree(pair_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # prepare lifecycle
    # ------------------------------------------------------------------
    def prepare(self, pair_id: str, *, configuration_id: str | None = None,
                geometry: dict[str, Any] | None = None) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        try:
            cfg = load_processing_config(configuration_id)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        run = self.run_dir(pair_id, cfg.configuration_id)
        run.mkdir(parents=True, exist_ok=True)
        budget = TimeBudget(cfg.p("execution", "max_runtime_seconds", default=300))
        started = time.perf_counter()
        with RunLock(run, budget_seconds=self.settings.run_stale_budget_seconds, tag="m2_processing"):
            status = {
                "pair_id": pair_id,
                "configuration_id": cfg.configuration_id,
                "configuration_version": cfg.configuration_version,
                "state": ProcessingState.READING.value,
                "state_label": STATE_LABELS[ProcessingState.READING.value],
                "progress": 5,
                "started_at": _now(),
                "finished_at": None,
                "stages": initial_stages(),
                "blocked": None,
                "error": None,
                "matcher_readiness": None,
                "geometry_source": None,
                "note": "",
            }
            try:
                result = self._prepare_main(status, run, cfg, record, pair_id, geometry, budget)
                record_run_event("m2_prepare", pair_id, cfg.configuration_id,
                                 status.get("state", "DONE"), elapsed_ms(started))
                return result
            except Exception as exc:  # noqa: BLE001
                record_run_event("m2_prepare", pair_id, cfg.configuration_id, "FAILED",
                                 elapsed_ms(started), error_code=getattr(exc, "code", None))
                raise

    # ------------------------------------------------------------------
    def _prepare_main(self, status, run, cfg, record, pair_id, geometry, budget) -> dict:
        data_root = self.root
        stages = {s["id"]: s for s in status["stages"]}
        manifest = ManifestBuilder(
            data_root=data_root,
            application=self.settings.product_name,
            app_version=self.settings.app_version,
            milestone=self.settings.milestone,
            configuration=cfg.as_manifest_snapshot(),
            pair_id=pair_id,
            products=[],
        )

        def blocker(code: str, reason: str, stage_id: str) -> dict:
            stage = stages.get(stage_id)
            if stage is not None:
                stage["state"] = "blocked"
                stage["detail"] = reason
            status["state"] = ProcessingState.BLOCKED.value
            status["state_label"] = STATE_LABELS[ProcessingState.BLOCKED.value]
            status["blocked"] = {"stage": stage_id, "code": code, "reason": reason}
            status["finished_at"] = _now()
            stages["run"]["state"] = "blocked"
            stages["run"]["finished_at"] = status["finished_at"]
            stages["run"]["detail"] = f"PREPARE run blocked at {stage_id} ({code})."
            manifest.finish_step(outputs=[], status="BLOCKED")
            manifest.write(self.manifest_path(pair_id, cfg.configuration_id))
            status["note"] = "PREPARE run stopped truthfully at the blocking stage; no data was skipped or guessed."
            self.write_status(status)
            return status

        # ---------------- stage 1: READING + validation/integrity ----------
        stages["reading"]["started_at"] = _now()
        stages["reading"]["state"] = "running"
        manifest.begin_step("reading", "Reading raw products and verifying integrity")
        try:
            validation = validate_record(record, self.settings)
        except Exception as exc:  # noqa: BLE001
            return self._fail(status, stages, "reading", f"Pair validation raised: {exc}", manifest, run)
        if validation["status"] != "VALID":
            return blocker("PAIR_NOT_VALID",
                           f"Pair {pair_id} failed validation — the raw products are not structurally valid before preprocessing.",
                           stage_id="reading")

        product_infos: list[dict[str, Any]] = []
        try:
            for side, rel, sensor, labelside in (
                ("a", _rel_or_filename(record.image_a_rel_path, record.image_a_filename), record.sensor_a, "label_a_filename"),
                ("b", _rel_or_filename(record.image_b_rel_path, record.image_b_filename), record.sensor_b, "label_b_filename"),
            ):
                path = resolve_raw_path(self.settings, f"image_{side}", sensor, rel)
                if not path.is_file():
                    return blocker("PRODUCT_MISSING", f"Image {side.upper()} raw file missing: {path.name}", stage_id="reading")
                label_path = (path.parent / getattr(record, labelside)) if getattr(record, labelside, None) else None
                if label_path is not None and not label_path.is_file():
                    label_path = None
                info = load_product(path, label_path)
                if info.status != "OK":
                    return blocker("PRODUCT_READ_FAILED",
                                   f"Image {side.upper()} could not be loaded as a CH-2 product: {info.error.get('message', '')}",
                                   stage_id="reading")
                expected_hash = record.raw_file_hash_a if side == "a" else record.raw_file_hash_b
                if expected_hash and info.raw_sha256 != expected_hash:
                    return blocker("RAW_INTEGRITY_MISMATCH",
                                   f"Image {side.upper()} SHA-256 does not match the recorded raw hash — raw file changed since registration.",
                                   stage_id="reading")
                product_infos.append({
                    "side": side, "sensor": sensor, "path": path,
                    "label_filename": info.label_filename, "info": info,
                })
        except (ValueError, OSError) as exc:
            return self._fail(status, stages, "reading", f"Could not resolve raw products: {exc}", manifest, run)

        raw_integrity_ok = all(not p["info"].error for p in product_infos)
        manifest.record(products=[
            {
                "side": p["side"], "sensor": p["sensor"],
                "filename": p["info"].filename,
                "label_filename": p["info"].label_filename,
                "product_id": p["info"].product_id,
                "raw_sha256": p["info"].raw_sha256,
                "raw_size_bytes": p["info"].size_bytes,
                "width": p["info"].width, "height": p["info"].height,
                "dtype": p["info"].dtype,
                "processing_level": p["info"].processing_level,
                "acquisition_datetime": p["info"].acquisition_datetime,
            }
            for p in product_infos
        ])
        stages["reading"]["finished_at"] = _now()
        stages["reading"]["state"] = "complete"
        stages["reading"]["detail"] = f"Raw integrity verified ({len(product_infos)} products)."
        manifest.finish_step(outputs=[])
        status["progress"] = 20
        self.write_status(status)
        self._check_timeout(budget, status, stages, manifest, run, "reading")

        # ---------------- stage 2: PREPROCESSING (mask + display) ---------
        stages["preprocessing"]["started_at"] = _now()
        stages["preprocessing"]["state"] = "running"
        manifest.begin_step("preprocessing", "Building invalid-data masks and display products")
        preprocessed: dict[str, dict[str, Any]] = {}
        try:
            for p in product_infos:
                info = p["info"]
                array = _read_array(p["path"], info)
                mask, mask_stats = build_invalid_mask(array, masking_params(cfg))
                display, norm_stats = display_normalize(
                    array, mask,
                    low_pct=cfg.p("normalization", "display_low_percentile", default=1.0),
                    high_pct=cfg.p("normalization", "display_high_percentile", default=99.0),
                )
                sensor_dir = run / p["sensor"]
                sensor_dir.mkdir(parents=True, exist_ok=True)
                display_path = sensor_dir / "preprocessed_display_u16.npy"
                mask_path = sensor_dir / "invalid_mask_u8.npy"
                stats_path = sensor_dir / "stats.json"
                atomic_write_npy(display_path, display)
                atomic_write_npy(mask_path, mask)
                self._write_json(stats_path, {
                    "side": p["side"], "sensor": p["sensor"],
                    "dimensions": {"width": int(info.width), "height": int(info.height)},
                    "mask": mask_stats,
                    "normalization": norm_stats,
                    "radiometric": cfg.radiometric_status,
                })
                preprocessed[p["side"]] = {
                    "sensor": p["sensor"], "display_path": display_path, "mask_path": mask_path,
                    "stats_path": stats_path, "mask": mask, "display": display,
                }
        except (OSError, ValueError) as exc:
            return self._fail(status, stages, "preprocessing", f"Preprocessing failed: {exc}", manifest, run)
        preprocess_ok = len(preprocessed) == 2
        stages["preprocessing"]["finished_at"] = _now()
        stages["preprocessing"]["state"] = "complete"
        stages["preprocessing"]["detail"] = "Mask + display product written for both sensors (radiometric NOT_APPLICABLE)."
        manifest.finish_step(outputs=[pp["display_path"] for pp in preprocessed.values()]
                             + [pp["mask_path"] for pp in preprocessed.values()])
        status["products"] = {
            side: {
                "sensor": pp["sensor"],
                "display_rel": rel_string(data_root, pp["display_path"]),
                "mask_rel": rel_string(data_root, pp["mask_path"]),
                "stats_rel": rel_string(data_root, pp["stats_path"]),
            }
            for side, pp in preprocessed.items()
        }
        status["progress"] = 45
        self.write_status(status)
        self._check_timeout(budget, status, stages, manifest, run, "preprocessing")

        # ---------------- stage 3: PREPARING_OVERLAP ----------------------
        stages["preparing_overlap"]["started_at"] = _now()
        stages["preparing_overlap"]["state"] = "running"
        manifest.begin_step("preparing_overlap", "Preparing documented overlap from ground geometry")
        plan = resolve_geometry(
            record,
            product_infos[0]["info"], product_infos[1]["info"],
            geometry,
        )
        if isinstance(plan, GeometryBlock):
            manifest.finish_step(outputs=[], status="BLOCKED")
            manifest.record(geometry={"source": UNKNOWN, "blocked": plan.to_dict()})
            self._write_json(run / "diagnostics" / "overlap.json", plan.to_dict())
            return blocker(plan.code, plan.message, stage_id="preparing_overlap")

        overlap = compute_overlap(plan, record.sensor_a, record.sensor_b)
        status["geometry_source"] = plan.source
        if overlap.status == "NO_OVERLAP":
            manifest.finish_step(outputs=[], status="BLOCKED")
            manifest.record(geometry=plan.to_dict(), overlap=None)
            self._write_json(run / "diagnostics" / "overlap.json", overlap.to_dict())
            return blocker("NO_OVERLAP", overlap.reason, stage_id="preparing_overlap")

        (run / "diagnostics").mkdir(parents=True, exist_ok=True)
        self._write_json(run / "diagnostics" / "overlap.json", overlap.to_dict())
        manifest.record(geometry=plan.to_dict(), overlap=overlap.to_dict())
        overlap_valid = overlap.status == "CONFIRMED_OVERLAP"
        stages["preparing_overlap"]["finished_at"] = _now()
        stages["preparing_overlap"]["state"] = "complete"
        stages["preparing_overlap"]["detail"] = f"Overlap {overlap.status} ({overlap.envelope.width_m:.1f}m x {overlap.envelope.height_m:.1f}m)."
        manifest.finish_step(outputs=[run / "diagnostics" / "overlap.json"])
        status["progress"] = 65
        self.write_status(status)
        self._check_timeout(budget, status, stages, manifest, run, "preparing_overlap")

        # ---------------- stage 4: GENERATING_CROPS -----------------------
        stages["generating_crops"]["started_at"] = _now()
        stages["generating_crops"]["state"] = "running"
        manifest.begin_step("generating_crops", "Generating sensor-native tiles over the overlap region")
        crops_dir = run / "crops"
        crops_dir.mkdir(parents=True, exist_ok=True)
        all_tiles: list[dict[str, Any]] = []
        try:
            for side, pp in preprocessed.items():
                sensor = pp["sensor"]
                region = overlap.regions[sensor]
                geom = plan.products[sensor]
                tiles = generate_tiles(
                    pp["display"], pp["mask"], region,
                    sensor=sensor, side=side, pair_id=pair_id, cfg=cfg,
                )
                for tile in tiles:
                    window = pp["display"][tile.row_start:tile.row_start + tile.height,
                                           tile.col_start:tile.col_start + tile.width]
                    tpath = crops_dir / tile.array_filename
                    atomic_write_npy(tpath, window)
                    if tile.ground_box is None:
                        tile.ground_box = ground_box_for(geom, tile).to_dict()
                    rec = tile_to_dict(tile)
                    rec["array_rel"] = rel_string(data_root, tpath)
                    rec["preview_url"] = f"/api/processing/{pair_id}/tiles/{tile.tile_id}/preview"
                    all_tiles.append(rec)
        except (OSError, ValueError) as exc:
            return self._fail(status, stages, "generating_crops", f"Crop generation failed: {exc}", manifest, run)

        tiles_generated = {record.sensor_a: 0, record.sensor_b: 0}
        for t in all_tiles:
            tiles_generated[t["sensor"]] = tiles_generated.get(t["sensor"], 0) + 1
        usable_counts = {s: sum(1 for t in all_tiles if t["sensor"] == s and not t["too_small"]) for s in (record.sensor_a, record.sensor_b)}

        if not all_tiles or any(usable_counts.get(s, 0) == 0 for s in (record.sensor_a, record.sensor_b)):
            self._write_json(crops_dir / "tiles.json", {"pair_id": pair_id, "count": len(all_tiles), "tiles": all_tiles})
            manifest.finish_step(outputs=[], status="BLOCKED")
            return blocker("TILES_UNUSABLE",
                           "The overlap region is too small for usable sensor-native tiles on at least one side. "
                           "Crops were not produced; nothing was invented.",
                           stage_id="generating_crops")

        self._write_json(crops_dir / "tiles.json", {"pair_id": pair_id, "count": len(all_tiles), "tiles": all_tiles})
        stages["generating_crops"]["finished_at"] = _now()
        stages["generating_crops"]["state"] = "complete"
        stages["generating_crops"]["detail"] = f"{len(all_tiles)} sensor-native tiles recorded."
        manifest.finish_step(outputs=[crops_dir / "tiles.json"] + [crops_dir / t["array_filename"] for t in all_tiles])
        manifest.record(tiles={
            "count": len(all_tiles),
            "per_sensor": tiles_generated,
            "usable": usable_counts,
            "tiles": all_tiles,
        })
        status["tiles"] = {"count": len(all_tiles), "per_sensor": tiles_generated, "usable": usable_counts}
        status["progress"] = 80
        self.write_status(status)
        self._check_timeout(budget, status, stages, manifest, run, "generating_crops")

        # ---------------- stage 5: ANALYZING_CONDITION ---------------------
        stages["analyzing_condition"]["started_at"] = _now()
        stages["analyzing_condition"]["state"] = "running"
        manifest.begin_step("analyzing_condition", "Estimating lunar scene conditions per tile")
        tile_results: list[dict[str, Any]] = []
        try:
            for t in all_tiles:
                array_p = crops_dir / t["array_filename"]
                window = np.load(array_p, mmap_mode="r")
                side = t["side"]
                mask_arr = np.load(preprocessed[side]["mask_path"], mmap_mode="r")
                r0, c0 = t["row_start"], t["col_start"]
                mask_win = np.asarray(mask_arr[r0:r0 + t["height"], c0:c0 + t["width"]])
                arr_win = np.asarray(window)
                tile_results.append(analyze_tile_cond(
                    arr_win, mask_win,
                    tile_id=t["tile_id"], sensor=t["sensor"], cfg=cfg,
                    too_small=t["too_small"],
                ))
        except (OSError, ValueError) as exc:
            return self._fail(status, stages, "analyzing_condition", f"Condition analysis failed: {exc}", manifest, run)

        summary = summarize(tile_results)
        self._write_json(run / "diagnostics" / "conditions.json", {
            "pair_id": pair_id,
            "configuration_id": cfg.configuration_id,
            "geometry_source": plan.source,
            "tiles": tile_results,
            "summary": summary,
        })
        manifest.record(conditions={"tiles": tile_results, "summary": summary})
        stages["analyzing_condition"]["finished_at"] = _now()
        stages["analyzing_condition"]["state"] = "complete"
        stages["analyzing_condition"]["detail"] = f"{summary['tiles']} tile(s) assessed; level {summary.get('level', 'NOT_RUN')}."
        manifest.finish_step(outputs=[run / "diagnostics" / "conditions.json"])
        status["progress"] = 95
        self.write_status(status)
        self._check_timeout(budget, status, stages, manifest, run, "analyzing_condition")

        # ---------------- matcher-readiness contract -----------------------
        readiness = self._matcher_readiness(
            cfg, raw_integrity_ok=raw_integrity_ok, preprocess_ok=preprocess_ok,
            overlap_valid=overlap_valid, all_tiles=all_tiles,
            usable_counts=usable_counts, condition_summary=summary,
        )
        status["matcher_readiness"] = readiness
        manifest.record(matcher_readiness=readiness)

        status["state"] = ProcessingState.READY_FOR_MATCHING.value
        status["state_label"] = STATE_LABELS[ProcessingState.READY_FOR_MATCHING.value]
        manifest.write(self.manifest_path(pair_id, cfg.configuration_id))
        status["finished_at"] = _now()
        status["progress"] = 100
        stages["run"]["state"] = "complete"
        stages["run"]["finished_at"] = status["finished_at"]
        stages["run"]["detail"] = "PREPARE run completed."
        status["note"] = (
            "Derived products, tiles and conditions are stored under "
            f"derived/processing/{pair_id}/{cfg.configuration_id}/ with a provenance manifest. "
            "Raw products are untouched."
        )
        self.write_status(status)
        logger.info("Processing %s < %s complete -> %s", pair_id, cfg.configuration_id, readiness["level"],
                    extra={"operation": "m2_prepare", "status": "done"})
        return status

    # ------------------------------------------------------------------
    def _matcher_readiness(self, cfg: ProcessingConfig, *, raw_integrity_ok: bool,
                           preprocess_ok: bool, overlap_valid: bool,
                           all_tiles: list[dict[str, Any]],
                           usable_counts: dict[str, int],
                           condition_summary: dict[str, Any]) -> dict[str, Any]:
        counts = dict(usable_counts)
        tiles_usable = (
            bool(all_tiles)
            and all(counts.get(s, 0) > 0 for s in counts)
            and all(any(not t["too_small"] for t in all_tiles if t["sensor"] == s) for s in counts)
        )
        condition_evaluated = condition_summary.get("assessed", 0) > 0

        spec = {
            "raw_integrity_ok": ("Raw SHA-256 re-verified for both products", raw_integrity_ok),
            "preprocess_ok": ("Preprocessed products + invalid-data masks written", preprocess_ok),
            "overlap_valid": (f"Overlap { 'CONFIRMED' if overlap_valid else 'not confirmed' }", overlap_valid),
            "tiles_generated": (f"Tiles generated: { {k: v for k, v in counts.items()} if counts else 'none' }", bool(all_tiles)),
            "tiles_usable": (f"Usable tiles per side: {counts if counts else 'none'}", tiles_usable),
            "condition_evaluated": ("Scene conditions evaluated", condition_evaluated),
        }
        requirements = []
        for req_id in cfg.required_readiness:
            label, met = spec.get(req_id, (f"Requirement '{req_id}'", False))
            requirements.append({"id": req_id, "label": label, "met": bool(met),
                                 "detail": "OK" if met else "not satisfied"})

        met_all = all(r["met"] for r in requirements)
        level = "READY" if met_all else "BLOCKED"
        condition_level = (condition_summary or {}).get("level")
        note = "All matcher-readiness requirements satisfied."
        if level == "READY" and condition_level in ("LOW_TEXTURE", "HIGH_TEXTURE"):
            level = "CONDITIONAL"
            note = f"Matcher ready but scene condition is {condition_level} — reliability reduced."
        if level == "BLOCKED":
            unmet = [r["id"] for r in requirements if not r["met"]]
            note = f"Matcher NOT ready — unmet requirements: {', '.join(unmet)}."

        return {
            "level": level,
            "ready": level in ("READY", "CONDITIONAL"),
            "note": note,
            "requirements": requirements,
            "tile_counts": counts,
            "condition": condition_summary,
        }

    # ------------------------------------------------------------------
    def _check_timeout(self, budget, status, stages, manifest, run, stage_id: str) -> dict | None:
        """Honest M11 timeout: a run that exceeds its time budget becomes a
        FAILED/TIMEOUT run at the last clean stage boundary — never a silent
        PARTIAL run presented as success."""
        if not budget.expired():
            return None
        return self._fail(
            status, stages, stage_id,
            "PREPARE run exceeded its time budget; stopped at the last completed stage. "
            "No data was skipped, guessed or presented as complete.",
            manifest, run, code="TIMEOUT",
        )

    # ------------------------------------------------------------------
    def _fail(self, status, stages, stage_id: str, message: str, manifest: ManifestBuilder,
              run: Path, *, code: str = "PROCESSING_FAILED") -> dict:
        stage = stages.get(stage_id)
        if stage is not None:
            stage["state"] = "failed"
            stage["detail"] = (stage.get("detail") or "") + message
        status["state"] = ProcessingState.FAILED.value
        status["state_label"] = STATE_LABELS[ProcessingState.FAILED.value]
        status["error"] = {
            "code": code,
            "message": message,
            "severity": "error",
            "retryable": True,
            "details": {"stage": stage_id},
        }
        status["finished_at"] = _now()
        stages["run"]["state"] = "failed"
        self.write_status(status)
        logger.error("Processing failed at %s (%s): %s", stage_id, code, message,
                     extra={"operation": "m2_prepare", "status": "failed"})
        exc = AppError(message, details={"stage": stage_id})
        exc.code = code
        raise exc

    # ------------------------------------------------------------------
    # read endpoints
    # ------------------------------------------------------------------
    def manifest(self, pair_id: str) -> dict[str, Any] | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        return load_manifest(run / "processing_manifest.json")

    def conditions(self, pair_id: str) -> dict[str, Any] | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "diagnostics" / "conditions.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def tiles(self, pair_id: str) -> dict[str, Any] | None:
        run = self.find_run_for_pair(pair_id)
        if run is None:
            return None
        path = run / "crops" / "tiles.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def tile(self, pair_id: str, tile_id: str) -> dict[str, Any] | None:
        index = self.tiles(pair_id)
        if not index:
            return None
        for tile in index.get("tiles", []):
            if tile.get("tile_id") == tile_id:
                return tile
        return None

    def tile_preview_path(self, pair_id: str, tile_id: str) -> Path | None:
        run = self.find_run_for_pair(pair_id)
        tile = self.tile(pair_id, tile_id)
        if run is None or tile is None:
            return None
        if not run.is_relative_to(self.base / pair_id):
            return None
        array_path = run / "crops" / tile.get("array_filename", "")
        if not array_path.is_file():
            return None
        preview = run / "diagnostics" / f"{tile_id}_preview.png"
        if preview.is_file():
            return preview
        arr = np.load(array_path, mmap_mode="r")
        try:
            from PIL import Image
        except ImportError:  # pragma: no cover
            return None
        a = np.asarray(arr)
        if a.ndim != 2:
            return None
        scale = min(1.0, 128 / max(a.shape))
        if scale < 1.0:
            step = max(1, int(round(1 / scale)))
            a = a[::step, ::step]
        img = (np.asarray(a, dtype=np.float32) / 257.0).astype(np.uint8)
        (run / "diagnostics").mkdir(parents=True, exist_ok=True)
        import io

        from ..hardening import atomic_write_bytes

        buf = io.BytesIO()
        Image.fromarray(img, mode="L").save(buf, format="PNG")
        atomic_write_bytes(preview, buf.getvalue())
        return preview


# ---------------------------------------------------------------------------
def _read_array(path: Path, info) -> np.ndarray:
    from ..loader import open_array, _open_container

    meta = info.metadata or {}
    if (isinstance(meta.get("lines"), int) and isinstance(meta.get("samples"), int)
            and meta.get("data_type") and ("offset" in meta or "offset_bytes" in meta)):
        try:
            return open_array(path, meta)
        except Exception:  # noqa: BLE001 - fall through to container
            pass
    arr, _w, _h, _b, _d = _open_container(path)
    return arr


def masking_params(cfg: ProcessingConfig) -> dict:
    return dict(cfg.p("masking", default={}))


def ground_box_for(geom, tile) -> "FootprintBox":
    from .geometry import FootprintBox

    row_min_m = geom.row_offset_m + tile.row_start * geom.gsd_m
    col_min_m = geom.col_offset_m + tile.col_start * geom.gsd_m
    return FootprintBox(
        row_min_m=row_min_m,
        row_max_m=row_min_m + tile.height * geom.gsd_m,
        col_min_m=col_min_m,
        col_max_m=col_min_m + tile.width * geom.gsd_m,
    )


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def default_configuration_id() -> str:
    return load_processing_config().configuration_id


def processing_overview(settings: Settings) -> dict[str, Any]:
    """Bulk readiness summary for the Data workspace / Overview page."""
    service = ProcessingService(settings)
    registry = PairRegistry(settings)
    pairs = registry.list()
    rows = []
    for record in pairs:
        status = service.read_status(record.pair_id)
        readiness = status.get("matcher_readiness") or {}
        rows.append({
            "pair_id": record.pair_id,
            "state": status.get("state", "NOT_STARTED"),
            "configuration_id": status.get("configuration_id") or default_configuration_id(),
            "level": readiness.get("level", "NOT_STARTED"),
            "ready": bool(readiness.get("ready", False)),
            "validated": record.validation_status == "VALID",
        })
    if not rows:
        return {
            "pairs": [],
            "counts": {},
            "blocked": True,
            "reason": "M2 real-data processing: BLOCKED — no validated real pair is available.",
        }
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {
        "pairs": rows,
        "counts": counts,
        "blocked": not any(r["ready"] for r in rows),
        "reason": "At least one pair is matcher-ready." if any(r["ready"] for r in rows) else "No pair is matcher-ready yet.",
    }