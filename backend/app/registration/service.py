"""M6 Registration Engine & Verified Alignment service.

Consumes M5 selected_correspondences.npz, fits a transform on sensor-pixel
evidence, validates it, warps the source crop to the target window and writes
a jury-ready registration workspace with full provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np

from backend.app.config import rfc3339_now
from backend.app.registration.config import RegistrationConfig
from backend.app.registration.coord_space import (
    build_tile_geometry_map,
    load_mapping_context,
    build_sensor_pixel_points,
)
from backend.app.registration.diagnostics import (
    diagnostics_to_dict,
    validation_to_dict,
)
from backend.app.registration.engine import fit_and_validate
from backend.app.registration.loader import load_selected_correspondences
from backend.app.registration.manifest import (
    artifact_spec,
    build_registration_manifest,
)
from backend.app.registration.provenance import build_provenance, sha256_of
from backend.app.registration.states import (
    RegistrationBlockCode,
    RegistrationRunState,
    RegistrationValidationVerdict,
)
from backend.app.registration.warp import WarpSpec, warp_tile
from backend.app.spatial.service import SpatialService

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_VALID_REGISTRATION_CONFIG_IDS = {"RG-M6-001"}

_SENSOR_LABELS = {"a": "sensor A", "b": "sensor B"}


def _f(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class RegistrationService:
    def __init__(
        self,
        data_root: Path,
        m6_cfg: dict | None = None,
        m5_cfg: dict | None = None,
        m4_defaults: dict | None = None,
    ):
        self._data = data_root
        self._m6_cfg = m6_cfg or {}
        self._m5_cfg = m5_cfg or {}
        self._m4_defaults = m4_defaults or {}
        self._derived_reg = self._m6_cfg.get("derived_rel", "derived/registration")

    # ---------- path discovery -------------------------------------------- #

    def _registration_root(self) -> Path:
        return self._data / self._derived_reg

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

    def _spatial_run_dir(self, pair_id: str) -> Path | None:
        spatial_svc = SpatialService(
            self._data, m5_cfg=self._m5_cfg, m4_defaults=self._m4_defaults)
        return spatial_svc.find_run_for_pair(pair_id)

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        pair_reg = self._registration_root() / pair_id
        if not pair_reg.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_reg.iterdir()):
            if not proc_dir.is_dir():
                continue
            for matcher_dir in sorted(proc_dir.iterdir()):
                if not matcher_dir.is_dir():
                    continue
                for trust_dir in sorted(matcher_dir.iterdir()):
                    if not trust_dir.is_dir():
                        continue
                    for spatial_dir in sorted(trust_dir.iterdir()):
                        if not spatial_dir.is_dir():
                            continue
                        for rg_dir in sorted(spatial_dir.iterdir()):
                            if rg_dir.is_dir():
                                deepest = rg_dir
        return deepest

    # ---------- public read API ------------------------------------------- #

    def read_status(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return self._synthetic_status(pair_id, RegistrationRunState.NOT_STARTED)
        status_path = run_dir / "status.json"
        if not status_path.is_file():
            return self._synthetic_status(pair_id, RegistrationRunState.NOT_STARTED)
        try:
            with open(status_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return self._synthetic_status(pair_id, RegistrationRunState.NOT_STARTED)

    def manifest(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "registration_manifest.json"
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

    def transform(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "transform.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def diagnostics(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "diagnostics.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def validation(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "validation.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def provenance(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "provenance.json"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def selected_evidence(self, pair_id: str) -> dict:
        try:
            spatial_svc = SpatialService(self._data, m5_cfg=self._m5_cfg, m4_defaults=self._m4_defaults)
            evidence = load_selected_correspondences(self._data, pair_id, spatial_svc)
        except Exception as exc:
            return {"error": str(exc).split(":", 1)[0], "pair_id": pair_id, "detail": str(exc)}
        return {
            "pair_id": pair_id,
            "n_correspondences": int(evidence.n_correspondences),
            "finite_usable": int(np.sum(
                np.isfinite(evidence.x_a) & np.isfinite(evidence.y_a)
                & np.isfinite(evidence.x_b) & np.isfinite(evidence.y_b))),
            "unique_tile_ids": list(evidence.unique_tile_ids),
            "unique_component_ids": list(evidence.unique_component_ids),
            "scene_sides_present": sorted(set(evidence.scene_side.tolist())),
            "source": "M5 selected_correspondences.npz",
            "m5_state": (evidence.m5_status or {}).get("state"),
            "note": "Evidence selected by M5; M6 does not recompute selection.",
        }

    # ---------- requirements ---------------------------------------------- #

    def prerequisites(self, pair_id: str) -> dict:
        spatial_run = self._spatial_run_dir(pair_id)
        if spatial_run is None:
            return {"ready": False, "block_code": RegistrationBlockCode.M5_NOT_AVAILABLE.value,
                    "reason": "No M5 spatial run exists for this pair — run SPATIAL first."}
        status_path = spatial_run / "status.json"
        if not status_path.is_file():
            return {"ready": False, "block_code": RegistrationBlockCode.M5_NOT_AVAILABLE.value,
                    "reason": "M5 spatial status.json missing."}
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ready": False, "block_code": RegistrationBlockCode.M5_NOT_AVAILABLE.value,
                    "reason": "M5 spatial status.json unreadable."}
        if status.get("state") != RegistrationRunState.COMPLETE.value:
            return {"ready": False, "block_code": RegistrationBlockCode.M5_NOT_COMPLETE.value,
                    "reason": f"M5 state is {status.get('state')}, expected COMPLETE.",
                    "m5_state": status.get("state")}
        sel_path = spatial_run / "selection.json"
        if not sel_path.is_file():
            return {"ready": False, "block_code": RegistrationBlockCode.NO_SELECTION.value,
                    "reason": "No M5 selection.json present."}
        try:
            sel = json.loads(sel_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ready": False, "block_code": RegistrationBlockCode.NO_SELECTION.value,
                    "reason": "M5 selection.json unreadable."}
        outcome = sel.get("selection_outcome") or sel.get("outcome")
        if outcome != "SELECTED":
            return {"ready": False, "block_code": RegistrationBlockCode.NO_SELECTION.value,
                    "reason": f"M5 selection outcome is {outcome}, expected SELECTED."}
        npz_path = spatial_run / "selected_correspondences.npz"
        if not npz_path.is_file():
            return {"ready": False, "block_code": RegistrationBlockCode.NO_SELECTION.value,
                    "reason": "No M5 selected_correspondences.npz present."}
        return {
            "ready": True,
            "block_code": None,
            "spatial_run_dir": spatial_run,
            "spatial_status": status,
            "selection": sel,
            "m5_summary": self._read_json(spatial_run / "summary.json", {}),
        }

    # ---------- run -------------------------------------------------------- #

    def run(self, pair_id: str, registration_config_id: str = "RG-M6-001") -> dict:
        if registration_config_id not in _VALID_REGISTRATION_CONFIG_IDS:
            return self._synthetic_status(pair_id, RegistrationRunState.BLOCKED,
                                          block_code=RegistrationBlockCode.UNKNOWN_CONFIG.value)
        prereq = self.prerequisites(pair_id)
        if not prereq["ready"]:
            return self._synthetic_status(pair_id, RegistrationRunState.BLOCKED,
                                          block_code=prereq["block_code"])

        spatial_run_dir = prereq["spatial_run_dir"]
        run_dir = self._discover_run_dir(pair_id, self._find_config_ids(spatial_run_dir), registration_config_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "registered").mkdir(exist_ok=True)
        (run_dir / "visualizations").mkdir(exist_ok=True)

        cfg = self._load_registration_config(registration_config_id)
        max_runtime = cfg.execution.max_runtime_seconds
        t_start = time.time()

        self._write_status(run_dir, pair_id, RegistrationRunState.RUNNING, cfg, prereq)

        try:
            spatial_svc = SpatialService(self._data, m5_cfg=self._m5_cfg, m4_defaults=self._m4_defaults)
            evidence = load_selected_correspondences(self._data, pair_id, spatial_svc)
        except Exception as exc:
            self._write_status(run_dir, pair_id, RegistrationRunState.BLOCKED, cfg, prereq,
                               block_code=str(exc).split(":", 1)[0])
            return self.read_status(pair_id)

        mapping = load_mapping_context(spatial_run_dir)
        if mapping is None or mapping.get("status") != "MAPPED":
            self._write_status(run_dir, pair_id, RegistrationRunState.BLOCKED, cfg, prereq,
                               block_code=RegistrationBlockCode.MAPPING_LOAD_FAILED.value)
            return self.read_status(pair_id)

        tile_geom_map = build_tile_geometry_map(mapping)
        px_a_x, px_a_y, px_b_x, px_b_y, valid_mask = build_sensor_pixel_points(
            evidence.x_a, evidence.y_a, evidence.x_b, evidence.y_b,
            evidence.source_tile_id, tile_geom_map,
        )
        n_valid = int(np.sum(valid_mask))
        if n_valid < 4:
            self._write_status(run_dir, pair_id, RegistrationRunState.INSUFFICIENT, cfg, prereq,
                               block_code=RegistrationBlockCode.INSUFFICIENT_EVIDENCE.value,
                               reasons=[f"Only {n_valid} valid sensor-pixel correspondences (< 4)."])
            self._write_summary(run_dir, pair_id, RegistrationRunState.INSUFFICIENT, cfg, prereq, {
                "error": "insufficient valid sensor-pixel correspondences",
            })
            self._write_diagnostics(run_dir, None, evidence, n_valid)
            return self.read_status(pair_id)

        result = fit_and_validate(
            px_a_x, px_a_y, px_b_x, px_b_y, valid_mask, cfg,
            t_start=t_start, max_runtime=float(max_runtime),
        )

        if result.transform_matrix is None:
            self._write_status(run_dir, pair_id, RegistrationRunState.FAILED, cfg, prereq,
                               reasons=[result.error or "TRANSFORM_FIT_FAILED"])
            self._write_summary(run_dir, pair_id, RegistrationRunState.FAILED, cfg, prereq, {
                "error": result.error,
            })
            self._write_diagnostics(run_dir, result, evidence, n_valid)
            self._write_validation(run_dir, result)
            self._write_transform(run_dir, result)
            return self.read_status(pair_id)

        verdict = result.validation.verdict.value
        if verdict != "PASS":
            self._write_status(run_dir, pair_id, RegistrationRunState.INSUFFICIENT, cfg, prereq,
                               reasons=result.validation.issues)
            self._write_summary(run_dir, pair_id, RegistrationRunState.INSUFFICIENT, cfg, prereq, {
                "validation_verdict": verdict,
                "issues": result.validation.issues,
            })
            self._write_diagnostics(run_dir, result, evidence, n_valid)
            self._write_validation(run_dir, result)
            self._write_transform(run_dir, result)
            return self.read_status(pair_id)

        warp_out = self._warp_evidence(mapping, evidence, result, run_dir, cfg)
        if warp_out is None or warp_out.get("error"):
            warp_reason = (warp_out or {}).get("error") or "WARP_FAILED"
            self._write_status(run_dir, pair_id, RegistrationRunState.FAILED, cfg, prereq,
                               reasons=[warp_reason])
            self._write_summary(run_dir, pair_id, RegistrationRunState.FAILED, cfg, prereq, {
                "error": f"warp failed: {warp_reason}",
            })
            self._write_diagnostics(run_dir, result, evidence, n_valid)
            self._write_validation(run_dir, result)
            self._write_transform(run_dir, result)
            return self.read_status(pair_id)

        runtime = time.time() - t_start
        self._write_diagnostics(run_dir, result, evidence, n_valid)
        self._write_validation(run_dir, result)
        self._write_transform(run_dir, result)
        self._write_registered(run_dir, warp_out, cfg)
        self._write_visualization(run_dir, warp_out, cfg)

        state = RegistrationRunState.COMPLETE
        summary = self._compose_summary(pair_id, run_dir, cfg, prereq, result, evidence,
                                        n_valid, runtime, warp_out)
        self._write_summary(run_dir, pair_id, state, cfg, prereq, summary)
        self._write_status(run_dir, pair_id, state, cfg, prereq)
        self._write_provenance(run_dir, pair_id, cfg, prereq, spatial_run_dir)
        self._write_manifest(run_dir, pair_id, cfg, prereq, spatial_run_dir, summary)
        return self.read_status(pair_id)

    # ---------- reset ------------------------------------------------------ #

    def reset(self, pair_id: str) -> dict:
        pair_reg = self._registration_root() / pair_id
        if pair_reg.is_dir():
            shutil.rmtree(pair_reg, ignore_errors=True)
        return self.read_status(pair_id)

    # ---------- internals -------------------------------------------------- #

    def _extract_pair_id(self, spatial_run_dir: Path) -> str:
        pair_reg = self._data / "derived" / "spatial"
        try:
            return spatial_run_dir.relative_to(pair_reg).parts[0]
        except (ValueError, IndexError):
            return ""

    def _find_config_ids(self, spatial_run_dir: Path) -> dict:
        status = self._read_json(spatial_run_dir / "status.json", {})
        return {
            "proc_cfg": str(status.get("processing_configuration_id", "PC-M2-001")),
            "matcher_cfg": str(status.get("matcher_configuration_id", "MC-M3-001")),
            "trust_cfg": str(status.get("trust_configuration_id", "TG-M4-001")),
            "spatial_cfg": str(status.get("spatial_reliability_configuration_id", "SR-M5-001")),
        }

    def _discover_run_dir(self, pair_id: str, ids: dict, registration_config_id: str) -> Path:
        return (self._registration_root() / pair_id / ids["proc_cfg"] / ids["matcher_cfg"]
                / ids["trust_cfg"] / ids["spatial_cfg"] / registration_config_id)

    def _load_registration_config(self, config_id: str) -> RegistrationConfig:
        defaults = self._m6_cfg.get("defaults") or {}
        return RegistrationConfig.from_dict(defaults)

    def _warp_evidence(self, mapping, evidence, result, run_dir, cfg) -> dict | None:
        tile_geom_map = build_tile_geometry_map(mapping)
        # pick the tile that contributes the most selected correspondences
        counts = Counter(evidence.source_tile_id.tolist())
        if not counts:
            return None
        best_tile = counts.most_common(1)[0][0]
        geom = tile_geom_map.get(best_tile)
        if geom is None or geom["a"] is None or geom["b"] is None:
            return None

        proc_root = self._processing_root(evidence.pair_id)
        if proc_root is None:
            return None
        tiles_json = self._read_tiles_json(proc_root)
        src_tile = self._find_tile_by_id(tiles_json, geom["a"].tile_id)
        dst_tile = self._find_tile_by_id(tiles_json, geom["b"].tile_id)
        if src_tile is None or dst_tile is None:
            return None

        if cfg.warp.max_output_rows > 0 and int(dst_tile.get("height", 0)) > cfg.warp.max_output_rows:
            return {"error": "OUTPUT_BOUNDS_INVALID: target rows "
                             f"{dst_tile.get('height')} > max_output_rows {cfg.warp.max_output_rows}"}
        if cfg.warp.max_output_cols > 0 and int(dst_tile.get("width", 0)) > cfg.warp.max_output_cols:
            return {"error": "OUTPUT_BOUNDS_INVALID: target cols "
                             f"{dst_tile.get('width')} > max_output_cols {cfg.warp.max_output_cols}"}

        src_array_path = proc_root / "crops" / src_tile.get("array_filename", "")
        if not src_array_path.is_file():
            return None
        arr = np.load(str(src_array_path), allow_pickle=False)
        if arr.ndim != 2:
            return None

        dst_array = None
        dst_array_path = proc_root / "crops" / dst_tile.get("array_filename", "")
        if dst_array_path.is_file():
            try:
                dst_array = np.load(str(dst_array_path), allow_pickle=False)
            except Exception:  # pragma: no cover - visualization is best effort
                dst_array = None

        spec = WarpSpec(
            src_array=arr,
            src_row_start=geom["a"].row_start,
            src_col_start=geom["a"].col_start,
            out_rows=int(dst_tile.get("height", 0)),
            out_cols=int(dst_tile.get("width", 0)),
            out_row_start=geom["b"].row_start,
            out_col_start=geom["b"].col_start,
        )
        product = warp_tile(spec, result.transform_matrix, result.transform_type.value.lower(),
                            fill_value=cfg.warp.fill_value)
        if product.warped.size == 0:
            return None
        warped = self._apply_warp_dtype(np.asarray(product.warped), cfg.warp.dtype)
        np.save(str(run_dir / "registered" / "registered_image.npy"), warped)
        np.save(str(run_dir / "registered" / "valid_mask.npy"), product.valid_mask)

        tile_mask = np.asarray(evidence.source_tile_id) == best_tile
        pts_a_local = np.column_stack([
            np.asarray(evidence.x_a)[tile_mask].astype(np.float64),
            np.asarray(evidence.y_a)[tile_mask].astype(np.float64),
        ])
        pts_b_local = np.column_stack([
            np.asarray(evidence.x_b)[tile_mask].astype(np.float64),
            np.asarray(evidence.y_b)[tile_mask].astype(np.float64),
        ])
        return {
            "warped": warped,
            "valid_mask": product.valid_mask,
            "source_tile_id": best_tile,
            "source_crop": src_tile.get("tile_id"),
            "target_crop": dst_tile.get("tile_id"),
            "src_row_start": geom["a"].row_start,
            "src_col_start": geom["a"].col_start,
            "out_rows": spec.out_rows,
            "out_cols": spec.out_cols,
            "matrix_type": product.matrix_type,
            "src_array": np.asarray(arr),
            "dst_array": dst_array,
            "pts_a_local": pts_a_local,
            "pts_b_local": pts_b_local,
        }

    @staticmethod
    def _apply_warp_dtype(arr: np.ndarray, dtype_name: str) -> np.ndarray:
        try:
            dtype = np.dtype(dtype_name)
        except (TypeError, ValueError):
            return arr
        if dtype.kind in "ui":
            info = np.iinfo(dtype)
            return np.clip(np.round(arr), float(info.min), float(info.max)).astype(dtype)
        return arr.astype(dtype) if dtype.kind in "fc" else arr

    def _read_tiles_json(self, proc_root: Path) -> dict:
        paths = [
            proc_root / "crops" / "tiles.json",
            proc_root / "diagnostics" / "tiles.json",
        ]
        for p in paths:
            if p.is_file():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
        return {}

    def _find_tile_by_id(self, tiles_json: dict, tile_id: str) -> dict | None:
        for t in tiles_json.get("tiles", []):
            if t.get("tile_id") == tile_id:
                return t
        return None

    def _synthetic_status(self, pair_id, state, block_code=None, reasons=None) -> dict:
        return {
            "pair_id": pair_id,
            "state": state.value,
            "registration_configuration_id": "RG-M6-001",
            "block_code": block_code,
            "reasons": reasons or [],
            "updated_at": rfc3339_now(),
        }

    def _read_json(self, path: Path, fallback):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return fallback

    def _write_json(self, path: Path, payload) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _write_status(self, run_dir, pair_id, state, cfg, prereq, block_code=None, reasons=None) -> None:
        status = {
            "pair_id": pair_id,
            "state": state.value,
            "processing_configuration_id": (prereq.get("spatial_status") or {}).get("processing_configuration_id", "PC-M2-001"),
            "matcher_configuration_id": (prereq.get("spatial_status") or {}).get("matcher_configuration_id", "MC-M3-001"),
            "trust_configuration_id": (prereq.get("spatial_status") or {}).get("trust_configuration_id", "TG-M4-001"),
            "spatial_reliability_configuration_id": (prereq.get("spatial_status") or {}).get("spatial_reliability_configuration_id", "SR-M5-001"),
            "registration_configuration_id": cfg.registration_configuration_id,
            "registration_configuration_version": cfg.registration_configuration_version,
            "block_code": block_code,
            "reasons": reasons or [],
            "scientific_note": "No claim of physical truth; diagnostics are measurements.",
            "updated_at": rfc3339_now(),
        }
        self._write_json(run_dir / "status.json", status)

    def _compose_summary(self, pair_id, run_dir, cfg, prereq, result, evidence, n_valid, runtime, warp_out) -> dict:
        return {
            "pair_id": pair_id,
            "state": RegistrationRunState.COMPLETE.value,
            "registration_configuration_id": cfg.registration_configuration_id,
            "transform_type": result.transform_type.value,
            "selection_reason": result.selection_reason.value,
            "validation_verdict": result.validation.verdict.value,
            "source_space": {
                "sensor": "a",
                "frame": "sensor_a_pixel",
                "units": "pixel",
            },
            "target_space": {
                "sensor": "b",
                "frame": "sensor_b_pixel",
                "units": "pixel",
            },
            "direction": "sensor_a_pixel -> sensor_b_pixel",
            "correspondences": {
                "selected_total": int(evidence.n_correspondences),
                "finite_usable": n_valid,
                "fit_used": result.transform_diagnostics.total_correspondences,
                "inliers": result.transform_diagnostics.inlier_count,
                "outlier": result.transform_diagnostics.outlier_count,
            },
            "warp": {
                "source_tile_id": warp_out["source_tile_id"],
                "registered_shown": True,
                "out_rows": warp_out["out_rows"],
                "out_cols": warp_out["out_cols"],
            },
            "runtime_seconds": round(runtime, 4),
            "generated_at": rfc3339_now(),
        }

    def _write_summary(self, run_dir, pair_id, state, cfg, prereq, payload) -> None:
        payload = dict(payload)
        payload["state"] = state.value
        if not payload.get("generated_at"):
            payload["generated_at"] = rfc3339_now()
        self._write_json(run_dir / "summary.json", payload)

    def _write_diagnostics(self, run_dir, result, evidence, n_valid) -> None:
        if result is None:
            payload = {
                "transform_type": None,
                "correspondences": {
                    "selected_total": int(evidence.n_correspondences),
                    "finite_usable": n_valid,
                },
                "error": "No transform computed.",
            }
        else:
            payload = diagnostics_to_dict(result, n_valid, evidence.n_correspondences)
        self._write_json(run_dir / "diagnostics.json", payload)

    def _write_validation(self, run_dir, result) -> None:
        payload = validation_to_dict(result)
        try:
            from backend.app.registration.diagnostics import build_independent_check
            payload["independent_check"] = build_independent_check(result)
        except Exception:  # pragma: no cover - best effort, never break the run
            payload["independent_check"] = {
                "recomputed": False,
                "status": "ERROR",
                "reason": "independent recomputation could not run",
            }
        payload["state"] = (
            "VALIDATED" if payload.get("verdict") == RegistrationValidationVerdict.PASS.value
            else "FAILED_VALIDATION"
        )
        self._write_json(run_dir / "validation.json", payload)

    def _write_transform(self, run_dir, result) -> None:
        m = result.transform_matrix
        payload = {
            "transform_type": result.transform_type.value,
            "matrix_type": result.transform_diagnostics.matrix_type,
            "matrix": None if m is None else [
                [float(v10) for v10 in row] for row in m.tolist()
            ],
            "source_space": {
                "sensor": "a",
                "side": "a",
                "frame": "sensor_a_pixel",
                "units": "pixel",
                "description": "OHRC/TMC-2 sensor A pixel coordinates of the selected tile region.",
            },
            "target_space": {
                "sensor": "b",
                "side": "b",
                "frame": "sensor_b_pixel",
                "units": "pixel",
                "description": "OHRC/TMC-2 sensor B pixel coordinates of the selected tile region.",
            },
            "direction": "sensor_a_pixel -> sensor_b_pixel",
            "inlier_count": result.transform_diagnostics.inlier_count,
            "inlier_ratio": round(result.transform_diagnostics.inlier_ratio, 6),
            "seed_used": result.transform_diagnostics.seed_used,
            "note": "Transform fit on M5-selected evidence in sensor pixel space.",
        }
        self._write_json(run_dir / "transform.json", payload)

    def _write_registered(self, run_dir, warp_out, cfg) -> None:
        arr = np.asarray(warp_out["warped"])
        low = float(np.nanmin(arr)) if arr.size else 0.0
        high = float(np.nanmax(arr)) if arr.size else 1.0
        if high - low < 1e-9:
            high = low + 1.0
        preview = ((arr.astype(np.float64) - low) / (high - low) * 255.0).astype(np.uint8)
        try:
            from PIL import Image
            Image.fromarray(preview, mode="L").save(
                str(run_dir / "registered" / "registered_image.png"), format="PNG")
        except Exception:  # pragma: no cover - preview is best effort
            pass
        meta = {
            "source_crop_tile_id": warp_out.get("source_crop"),
            "target_crop_tile_id": warp_out.get("target_crop"),
            "out_rows": warp_out["out_rows"],
            "out_cols": warp_out["out_cols"],
            "dtype": str(arr.dtype),
            "fill_value": cfg.warp.fill_value,
            "valid_pixel_fraction": round(
                float(np.mean(warp_out["valid_mask"])), 6) if warp_out["valid_mask"].size else 0.0,
            "note": "Registered output is a warped source crop; diagnostics are not proof.",
        }
        self._write_json(run_dir / "registered" / "registered_meta.json", meta)

    def _write_visualization(self, run_dir, warp_out, cfg) -> None:
        arr = np.asarray(warp_out["warped"])
        self._write_normalized_png(arr, run_dir / "visualizations" / "registered_overlay.png")
        try:
            from backend.app.registration.visualize import (
                build_correspondence_overlay,
                build_difference_overlay,
                build_footprint_overlay,
                build_side_by_side,
            )
            src_arr = warp_out.get("src_array")
            dst_arr = warp_out.get("dst_array")
            base_path = run_dir / "visualizations"
            if dst_arr is not None and dst_arr.size:
                build_side_by_side(
                    src_arr, np.asarray(dst_arr), arr,
                    src_name="Source A", dst_name="Source B", reg_name="Registered",
                    out_path=base_path / "before_after.png",
                    normalization=cfg.warp.visualization_normalization,
                )
                build_difference_overlay(
                    np.asarray(dst_arr), arr,
                    out_path=base_path / "difference_overlay.png",
                    normalization=cfg.warp.visualization_normalization,
                )
            build_correspondence_overlay(
                src_arr, warp_out.get("pts_a_local"), warp_out.get("pts_b_local"),
                out_path=base_path / "correspondences.png",
                normalization=cfg.warp.visualization_normalization,
            )
            build_footprint_overlay(
                src_arr, np.asarray(dst_arr) if dst_arr is not None and dst_arr.size else None,
                warp_out.get("pts_a_local"), warp_out.get("pts_b_local"),
                out_path=base_path / "footprint.png",
                normalization=cfg.warp.visualization_normalization,
            )
        except Exception:  # pragma: no cover - visualization is best effort
            pass

    @staticmethod
    def _write_normalized_png(arr, out_path: Path) -> None:
        if arr.size == 0:
            return
        low = float(np.nanmin(arr)) if arr.size else 0.0
        high = float(np.nanmax(arr)) if arr.size else 1.0
        if high - low < 1e-9:
            high = low + 1.0
        preview = ((arr.astype(np.float64) - low) / (high - low) * 255.0).astype(np.uint8)
        try:
            from PIL import Image
            Image.fromarray(preview, mode="L").save(str(out_path), format="PNG")
        except Exception:  # pragma: no cover
            pass

    def _write_manifest(self, run_dir, pair_id, cfg, prereq, spatial_run_dir, summary) -> None:
        artifact_paths = [
            (run_dir / "summary.json", "summary"),
            (run_dir / "transform.json", "transform"),
            (run_dir / "diagnostics.json", "diagnostics"),
            (run_dir / "validation.json", "validation"),
            (run_dir / "provenance.json", "provenance"),
            (run_dir / "status.json", "status"),
        ]
        reg_dir = run_dir / "registered"
        if (reg_dir / "registered_image.npy").is_file():
            artifact_paths.append((reg_dir / "registered_image.npy", "registered_image"))
        if (reg_dir / "valid_mask.npy").is_file():
            artifact_paths.append((reg_dir / "valid_mask.npy", "valid_mask"))
        if (reg_dir / "registered_meta.json").is_file():
            artifact_paths.append((reg_dir / "registered_meta.json", "registered_meta"))
        visual_path = run_dir / "visualizations" / "registered_overlay.png"
        if visual_path.is_file():
            artifact_paths.append((visual_path, "registered_overlay"))

        artifacts = [
            artifact_spec(p.relative_to(self._data).as_posix(), self._sha256(p), kind)
            for p, kind in artifact_paths
        ]
        manifest = build_registration_manifest(
            pair_id=pair_id,
            registration_config_id=cfg.registration_configuration_id,
            registration_config_version=cfg.registration_configuration_version,
            proc_cfg=(prereq.get("spatial_status") or {}).get("processing_configuration_id", "PC-M2-001"),
            matcher_cfg=(prereq.get("spatial_status") or {}).get("matcher_configuration_id", "MC-M3-001"),
            trust_cfg=(prereq.get("spatial_status") or {}).get("trust_configuration_id", "TG-M4-001"),
            spatial_cfg=(prereq.get("spatial_status") or {}).get("spatial_reliability_configuration_id", "SR-M5-001"),
            summary=summary,
            artifacts=artifacts,
            scientific_note="No claim of physical truth; diagnostics are measurements.",
        )
        self._write_json(run_dir / "registration_manifest.json", manifest)

    def _write_provenance(self, run_dir, pair_id, cfg, prereq, spatial_run_dir) -> None:
        m2 = self._processing_root(pair_id)
        m3 = self._match_run_dir(pair_id)
        m4 = self._trust_run_dir(pair_id)
        m5 = spatial_run_dir
        prov = build_provenance(
            pair_id, self._data,
            m2_run_dir=m2, m3_run_dir=m3, m4_run_dir=m4, m5_run_dir=m5,
            m6_run_dir=run_dir,
            m6_status=self.read_status(pair_id),
        )
        self._write_json(run_dir / "provenance.json", prov)

    def _sha256(self, path: Path) -> str:
        return sha256_of(path)

    def reset_run(self, pair_id: str) -> dict:
        return self.reset(pair_id)