"""M5 Spatial Reliability & Reliability-Aware Selection service.

Consumes M2 scene geometry (overlap + tiles), M3 match artifacts and M4
trusted tile evidence to produce a deterministic per-cell spatial reliability
representation and a reliability-aware selection of registration evidence.
All numbers are binary/count-based: no fabricated confidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

import numpy as np

from backend.app.config import rfc3339_now
from backend.app.hardening import atomic_write_json, atomic_write_npz
from backend.app.spatial.config import SpatialReliabilityConfig
from backend.app.spatial.grid import Grid
from backend.app.spatial.manifest import artifact_spec, build_spatial_manifest
from backend.app.spatial.mapping import (
    load_scene_map,
    map_correspondences,
)
from backend.app.spatial.reliability import compute_reliability
from backend.app.spatial.selection import (
    INSUFFICIENT,
    SELECTED,
    assign_reasons,
    plan_selection,
)
from backend.app.spatial.states import (
    MappingStatus,
    SpatialBlockCode,
    SpatialRunState,
)
from backend.app.trust.config import TrustConfig
from backend.app.trust.engine import evaluate_tile
from backend.app.trust.states import TileTrustState

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

_VALID_SPATIAL_CONFIG_IDS = {"SR-M5-001"}

_SPATIAL_STATUS_FILENAME = "status.json"


class SpatialService:
    def __init__(
        self,
        data_root: Path,
        m5_cfg: dict | None = None,
        m4_defaults: dict | None = None,
    ):
        self._data = data_root
        self._m5_cfg = m5_cfg or {}
        self._m4_defaults = m4_defaults or {}
        self._derived_rel = self._m5_cfg.get("derived_rel", "derived/spatial")

    # ---------- path discovery ---------------------------------------------- #

    def _spatial_root(self) -> Path:
        return self._data / self._derived_rel

    def _match_run_dir(self, pair_id: str) -> Path | None:
        pair_match = self._data / "derived" / "matches" / pair_id
        if not pair_match.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_match.iterdir()):
            if not proc_dir.is_dir():
                continue
            for matcher_dir in sorted(proc_dir.iterdir()):
                if matcher_dir.is_dir():
                    deepest = matcher_dir
        if deepest is not None and (deepest / "summary.json").is_file():
            return deepest
        return None

    def _processing_root(self, pair_id: str) -> Path | None:
        pair_proc = self._data / "derived" / "processing" / pair_id
        if not pair_proc.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_proc.iterdir()):
            if proc_dir.is_dir():
                deepest = proc_dir
        return deepest

    def _trust_run_dir(self, pair_id: str) -> Path | None:
        pair_trust = self._data / "derived" / "trust" / pair_id
        if not pair_trust.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_trust.iterdir()):
            if not proc_dir.is_dir():
                continue
            for matcher_dir in sorted(proc_dir.iterdir()):
                if not matcher_dir.is_dir():
                    continue
                for trust_dir in sorted(matcher_dir.iterdir()):
                    if trust_dir.is_dir():
                        deepest = trust_dir
        if deepest is not None and (deepest / "trust_status.json").is_file():
            return deepest
        return None

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        pair_spatial = self._spatial_root() / pair_id
        if not pair_spatial.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_spatial.iterdir()):
            if not proc_dir.is_dir():
                continue
            for matcher_dir in sorted(proc_dir.iterdir()):
                if not matcher_dir.is_dir():
                    continue
                for trust_dir in sorted(matcher_dir.iterdir()):
                    if not trust_dir.is_dir():
                        continue
                    for sr_dir in sorted(trust_dir.iterdir()):
                        if sr_dir.is_dir():
                            deepest = sr_dir
        return deepest

    # ---------- public read API --------------------------------------------- #

    def read_status(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return self._synthetic_status(pair_id, SpatialRunState.NOT_STARTED)
        status_path = run_dir / _SPATIAL_STATUS_FILENAME
        if not status_path.is_file():
            return self._synthetic_status(pair_id, SpatialRunState.NOT_STARTED)
        try:
            with open(status_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return self._synthetic_status(pair_id, SpatialRunState.NOT_STARTED)

    def manifest(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "spatial_manifest.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def summary(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "summary.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def reliability_map(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "reliability_map.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def components(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "components.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def cells(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "cells.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def selection(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "selection.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def mapping(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "mapping.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def selected_correspondences(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "selected_correspondences.npz"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        data = np.load(str(path), allow_pickle=True)
        result: dict = {"pair_id": pair_id, "fields": list(data.files)}
        for k in data.files:
            result[f"{k}_count"] = int(len(data[k]))
        return result

    # ---------- prerequisites ------------------------------------------------ #

    def prerequisites(self, pair_id: str) -> dict:
        match_dir = self._match_run_dir(pair_id)
        if match_dir is None:
            return {
                "ready": False,
                "block_code": SpatialBlockCode.MATCHING_NOT_AVAILABLE.value,
            }
        try:
            with open(match_dir / "summary.json", encoding="utf-8") as f:
                summary = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {
                "ready": False,
                "block_code": SpatialBlockCode.MATCHING_NOT_AVAILABLE.value,
            }
        total_candidates = sum(
            int(t.get("candidates", 0) or 0) for t in summary.get("per_tile", [])
        )
        if total_candidates == 0:
            return {
                "ready": False,
                "block_code": SpatialBlockCode.TRUST_OUTPUTS_MISSING.value,
            }
        trust_dir = self._trust_run_dir(pair_id)
        if trust_dir is None:
            return {
                "ready": False,
                "block_code": SpatialBlockCode.M4_NOT_AVAILABLE.value,
            }
        return {
            "ready": True,
            "block_code": None,
            "match_dir": match_dir,
            "trust_dir": trust_dir,
            "match_summary": summary,
        }

    # ---------- run ---------------------------------------------------------- #

    def run(self, pair_id: str, spatial_config_id: str = "SR-M5-001") -> dict:
        if spatial_config_id not in _VALID_SPATIAL_CONFIG_IDS:
            return self._synthetic_status(
                pair_id, SpatialRunState.BLOCKED,
                block_code=SpatialBlockCode.SPATIAL_UNKNOWN_CONFIG.value,
            )
        prereq = self.prerequisites(pair_id)
        if not prereq["ready"]:
            return self._synthetic_status(
                pair_id, SpatialRunState.BLOCKED,
                block_code=prereq["block_code"],
            )
        match_dir = prereq["match_dir"]
        trust_dir = prereq["trust_dir"]
        match_summary = prereq["match_summary"]

        trust_status = self._read_json(trust_dir / "trust_status.json", {})
        if trust_status.get("gate_state") != "COMPLETE":
            return self._synthetic_status(
                pair_id, SpatialRunState.BLOCKED,
                block_code=SpatialBlockCode.NO_TRUSTED_EVIDENCE.value,
            )
        tile_trust = self._read_json(trust_dir / "tile_trust.json", {})
        trusted_tiles = [
            t for t in tile_trust.get("tiles", [])
            if t.get("trust_state") == TileTrustState.TRUSTED.value
        ]
        if not trusted_tiles:
            return self._synthetic_status(
                pair_id, SpatialRunState.BLOCKED,
                block_code=SpatialBlockCode.NO_TRUSTED_EVIDENCE.value,
            )

        proc_cfg = str(match_summary.get("processing_configuration_id", "PC-M2-001"))
        matcher_cfg = str(match_summary.get("configuration_id", "MC-M3-001"))
        trust_cfg_id = str(trust_dir.name)
        run_dir = self._spatial_root() / pair_id / proc_cfg / matcher_cfg / trust_cfg_id / spatial_config_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "policies").mkdir(exist_ok=True)

        sr_cfg = self._load_spatial_config(spatial_config_id)
        trust_cfg = TrustConfig.from_dict(self._m4_defaults)
        max_runtime = sr_cfg.execution.max_runtime_seconds
        t_start = time.time()

        self._write_status(run_dir, pair_id, SpatialRunState.RUNNING, proc_cfg, matcher_cfg, trust_cfg_id, spatial_config_id)

        proc_root = self._processing_root(pair_id)
        scene = load_scene_map(proc_root, match_dir, match_summary, sr_cfg.grid.edge_tolerance_px)
        if scene.get("status") != MappingStatus.MAPPED.value:
            self._write_status(
                run_dir, pair_id, SpatialRunState.BLOCKED, proc_cfg, matcher_cfg,
                trust_cfg_id, spatial_config_id,
                block_code=SpatialBlockCode.SPATIAL_MAPPING_UNAVAILABLE.value,
            )
            self._write_mapping(run_dir, scene)
            return self.read_status(pair_id)

        grid = Grid(sr_cfg.grid.rows, sr_cfg.grid.cols)
        tile_results: list[dict] = []
        verified_records: list[dict] = []
        cell_verified: dict[str, int] = {}
        cell_usable: dict[str, int] = {}
        cell_tiles: dict[str, set[str]] = {}
        side_a_verified: dict[str, int] = {}
        side_b_verified: dict[str, int] = {}
        side_a_usable: dict[str, int] = {}
        side_b_usable: dict[str, int] = {}
        mapping_by_tile = {m["match_tile_id"]: m for m in scene.get("mappings", [])}

        total_trusted = len(trusted_tiles)
        processed_tiles = 0
        recompute_failed = 0
        timeout_flagged = False
        usable_inliers = 0
        usable_candidates = 0

        for idx, tt in enumerate(trusted_tiles):
            if time.time() - t_start >= max_runtime:
                timeout_flagged = True
                break
            tile_id = str(tt.get("tile_id", ""))
            tile_inlier_mask = None
            cand_path = match_dir / "candidates" / f"{tile_id}.npz"
            try:
                cand = np.load(str(cand_path), allow_pickle=False)
                finite = (
                    np.isfinite(cand["x_a"]) & np.isfinite(cand["y_a"])
                    & np.isfinite(cand["x_b"]) & np.isfinite(cand["y_b"])
                )
                if not np.any(finite):
                    tile_results.append({"tile_id": tile_id, "state": "FAILED", "reason": "NO_FINITE_CANDIDATES"})
                    recompute_failed += 1
                    continue
                result = evaluate_tile(cand_path, trust_cfg, tile_id=tile_id)
                if result.model_result is None or result.model_result.inlier_mask is None:
                    tile_results.append({"tile_id": tile_id, "state": "FAILED", "reason": "INVALID_TRUST_ARTIFACT"})
                    recompute_failed += 1
                    continue
                tile_inlier_mask = np.asarray(result.model_result.inlier_mask, dtype=bool)
            except Exception:
                tile_results.append({"tile_id": tile_id, "state": "FAILED", "reason": "INVALID_TRUST_ARTIFACT"})
                recompute_failed += 1
                continue

            processed_tiles += 1
            m = mapping_by_tile.get(tile_id)
            idx_finite = np.where(finite)[0]
            xa_f = cand["x_a"][finite]
            ya_f = cand["y_a"][finite]
            xb_f = cand["x_b"][finite]
            yb_f = cand["y_b"][finite]

            nxa, nya, mapped_a, _ = self._map(side="a", mapping=m, scene=scene, dx=xa_f, dy=ya_f, tol=sr_cfg.grid.edge_tolerance_px)
            nxb, nyb, mapped_b, _ = self._map(side="b", mapping=m, scene=scene, dx=xb_f, dy=yb_f, tol=sr_cfg.grid.edge_tolerance_px)

            cells_usable_a = self._assign_cells(grid, nxa, nya, mapped_a)
            cells_usable_b = self._assign_cells(grid, nxb, nyb, mapped_b)
            for i, (ca, cb) in enumerate(zip(cells_usable_a, cells_usable_b)):
                usable_candidates += 1
                pair_cell = ca if ca else (cb if cb else "")
                if pair_cell:
                    self._inc(cell_usable, pair_cell)
                if ca:
                    self._inc(side_a_usable, ca)
                if cb:
                    self._inc(side_b_usable, cb)

            valid_pos = idx_finite[tile_inlier_mask]
            n = int(valid_pos.size)
            if n == 0:
                tile_results.append({"tile_id": tile_id, "state": "TRUSTED", "inliers": 0})
                continue
            used = set()
            cell_a_inlier = self._assign_cells(grid, nxa, nya, mapped_a)
            cell_b_inlier = self._assign_cells(grid, nxb, nyb, mapped_b)
            for j, orig_idx in enumerate(valid_pos.tolist()):
                ca = cell_a_inlier[j]
                cb = cell_b_inlier[j]
                scene_key = ca if ca else (cb if cb else "")
                scene_side = "a" if ca else ("b" if cb else "")
                if scene_key:
                    self._inc(cell_verified, scene_key)
                if ca:
                    self._inc(side_a_verified, ca)
                if cb:
                    self._inc(side_b_verified, cb)
                if scene_key:
                    cell_tiles.setdefault(scene_key, set()).add(tile_id)
                record = {
                    "tile_id": tile_id,
                    "cand_idx": orig_idx,
                    "cell_a": ca,
                    "cell_b": cb,
                    "scene_key": scene_key,
                    "scene_side": scene_side,
                    "x_a": float(cand["x_a"][orig_idx]),
                    "y_a": float(cand["y_a"][orig_idx]),
                    "x_b": float(cand["x_b"][orig_idx]),
                    "y_b": float(cand["y_b"][orig_idx]),
                    "nx_a": float(nxa[j]) if mapped_a[j] else None,
                    "ny_a": float(nya[j]) if mapped_a[j] else None,
                    "nx_b": float(nxb[j]) if mapped_b[j] else None,
                    "ny_b": float(nyb[j]) if mapped_b[j] else None,
                }
                verified_records.append(record)
                usable_inliers += 1
            tile_results.append({"tile_id": tile_id, "state": "TRUSTED", "inliers": n})

        if recompute_failed and processed_tiles == 0:
            self._write_status(
                run_dir, pair_id, SpatialRunState.FAILED, proc_cfg, matcher_cfg,
                trust_cfg_id, spatial_config_id,
                block_code=SpatialBlockCode.SPATIAL_INVALID_ARTIFACT.value,
            )
            self._write_summary(run_dir, pair_id, SpatialRunState.FAILED, proc_cfg, matcher_cfg, trust_cfg_id, spatial_config_id, {
                "error": "all trusted tile recomputation failed; trust artifacts inconsistent with M4",
            })
            return self.read_status(pair_id)

        result = compute_reliability(
            grid, sr_cfg,
            verified=cell_verified, usable=cell_usable, tiles=cell_tiles,
            side_a_verified=side_a_verified, side_a_usable=side_a_usable,
            side_b_verified=side_b_verified, side_b_usable=side_b_usable,
        )
        plan = plan_selection(grid, sr_cfg, result)

        if plan.selection_outcome == SELECTED:
            for cid in plan.selected_cell_ids:
                for c in result.cells:
                    if c.cell_id == cid:
                        c.selected = True
            for comp in result.components:
                if comp.component_id in plan.selected_component_ids:
                    comp.selected = True

        if verified_records:
            rows_keys: list[int] = []
            cols_keys: list[int] = []
            for r in verified_records:
                rc = grid.rc(r["scene_key"]) if r["scene_key"] else (0, 0)
                rows_keys.append(int(rc[0]))
                cols_keys.append(int(rc[1]))
            (primary, secondary, final_sel, capped) = assign_reasons(
                grid, sr_cfg, result, plan,
                cell_keys=[r["scene_key"] for r in verified_records],
                row_keys=rows_keys,
                col_keys=cols_keys,
                tile_ids=[r["tile_id"] for r in verified_records],
                candidate_indices=[int(r["cand_idx"]) for r in verified_records],
            )
        else:
            primary, secondary, final_sel, capped = [], [], [], False

        selected_count = int(np.sum(final_sel)) if final_sel else 0
        runtime = time.time() - t_start

        # write artifacts
        self._write_reliability_map(run_dir, grid, sr_cfg, result, plan)
        self._write_components(run_dir, grid, result, plan)
        self._write_cells(run_dir, grid, result, plan)
        self._write_selection(run_dir, grid, sr_cfg, result, plan, primary, secondary, final_sel, capped, selected_count)
        self._write_mapping(run_dir, scene)
        self._write_policies(run_dir, sr_cfg, trust_cfg_id, match_summary)
        if selected_count > 0:
            self._write_selected_npz(run_dir, verified_records, result, plan, final_sel, primary)

        state = SpatialRunState.FAILED if timeout_flagged else SpatialRunState.COMPLETE
        outcome = plan.selection_outcome
        summary = self._compose_summary(
            pair_id, run_dir, proc_cfg, matcher_cfg, trust_cfg_id, spatial_config_id,
            sr_cfg, result, plan, selected_count, runtime, trusted_tiles=total_trusted,
            processed_tiles=processed_tiles, recompute_failed=recompute_failed,
            timed_out=timeout_flagged, capped=capped, outcome=outcome,
            scene=scene, usable_candidates=usable_candidates, usable_inliers=usable_inliers,
        )
        self._write_summary(run_dir, pair_id, state, proc_cfg, matcher_cfg, trust_cfg_id, spatial_config_id, summary)
        if timeout_flagged:
            self._write_status(
                run_dir, pair_id, SpatialRunState.FAILED, proc_cfg, matcher_cfg,
                trust_cfg_id, spatial_config_id,
                block_code=SpatialBlockCode.SPATIAL_TIMEOUT.value,
                reasons=["SPATIAL_RUNTIME_TIMEOUT"],
            )
        else:
            self._write_status(run_dir, pair_id, state, proc_cfg, matcher_cfg, trust_cfg_id, spatial_config_id)
        self._write_manifest(run_dir, pair_id, sr_cfg, proc_cfg, matcher_cfg, trust_cfg_id, summary, spatial_config_id)
        return self.read_status(pair_id)

    # ---------- reset -------------------------------------------------------- #

    def reset(self, pair_id: str) -> dict:
        pair_spatial = self._spatial_root() / pair_id
        if pair_spatial.is_dir():
            shutil.rmtree(pair_spatial, ignore_errors=True)
        return self.read_status(pair_id)

    # ---------- internals ---------------------------------------------------- #

    def _map(self, *, side: str, mapping, scene, dx, dy, tol):
        return map_correspondences(scene, mapping, side, dx, dy, tol)

    def _assign_cells(self, grid, nx, ny, mapped):
        cell_ids = np.full(int(len(nx)), "", dtype=object)
        if np.any(mapped):
            rows, cols = grid.to_cell(nx[mapped], ny[mapped])
            cell_ids[mapped] = [
                grid.cell_id(int(ri), int(ci)) for ri, ci in zip(rows.tolist(), cols.tolist())
            ]
        return cell_ids

    def _load_spatial_config(self, spatial_config_id: str) -> SpatialReliabilityConfig:
        defaults = self._m5_cfg.get("defaults") or {}
        return SpatialReliabilityConfig.from_dict(defaults)

    def _read_json(self, path: Path, fallback):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return fallback

    def _write_json(self, path: Path, payload) -> None:
        atomic_write_json(path, payload)

    def _write_status(self, run_dir, pair_id, state, proc_cfg, matcher_cfg, trust_cfg, sr_cfg, block_code=None, reasons=None) -> None:
        status = {
            "pair_id": pair_id,
            "state": state.value,
            "coordinate_space": "pair_overlap_normalized",
            "processing_configuration_id": proc_cfg,
            "matcher_configuration_id": matcher_cfg,
            "trust_configuration_id": trust_cfg,
            "spatial_reliability_configuration_id": sr_cfg,
            "block_code": block_code,
            "reasons": reasons or [],
            "updated_at": rfc3339_now(),
        }
        self._write_json(run_dir / _SPATIAL_STATUS_FILENAME, status)

    def _synthetic_status(self, pair_id, state, block_code=None, reasons=None) -> dict:
        return {
            "pair_id": pair_id,
            "state": state.value,
            "coordinate_space": "pair_overlap_normalized",
            "processing_configuration_id": None,
            "matcher_configuration_id": None,
            "trust_configuration_id": None,
            "spatial_reliability_configuration_id": "SR-M5-001",
            "block_code": block_code,
            "reasons": reasons or [],
            "updated_at": rfc3339_now(),
        }

    def _inc(self, counter: dict, key: str) -> None:
        counter[key] = counter.get(key, 0) + 1

    def _write_reliability_map(self, run_dir, grid, sr_cfg, result, plan) -> None:
        legend = {
            "TYPE_NOT_APPLICABLE": "outer cell",
            "TYPE_NEEDS_TILES": "observed but below thresholds",
            "TYPE_CONFIRMED": "reliable",
            "TYPE_SELECTED": "reliable + selected for registration",
        }
        payload = {
            "grid": {"rows": grid.rows, "cols": grid.cols},
            "coordinate_space": "pair_overlap_normalized",
            "cells": [c.to_dict() for c in result.cells],
            "fragmentation": result.fragmentation,
            "boundary": result.boundary,
            "visualization": {
                "legend": legend,
                "grid": [
                    [{"cell_id": c.cell_id, "state": self._map_state(c)} for c in result.cells[r*grid.cols:(r+1)*grid.cols]]
                    for r in range(grid.rows)
                ],
                "selected_cell_ids": sorted(plan.selected_cell_ids),
            },
        }
        self._write_json(run_dir / "reliability_map.json", payload)

    def _map_state(self, c) -> str:
        if c.selected:
            return "TYPE_SELECTED"
        if c.reliable:
            return "TYPE_CONFIRMED"
        if c.observed:
            return "TYPE_NEEDS_TILES"
        return "TYPE_NOT_APPLICABLE"

    def _write_components(self, run_dir, grid, result, plan) -> None:
        payload = {
            "component_count": len(result.components),
            "components": [c.to_dict(grid) for c in result.components],
            "selected_component_ids": plan.selected_component_ids,
        }
        self._write_json(run_dir / "components.json", payload)

    def _write_cells(self, run_dir, grid, result, plan) -> None:
        payload = {
            "grid": {"rows": grid.rows, "cols": grid.cols},
            "cells": [c.to_dict() for c in result.cells],
        }
        self._write_json(run_dir / "cells.json", payload)

    def _write_selection(self, run_dir, grid, sr_cfg, result, plan, primary, secondary, final_sel, capped, selected_count) -> None:
        reason_counts: dict[str, int] = {}
        for code, subs, sel in zip(primary, secondary, final_sel):
            if sel:
                reason_counts[code] = reason_counts.get(code, 0) + 1
                for s in subs:
                    reason_counts[s] = reason_counts.get(s, 0) + 1
        payload = {
            "mode": sr_cfg.selection.mode,
            "selection_outcome": plan.selection_outcome,
            "decision_reason": plan.decision_reason,
            "selected_component_ids": plan.selected_component_ids,
            "selected_cell_ids": sorted(plan.selected_cell_ids),
            "selected_correspondence_count": selected_count,
            "capped_at_limit": capped,
            "limit": sr_cfg.selection.max_selected_correspondences,
            "reason_counts": reason_counts,
            "trace": plan.trace,
        }
        self._write_json(run_dir / "selection.json", payload)

    def _write_mapping(self, run_dir, scene) -> None:
        self._write_json(run_dir / "mapping.json", scene)

    def _write_policies(self, run_dir, sr_cfg, trust_cfg_id, match_summary) -> None:
        payload = {
            "spatial_reliability_configuration_id": sr_cfg.spatial_reliability_configuration_id,
            "spatial_reliability_configuration_version": sr_cfg.spatial_reliability_configuration_version,
            "coordinate_space": sr_cfg.coordinate_space,
            "grid": {
                "rows": sr_cfg.grid.rows, "cols": sr_cfg.grid.cols,
                "edge_tolerance_px": sr_cfg.grid.edge_tolerance_px,
            },
            "reliability": {
                "min_verified_inliers_per_cell": sr_cfg.reliability.min_verified_inliers_per_cell,
                "min_trusted_tiles_per_cell": sr_cfg.reliability.min_trusted_tiles_per_cell,
            },
            "neighborhood": {"support_radius_cells": sr_cfg.neighborhood.support_radius_cells},
            "fragmentation": {"enabled": sr_cfg.fragmentation.enabled},
            "boundary": {"edge_policy": sr_cfg.boundary.edge_policy},
            "connected_components": {"connectivity": sr_cfg.connected_components.connectivity},
            "selection": sr_cfg.selection_policy(),
            "execution": {"max_runtime_seconds": sr_cfg.execution.max_runtime_seconds},
            "source": {
                "matching_run": {
                    "processing_configuration_id": match_summary.get("processing_configuration_id"),
                    "matcher_configuration_id": match_summary.get("configuration_id"),
                },
                "trust_configuration_id": trust_cfg_id,
            },
        }
        self._write_json(run_dir / "policies" / "applied.json", payload)

    def _compose_summary(self, pair_id, run_dir, proc_cfg, matcher_cfg, trust_cfg, sr_cfg,
                        cfg, result, plan, selected_count, runtime, *, trusted_tiles,
                        processed_tiles, recompute_failed, timed_out, capped, outcome,
                        scene, usable_candidates, usable_inliers) -> dict:
        return {
            "pair_id": pair_id,
            "state": "COMPLETE",
            "coordinate_space": "pair_overlap_normalized",
            "processing_configuration_id": proc_cfg,
            "matcher_configuration_id": matcher_cfg,
            "trust_configuration_id": trust_cfg,
            "spatial_reliability_configuration_id": sr_cfg,
            "grid": {"rows": cfg.grid.rows, "cols": cfg.grid.cols},
            "tiles": {
                "trusted_tiles": trusted_tiles,
                "processed_tiles": processed_tiles,
                "recompute_failed": recompute_failed,
                "timed_out": timed_out,
            },
            "scene": {
                "mapped": 1 if scene.get("status") == MappingStatus.MAPPED.value else 0,
                "unmapped_match_tiles": sum(
                    1 for m in scene.get("mappings", [])
                    if m.get("status") != MappingStatus.MAPPED.value
                ),
                "usable_candidates_from_trusted_tiles": usable_candidates,
                "verified_inlier_count": usable_inliers,
            },
            "reliability": {
                "scene_cells_observed": sum(1 for c in result.cells if c.observed),
                "reliable_cells": len(result.reliable_cells),
                "supported_cells": len(result.supported_cells),
                "connected_components": len(result.components),
                "fragmentation": result.fragmentation,
                "boundary": result.boundary,
            },
            "selection": {
                "outcome": outcome,
                "selected_cells": len(plan.selected_cell_ids),
                "selected_correspondence_count": selected_count,
                "capped_at_limit": capped,
                "max_selected_correspondences": cfg.selection.max_selected_correspondences,
                "reason": plan.decision_reason,
            },
            "selection_outcome": outcome if outcome == INSUFFICIENT else "SELECTED",
            "runtime_seconds": round(runtime, 4),
            "generated_at": rfc3339_now(),
        }

    def _write_summary(self, run_dir, pair_id, state, proc_cfg, matcher_cfg, trust_cfg, sr_cfg, payload) -> None:
        payload = dict(payload)
        payload["state"] = state.value
        self._write_json(run_dir / "summary.json", payload)

    def _write_manifest(self, run_dir, pair_id, cfg, proc_cfg, matcher_cfg, trust_cfg, summary, sr_cfg) -> None:
        artifact_paths = [
            (run_dir / "summary.json", "summary"),
            (run_dir / "reliability_map.json", "reliability_map"),
            (run_dir / "components.json", "components"),
            (run_dir / "cells.json", "cells"),
            (run_dir / "selection.json", "selection"),
            (run_dir / "mapping.json", "mapping"),
            (run_dir / "policies" / "applied.json", "policies_applied"),
        ]
        if (run_dir / "selected_correspondences.npz").is_file():
            artifact_paths.append((run_dir / "selected_correspondences.npz", "selected_correspondences"))
        artifacts = [
            artifact_spec(p.relative_to(self._data).as_posix(), self._sha256(p), kind)
            for p, kind in artifact_paths
        ]
        manifest = build_spatial_manifest(
            pair_id=pair_id,
            spatial_config_id=cfg.spatial_reliability_configuration_id,
            spatial_config_version=cfg.spatial_reliability_configuration_version,
            coordinate_space=cfg.coordinate_space,
            proc_cfg=proc_cfg,
            matcher_cfg=matcher_cfg,
            trust_cfg=trust_cfg,
            summary=summary,
            artifacts=artifacts,
        )
        self._write_json(run_dir / "spatial_manifest.json", manifest)

    def _sha256(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _write_selected_npz(self, run_dir, records, result, plan, final_sel, primary) -> None:
        sel = [r for r, f in zip(records, final_sel) if f]
        cell_by_id = {c.cell_id: c for c in result.cells}
        comp_of: dict[str, str] = {}
        for comp in result.components:
            for cid in comp.cells:
                comp_of[cid] = comp.component_id
        if not sel:
            return
        n = len(sel)
        atomic_write_npz(
            run_dir / "selected_correspondences.npz",
            x_a=np.array([r["x_a"] for r in sel], dtype=np.float64),
            y_a=np.array([r["y_a"] for r in sel], dtype=np.float64),
            x_b=np.array([r["x_b"] for r in sel], dtype=np.float64),
            y_b=np.array([r["y_b"] for r in sel], dtype=np.float64),
            scene_x=np.array([(r["nx_a"] if r["nx_a"] is not None else r["nx_b"]) if r["scene_side"] else np.nan for r in sel], dtype=np.float64),
            scene_y=np.array([(r["ny_a"] if r["ny_a"] is not None else r["ny_b"]) if r["scene_side"] else np.nan for r in sel], dtype=np.float64),
            scene_side=np.array([r["scene_side"] for r in sel], dtype="U1"),
            source_tile_id=np.array([r["tile_id"] for r in sel], dtype="U64"),
            source_candidate_index=np.array([int(r["cand_idx"]) for r in sel], dtype=np.int64),
            side_a_cell_id=np.array([r["cell_a"] for r in sel], dtype="U16"),
            side_b_cell_id=np.array([r["cell_b"] for r in sel], dtype="U16"),
            component_id=np.array([comp_of.get(r["scene_key"], "") for r in sel], dtype="U16"),
            selection_reason=np.array([primary[i] for i, f in enumerate(final_sel) if f], dtype="U64"),
        )

    def reset_run(self, pair_id: str) -> dict:
        return self.reset(pair_id)