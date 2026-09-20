from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path

import numpy as np

from backend.app.config import rfc3339_now
from backend.app.hardening import atomic_write_json, atomic_write_npz
from backend.app.trust.config import TrustConfig
from backend.app.trust.engine import evaluate_tile, tile_to_dict
from backend.app.trust.manifest import build_trust_manifest
from backend.app.trust.states import (
    TrustBlockCode,
    TrustGateState,
    TileTrustState,
    TrustReasonCode,
)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


_VALID_TRUST_CONFIG_IDS = {"TG-M4-001"}


class TrustService:
    def __init__(self, data_root: Path, m4_cfg: dict | None = None):
        self._data = data_root
        self._m4_cfg = m4_cfg or {}
        self._derived_rel = self._m4_cfg.get("derived_rel", "derived/trust")

    def _trust_root(self) -> Path:
        return self._data / self._derived_rel

    def _match_run_dir(self, pair_id: str) -> Path | None:
        """Locate the deepest MATCH run dir for pair (M3 layout:
        derived/matches/<pair>/<proc_cfg>/<matcher_cfg>/)."""
        pair_match = self._data / "derived" / "matches" / pair_id
        if not pair_match.is_dir():
            return None
        deepest = None
        for proc_dir in sorted(pair_match.iterdir()):
            if not proc_dir.is_dir():
                continue
            for matcher_dir in sorted(proc_dir.iterdir()):
                if not matcher_dir.is_dir():
                    continue
                if matcher_dir.name == "m8":
                    # M8 deep-matcher expansion runs must NOT be interpreted as
                    # an M3 matcher run by the M4 trust gate.
                    continue
                deepest = matcher_dir
        if deepest is not None and (deepest / "summary.json").is_file():
            return deepest
        return None

    def prerequisites(self, pair_id: str) -> dict:
        match_dir = self._match_run_dir(pair_id)
        if match_dir is None:
            return {
                "ready": False,
                "block_code": TrustBlockCode.MATCHING_NOT_AVAILABLE.value,
                "reasons": [TrustReasonCode.TG_NOT_RUN.value],
            }
        summary_path = match_dir / "summary.json"
        try:
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {
                "ready": False,
                "block_code": TrustBlockCode.MATCHING_NOT_AVAILABLE.value,
                "reasons": [TrustReasonCode.TG_NOT_RUN.value],
            }
        total_candidates = 0
        for tile in summary.get("per_tile", []):
            total_candidates += int(tile.get("candidates", 0) or 0)
        if total_candidates == 0:
            return {
                "ready": False,
                "block_code": TrustBlockCode.NO_CANDIDATE_ARTIFACT.value,
                "reasons": [TrustReasonCode.TG_BLOCK_NO_CANDIDATES.value],
            }
        return {"ready": True, "block_code": None, "reasons": []}

    def find_run_for_pair(self, pair_id: str) -> Path | None:
        pair_trust = self._trust_root() / pair_id
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
        return deepest

    def read_status(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return self._synthetic_status(pair_id, TrustGateState.NOT_STARTED)
        status_path = run_dir / "trust_status.json"
        if not status_path.is_file():
            return self._synthetic_status(pair_id, TrustGateState.NOT_STARTED)
        try:
            with open(status_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return self._synthetic_status(pair_id, TrustGateState.NOT_STARTED)

    def run(self, pair_id: str, trust_config_id: str = "TG-M4-001") -> dict:
        if trust_config_id not in _VALID_TRUST_CONFIG_IDS:
            return self._synthetic_status(
                pair_id, TrustGateState.BLOCKED,
                block_code=TrustBlockCode.TRUST_UNKNOWN_CONFIG.value,
                reasons=[TrustReasonCode.TG_NOT_RUN.value],
            )
        prereq = self.prerequisites(pair_id)
        if not prereq["ready"]:
            return self._synthetic_status(
                pair_id, TrustGateState.BLOCKED,
                block_code=prereq["block_code"], reasons=prereq["reasons"],
            )
        match_dir = self._match_run_dir(pair_id)
        if match_dir is None:
            return self._synthetic_status(
                pair_id, TrustGateState.BLOCKED,
                block_code=TrustBlockCode.MATCHING_NOT_AVAILABLE.value,
                reasons=[TrustReasonCode.TG_NOT_RUN.value],
            )
        with open(match_dir / "summary.json", encoding="utf-8") as f:
            match_summary = json.load(f)
        proc_cfg = match_summary.get("processing_configuration_id", "PC-M2-001")
        matcher_cfg = match_summary.get("configuration_id", "MC-M3-001")
        trust_run = self._trust_root() / pair_id / proc_cfg / matcher_cfg / trust_config_id
        trust_run.mkdir(parents=True, exist_ok=True)
        tiles_dir = trust_run / "tiles"
        tiles_dir.mkdir(exist_ok=True)
        self._write_status(pair_id, trust_run, TrustGateState.RUNNING, proc_cfg, matcher_cfg, trust_config_id)
        trust_cfg = self._load_trust_config(trust_config_id)
        max_runtime = trust_cfg.execution.max_runtime_seconds
        t_start = time.time()
        tiles_processed = 0
        trusted_tiles = 0
        rejected_tiles = 0
        failed_tiles = 0
        reason_counts: dict[str, int] = {}
        tile_results: list[dict] = []
        match_tiles = [t for t in match_summary.get("per_tile", [])
                       if t.get("outcome") == "SUCCESS" and int(t.get("candidates", 0) or 0) > 0]
        all_xa: list[np.ndarray] = []
        all_ya: list[np.ndarray] = []
        all_xb: list[np.ndarray] = []
        all_yb: list[np.ndarray] = []
        for mt in match_tiles:
            elapsed = time.time() - t_start
            if elapsed >= max_runtime:
                for remaining in match_tiles[tiles_processed:]:
                    tid = remaining.get("match_tile_id", "")
                    tile_results.append({
                        "tile_id": tid,
                        "trust_state": TileTrustState.FAILED.value,
                        "reasons": [TrustReasonCode.TG_NOT_RUN.value],
                        "block_code": "TIMEOUT",
                    })
                    failed_tiles += 1
                break
            tile_id = mt.get("match_tile_id", "")
            cand_path = match_dir / "candidates" / f"{tile_id}.npz"
            if not cand_path.is_file():
                tile_results.append({
                    "tile_id": tile_id,
                    "trust_state": TileTrustState.FAILED.value,
                    "reasons": [TrustReasonCode.TG_NOT_RUN.value],
                    "block_code": "NO_CANDIDATE_ARTIFACT",
                })
                failed_tiles += 1
                continue
            result = evaluate_tile(cand_path, trust_cfg, tile_id=tile_id)
            tiles_processed += 1
            tile_dict = tile_to_dict(result)
            tile_results.append(tile_dict)
            tile_out = tiles_dir / f"{tile_id}.json"
            atomic_write_json(tile_out, tile_dict)
            for r in result.reasons:
                reason_counts[r] = reason_counts.get(r, 0) + 1
            if result.trust_state == TileTrustState.TRUSTED:
                trusted_tiles += 1
                if result.model_result and result.model_result.inlier_mask is not None:
                    cand_data = np.load(str(cand_path), allow_pickle=False)
                    finite_mask = (
                        np.isfinite(cand_data["x_a"]) & np.isfinite(cand_data["y_a"])
                        & np.isfinite(cand_data["x_b"]) & np.isfinite(cand_data["y_b"])
                    )
                    inlier_mask = result.model_result.inlier_mask
                    idx_finite = np.where(finite_mask)[0]
                    idx_inlier = idx_finite[inlier_mask]
                    all_xa.append(cand_data["x_a"][idx_inlier])
                    all_ya.append(cand_data["y_a"][idx_inlier])
                    all_xb.append(cand_data["x_b"][idx_inlier])
                    all_yb.append(cand_data["y_b"][idx_inlier])
            elif result.trust_state == TileTrustState.REJECTED:
                rejected_tiles += 1
            else:
                failed_tiles += 1
        total_runtime = time.time() - t_start
        timed_out = any(((isinstance(t.get("block_code"), str) and t.get("block_code") == "TIMEOUT"))
                        for t in tile_results)
        gate_state = TrustGateState.COMPLETE if trusted_tiles > 0 else TrustGateState.FAILED
        if timed_out:
            gate_state = TrustGateState.FAILED
        self._write_status(pair_id, trust_run, gate_state, proc_cfg, matcher_cfg, trust_config_id,
                           block_code="TIMEOUT" if timed_out else None,
                           reasons=[TrustReasonCode.TG_NOT_RUN.value] if timed_out else None)
        if all_xa:
            atomic_write_npz(
                trust_run / "trusted_correspondences.npz",
                x_a=np.concatenate(all_xa),
                y_a=np.concatenate(all_ya),
                x_b=np.concatenate(all_xb),
                y_b=np.concatenate(all_yb),
            )
        manifest = build_trust_manifest(
            pair_id=pair_id,
            trust_config_id=trust_config_id,
            trust_config_version=trust_cfg.trust_configuration_version,
            proc_cfg=proc_cfg,
            matcher_cfg=matcher_cfg,
            tiles_processed=tiles_processed,
            trusted_tiles=trusted_tiles,
            rejected_tiles=rejected_tiles,
            total_runtime=total_runtime,
            reason_counts=reason_counts,
        )
        atomic_write_json(trust_run / "trust_manifest.json", manifest)
        summary = {
            "pair_id": pair_id,
            "trust_configuration_id": trust_config_id,
            "processing_configuration_id": proc_cfg,
            "matcher_configuration_id": matcher_cfg,
            "gate_state": gate_state.value,
            "tiles_processed": tiles_processed,
            "trusted_tiles": trusted_tiles,
            "rejected_tiles": rejected_tiles,
            "failed_tiles": failed_tiles,
            "total_runtime_seconds": round(total_runtime, 4),
            "reason_distribution": reason_counts,
            "timed_out": timed_out,
            "generated_at": rfc3339_now(),
        }
        atomic_write_json(trust_run / "summary.json", summary)
        tile_trust_index = {
            "pair_id": pair_id,
            "trust_configuration_id": trust_config_id,
            "tiles": tile_results,
        }
        atomic_write_json(trust_run / "tile_trust.json", tile_trust_index)
        return self.read_status(pair_id)

    def reset(self, pair_id: str) -> dict:
        pair_trust = self._trust_root() / pair_id
        if pair_trust.is_dir():
            shutil.rmtree(pair_trust, ignore_errors=True)
        return self.read_status(pair_id)

    def tile_trust(self, pair_id: str, tile_id: str) -> dict:
        if not tile_id or not _SAFE_ID.match(tile_id):
            return {"error": "INVALID_TILE_ID", "pair_id": pair_id, "tile_id": tile_id}
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id, "tile_id": tile_id}
        tile_path = run_dir / "tiles" / f"{tile_id}.json"
        if not tile_path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id, "tile_id": tile_id}
        with open(tile_path, encoding="utf-8") as f:
            return json.load(f)

    def manifest(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "trust_manifest.json"
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

    def trusted_correspondences(self, pair_id: str) -> dict:
        run_dir = self.find_run_for_pair(pair_id)
        if run_dir is None:
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        path = run_dir / "trusted_correspondences.npz"
        if not path.is_file():
            return {"error": "NOT_FOUND", "pair_id": pair_id}
        data = np.load(str(path), allow_pickle=False)
        result: dict = {"pair_id": pair_id, "fields": list(data.files)}
        for k in data.files:
            result[f"{k}_count"] = int(len(data[k]))
        return result

    def _load_trust_config(self, trust_config_id: str) -> TrustConfig:
        defaults = (self._m4_cfg.get("defaults") or {})
        if trust_config_id == "TG-M4-001":
            return TrustConfig.from_dict(defaults)
        return TrustConfig.from_dict(defaults)

    def _write_status(
        self, pair_id: str, run_dir: Path, state: TrustGateState,
        proc_cfg: str, matcher_cfg: str, trust_cfg_id: str,
        block_code: str | None = None, reasons: list[str] | None = None,
    ) -> None:
        status = {
            "pair_id": pair_id,
            "gate_state": state.value,
            "processing_configuration_id": proc_cfg,
            "matcher_configuration_id": matcher_cfg,
            "trust_configuration_id": trust_cfg_id,
            "block_code": block_code,
            "reasons": reasons or [],
            "updated_at": rfc3339_now(),
        }
        atomic_write_json(run_dir / "trust_status.json", status)

    def _synthetic_status(
        self, pair_id: str, state: TrustGateState,
        block_code: str | None = None, reasons: list[str] | None = None,
    ) -> dict:
        return {
            "pair_id": pair_id,
            "gate_state": state.value,
            "processing_configuration_id": None,
            "matcher_configuration_id": None,
            "trust_configuration_id": "TG-M4-001",
            "block_code": block_code,
            "reasons": reasons or [TrustReasonCode.TG_NOT_RUN.value],
            "updated_at": rfc3339_now(),
        }
