"""M7 TRUST GATE — service (run, read, list, status, artifact persistence).

The M7 Trust Gate consumes ONE matcher run artifact (M3 baseline or M4 deep,
carried through M6 when the router dispatched it) and records a deterministic
geometric-verification decision as a never-overwritten artifact under
``data/metadata/m7_trust``.

Rules enforced here (not in the pure engine):
    * coordinate frame must be declared per side (effective matcher plane);
    * a REAL pair fed by an artifact that was synthetically derived is BLOCKED;
    * candidates that were never produced (non-SUCCESS run, empty list) are
      recorded as BLOCKED/CANDIDATES_MISSING, never silently fabricated;
    * provenance (routing mode / routing run / matcher run) is resolved and
      persisted.

No M8 spatial selection, no M9 registration semantics live here.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Settings, rfc3339_now
from ..errors import NotFoundError
from ..hardening import atomic_write_json
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..routing.service import RoutingService
from ..state import get_state
from . import states
from .config import TrustGateConfig, load_trust_gate_config
from .contract import (
    assert_artifact_vocabulary_safe,
    license_text,
)

logger = get_logger(__name__)

_STATUS_SUCCESS = "SUCCESS"

_TRUST_CHAIN = "M2 -> M3/M4 (-> M6 adaptivity) -> M7 trust gate"


def _safe_run_id(run_id: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id or ""))


def _synthetic_like(record) -> bool:
    ids = f"{record.source_class_a} {record.source_class_b}"
    if "FIXTURE" in ids.upper() or "fixture" in ids:
        return True
    if record.data_source_gate != "PATH_A_REAL_DATA":
        return True
    return False


def _environment_snapshot() -> dict[str, Any]:
    import cv2  # noqa: PLC0415
    import numpy  # noqa: PLC0415

    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "numpy_version": numpy.__version__,
        "opencv_version": cv2.__version__,
        "rng": "NUMPY_RANDOMSTATE_SEEDED",
        "rng_seed_policy": "explicit seed per model config; reproduced every run",
    }


def _configuration_dict(cfg: TrustGateConfig) -> dict[str, Any]:
    return json.loads(json.dumps(dataclasses.asdict(cfg)))


def _decision_hash(result: dict[str, Any]) -> str:
    blob = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _executed_matcher_run_id(routing_artifact: dict[str, Any] | None) -> str | None:
    """Resolve the matcher run id that a routing run actually dispatched."""
    if not isinstance(routing_artifact, dict):
        return None
    execution = routing_artifact.get("execution") or {}
    runs = execution.get("runs") or {}
    final_route = execution.get("final_route")
    candidates: list[str] = []
    if final_route and isinstance(runs.get(final_route), dict):
        candidates.append(str(runs[final_route].get("run_id") or ""))
    for value in runs.values():
        if isinstance(value, dict) and value.get("run_id"):
            candidates.append(str(value["run_id"]))
    for run_id in candidates:
        if run_id:
            return run_id
    return None


def _side_plane_meta(image_block: dict[str, Any]) -> dict[str, Any]:
    dims = image_block.get("effective_dimensions") or {}
    return {
        "effective_dimensions": dims,
        "original_dimensions": image_block.get("original_dimensions"),
        "resample_factor": image_block.get("resample_factor"),
        "resampled": image_block.get("resampled"),
        "source_product": image_block.get("source_product"),
        "model_plane": "EFFECTIVE_MATCHER_PLANE",
        "frame_declared": bool(dims and dims.get("height") and dims.get("width")),
        "note": "Coordinates are expressed in the effective matcher plane for this side.",
    }


def _frame_block(input_meta: dict[str, Any]) -> dict[str, Any]:
    a = input_meta.get("image_a") or {}
    b = input_meta.get("image_b") or {}
    side_a = _side_plane_meta(a)
    side_b = _side_plane_meta(b)
    return {
        "frame": "EFFECTIVE_MATCHER_PLANE",
        "side_a": side_a,
        "side_b": side_b,
        "consistent": bool(side_a["frame_declared"] and side_b["frame_declared"]),
        "policy": (
            "If either side cannot declare its effective dimensions the run is "
            "BLOCKED/INVALID_COORDINATE_FRAME; coordinates are never silently "
            "reinterpreted."
        ),
    }


def _extract_correspondences(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    matcher = payload.get("matcher")
    if not isinstance(matcher, dict):
        return None
    corr = matcher.get("correspondences")
    if not isinstance(corr, list):
        return None
    return [c for c in corr if isinstance(c, dict)]


def _coords_from_correspondences(corr: list[dict[str, Any]]) -> np.ndarray:
    rows = []
    for c in corr:
        rows.append([c["x_a"], c["y_a"], c["x_b"], c["y_b"]])
    return np.asarray(rows, dtype=np.float64)


def trust_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    evidence = payload.get("evidence") or {}
    model = evidence.get("model")
    model_type = model.get("model_type") if isinstance(model, dict) else None
    inlier_ratio = evidence.get("inlier_ratio")
    if isinstance(inlier_ratio, float):
        inlier_ratio = round(inlier_ratio, 4)
    return {
        "run_id": payload.get("run_id"),
        "pair_id": payload.get("pair_id"),
        "created_at_utc": payload.get("created_at_utc"),
        "matcher_run_id": payload.get("matcher_run_id"),
        "matcher_id": payload.get("matcher_id"),
        "routing_run_id": payload.get("routing_run_id"),
        "routing_mode": payload.get("routing_mode"),
        "state": decision.get("state"),
        "decision_status": decision.get("state"),
        "reason_codes": decision.get("reasons"),
        "explanation": decision.get("explanation"),
        "decision_hash": payload.get("decision_hash"),
        "block_code": decision.get("block_code"),
        "abstain_code": decision.get("abstain_code"),
        "candidate_count": evidence.get("candidate_count"),
        "verified_count": evidence.get("verified_count"),
        "inlier_count": evidence.get("inlier_count"),
        "inlier_ratio": inlier_ratio,
        "model_type": model_type,
        "synthetically_derived": payload.get("synthetically_derived"),
        "configuration_id": payload.get("configuration_id"),
        "experiment_id": payload.get("experiment_id"),
        "runtime_ms": payload.get("runtime_ms"),
        "decision_tone": decision_tone(decision.get("state")),
    }


def decision_tone(state: str | None) -> str:
    if state == states.ACCEPT:
        return "ok"
    if state == states.REJECT:
        return "danger"
    if state == states.ABSTAIN:
        return "warn"
    return "neutral"


class TrustGateService:
    """Run, read, list and stat M7 trust gate runs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_state().settings
        self.config: TrustGateConfig = load_trust_gate_config()
        self.metadata_root = (
            self.settings.data_root_path / Path(self.config.derived_rel)
        )
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def _new_run_id(self, pair_id: str) -> str:
        while True:
            run_id = f"tg7-{pair_id}-{uuid.uuid4().hex[:8]}"
            if not self.artifact_path(run_id).exists():
                return run_id

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            raise OSError(f"Refusing to overwrite existing M7 trust artifact {path.name}")
        assert_artifact_vocabulary_safe(payload)
        atomic_write_json(path, payload)
        return path

    def read(self, run_id: str) -> dict[str, Any] | None:
        if not _safe_run_id(run_id):
            return None
        path = self.artifact_path(run_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def list_runs(self, pair_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.metadata_root.is_dir():
            return rows
        for p in sorted(self.metadata_root.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("pair_id") != pair_id:
                continue
            rows.append(trust_run_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------ run
    def run(
        self,
        pair_id: str,
        matcher_run_id: str | None = None,
        routing_run_id: str | None = None,
    ) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        cfg = self.config
        run_id = self._new_run_id(pair_id)
        created_at = rfc3339_now()

        matcher_payload, provenance = self._resolve_matcher_run(
            pair_id, matcher_run_id=matcher_run_id, routing_run_id=routing_run_id
        )
        if matcher_payload is None:
            raise NotFoundError(
                f"No M3/M4 matcher run available for pair {pair_id}; refusing to run "
                "the M7 trust gate without a matcher artifact (MATCH_RUN_NOT_AVAILABLE)."
            )

        base = self._base_artifact(
            record=record,
            run_id=run_id,
            created_at=created_at,
            matcher_payload=matcher_payload,
            provenance=provenance,
        )

        blocker = None
        if matcher_payload.get("status") != _STATUS_SUCCESS:
            base["block_code"] = states.CANDIDATES_MISSING
            base["decision"] = {
                "state": states.BLOCKED, "reasons": [states.CANDIDATES_MISSING],
                "explanation": (
                    f"Matcher run {matcher_payload.get('matcher_id')} did not reach "
                    "SUCCESS; no candidate correspondences exist to verify."
                ),
                "block_code": states.CANDIDATES_MISSING, "abstain_code": None,
            }
            base["errors"] = [matcher_payload.get("error_detail") or
                              matcher_payload.get("error_code") or "CANDIDATES_MISSING"]
        elif not _frame_block(self._input_meta(matcher_payload))["consistent"]:
            base["block_code"] = states.INVALID_COORDINATE_FRAME
            base["decision"] = {
                "state": states.BLOCKED, "reasons": [states.INVALID_COORDINATE_FRAME],
                "explanation": (
                    "One or both sides did not declare an effective matcher plane; "
                    "coordinates were never silently reinterpreted or scaled."
                ),
                "block_code": states.INVALID_COORDINATE_FRAME, "abstain_code": None,
            }
        elif bool(matcher_payload.get("synthetically_derived", False)) and not _synthetic_like(record):
            base["block_code"] = states.REAL_DATA_BLOCKED
            base["decision"] = {
                "state": states.BLOCKED, "reasons": [states.REAL_DATA_BLOCKED],
                "explanation": (
                    "This pair is REAL data but the matcher artifact was marked "
                    "synthetically_derived; a synthetic-derived trust verdict would "
                    "be misleading and is refused."
                ),
                "block_code": states.REAL_DATA_BLOCKED, "abstain_code": None,
            }
            base["errors"] = [
                "A REAL pair cannot be evaluated from a synthetically-derived matcher run."
            ]
        else:
            corr = _extract_correspondences(matcher_payload)
            if not corr:
                base["block_code"] = states.CANDIDATES_MISSING
                base["decision"] = {
                    "state": states.BLOCKED, "reasons": [states.CANDIDATES_MISSING],
                    "explanation": (
                        "The matcher run reported SUCCESS but produced no candidate "
                        "correspondences; nothing to verify."
                    ),
                    "block_code": states.CANDIDATES_MISSING, "abstain_code": None,
                }
            else:
                coords = _coords_from_correspondences(corr)
                budget_ms = int(cfg.decision.max_runtime_seconds) * 1000
                t0 = time.monotonic()
                from .engine import verify  # I/O stays out of the pure engine

                result = verify(coords, cfg)
                elapsed_ms = int(round((time.monotonic() - t0) * 1000))
                base.update({
                    "runtime_ms": elapsed_ms,
                    "coordinate_count": int(len(coords)),
                    "decision": result["decision"],
                    "evidence": result["evidence"],
                    "frame": _frame_block(self._input_meta(matcher_payload)),
                })
                if elapsed_ms > budget_ms and result["decision"]["state"] in (
                    states.ACCEPT, states.REJECT, states.ABSTAIN,
                ):
                    base["decision"] = {
                        "state": states.ABSTAIN, "reasons": [states.RESOURCE_LIMIT],
                        "explanation": (
                            f"Wall-clock budget {budget_ms} ms exceeded ({elapsed_ms} ms); "
                            "declared RESOURCE_LIMIT. The under-budget result was discarded."
                        ),
                        "block_code": None, "abstain_code": states.RESOURCE_LIMIT,
                    }
                    base["warnings"] = base.get("warnings", []) + [
                        "Runtime exceeded the declared max_runtime_seconds; "
                        "decision overridden to ABSTAIN/RESOURCE_LIMIT."
                    ]

        base["decision_hash"] = _decision_hash(base["decision"])
        base["run_id"] = run_id
        base["trust_run_id"] = run_id
        base["provenance"] = {
            "chain": _TRUST_CHAIN,
            "m3_or_m4_run": base.get("matcher_run_id"),
            "m6_routing_run": base.get("routing_run_id"),
            "m7_run": run_id,
            "frame": base.get("frame"),
        }
        base["license"] = license_text()

        path = self.write_artifact(run_id, base)
        logger.info("M7 trust gate run recorded for %s -> %s [%s]", pair_id, path.name,
                    base["decision"]["state"])
        return base

    def _input_meta(self, matcher_payload: dict[str, Any]) -> dict[str, Any]:
        return matcher_payload.get("input") or {}

    def _base_artifact(
        self,
        record,
        run_id: str,
        created_at: str,
        matcher_payload: dict[str, Any],
        provenance: dict[str, Any],
    ) -> dict[str, Any]:
        cfg = self.config
        matcher_block = matcher_payload.get("matcher") or {}
        routing_mode = provenance.get("routing_mode")
        matcher_id = matcher_payload.get("matcher_id") or matcher_block.get("matcher_id")
        experiment_id = (
            f"EXP-M7-{routing_mode or 'NONE'}-{str(matcher_id or 'MATCHER')}-{cfg.configuration_id}"
        )
        return {
            "run_id": run_id,
            "trust_run_id": run_id,
            "pair_id": record.pair_id,
            "experiment_id": experiment_id,
            "created_at_utc": created_at,
            "matcher_run_id": matcher_payload.get("run_id"),
            "matcher_id": matcher_id,
            "matcher_status": matcher_payload.get("status"),
            "matcher_configuration_id": matcher_payload.get("configuration_id"),
            "routing_mode": routing_mode,
            "routing_run_id": provenance.get("routing_run_id"),
            "source_gate": {
                "data_source_gate": record.data_source_gate,
                "source_class_a": record.source_class_a,
                "source_class_b": record.source_class_b,
            },
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
            "data_source_gate": record.data_source_gate,
            "synthetically_derived": bool(matcher_payload.get("synthetically_derived", False)),
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "configuration": _configuration_dict(cfg),
            "reference_status": cfg.reference_status,
            "decision": {
                "state": states.BLOCKED, "reasons": [],
                "explanation": "Pre-flight gates not satisfied.",
                "block_code": None, "abstain_code": None,
            },
            "evidence": {},
            "runtime_ms": None,
            "warnings": [],
            "errors": [],
            "environment": _environment_snapshot(),
            "frame": None,
        }

    # ------------------------------------------------ resolution
    def _resolve_matcher_run(
        self,
        pair_id: str,
        matcher_run_id: str | None,
        routing_run_id: str | None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        from ..matching.deep.service import DeepMatcherService

        deep = DeepMatcherService(self.settings)
        empty_provenance = {"routing_run_id": None, "routing_mode": None}

        if matcher_run_id:
            payload = deep.read_any(matcher_run_id)
            if payload is None:
                raise NotFoundError(f"No M3/M4 matcher run with id {matcher_run_id}.")
            if payload.get("pair_id") not in (None, pair_id):
                raise NotFoundError(
                    f"Matcher run {matcher_run_id} belongs to a different pair."
                )
            provenance = self._find_routing_provenance(
                pair_id, matcher_run_id, preferred_routing_run_id=routing_run_id
            )
            return payload, provenance

        routing = RoutingService(self.settings)
        if routing_run_id:
            routing_artifact = routing.read(routing_run_id)
            if routing_artifact is None:
                raise NotFoundError(f"No M6 routing run with id {routing_run_id}.")
            if routing_artifact.get("pair_id") != pair_id:
                raise NotFoundError(
                    f"Routing run {routing_run_id} belongs to a different pair."
                )
            executed = _executed_matcher_run_id(routing_artifact)
            payload = deep.read_any(executed) if executed else None
            if payload is None:
                raise NotFoundError(
                    f"M6 routing run {routing_run_id} has no executed matcher run "
                    "available (MATCH_RUN_NOT_AVAILABLE)."
                )
            return payload, {
                "routing_run_id": routing_run_id,
                "routing_mode": routing_artifact.get("mode"),
            }

        # Latest routing run for the pair that actually dispatched a matcher run.
        for summary in routing.list_runs(pair_id):
            rid = summary.get("routing_run_id")
            if not rid:
                continue
            routing_artifact = routing.read(str(rid))
            executed = _executed_matcher_run_id(routing_artifact)
            if not executed:
                continue
            payload = deep.read_any(executed)
            if payload is None:
                continue
            return payload, {
                "routing_run_id": rid,
                "routing_mode": (routing_artifact or {}).get("mode"),
            }

        # Fallback: latest successful baseline/deep run for the pair.
        payload = self._latest_matcher_run(pair_id)
        if payload is None:
            raise NotFoundError(
                f"No matcher artifact available for pair {pair_id} (MATCH_RUN_NOT_AVAILABLE)."
            )
        return payload, {
            "routing_run_id": None,
            "routing_mode": None,
        }

    def _latest_matcher_run(self, pair_id: str) -> dict[str, Any] | None:
        from ..matching.baseline import BaselineMatcherService
        from ..matching.deep.service import DeepMatcherService

        deep = DeepMatcherService(self.settings)
        rows: list[dict[str, Any]] = []
        rows += BaselineMatcherService(self.settings).list_runs(pair_id)
        rows += deep.list_runs(pair_id)
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        for row in rows:
            rid = row.get("run_id")
            if not rid or row.get("status") != _STATUS_SUCCESS:
                continue
            payload = deep.read_any(str(rid))
            if payload is not None:
                return payload
        return None

    def _find_routing_provenance(
        self,
        pair_id: str,
        matcher_run_id: str,
        preferred_routing_run_id: str | None,
    ) -> dict[str, Any]:
        routing = RoutingService(self.settings)
        if preferred_routing_run_id:
            artifact = routing.read(preferred_routing_run_id)
            if (
                isinstance(artifact, dict)
                and artifact.get("pair_id") == pair_id
                and _executed_matcher_run_id(artifact) == matcher_run_id
            ):
                return {
                    "routing_run_id": preferred_routing_run_id,
                    "routing_mode": artifact.get("mode"),
                }
        for summary in routing.list_runs(pair_id):
            rid = summary.get("routing_run_id")
            if not rid:
                continue
            artifact = routing.read(str(rid))
            if not isinstance(artifact, dict):
                continue
            if _executed_matcher_run_id(artifact) == matcher_run_id:
                return {
                    "routing_run_id": rid,
                    "routing_mode": artifact.get("mode"),
                }
        return {"routing_run_id": None, "routing_mode": None}

    # ------------------------------------------------ status
    def status(self, pair_id: str) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")
        cfg = self.config
        return {
            "pair_id": pair_id,
            "data_source_gate": record.data_source_gate,
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
            "synthetically_derived": bool(_synthetic_like(record)),
            "configured": {
                "configuration_id": cfg.configuration_id,
                "configuration_version": cfg.configuration_version,
                "scientifically_tuned": cfg.scientifically_tuned,
                "reference_status": cfg.reference_status,
                "models": list(cfg.geometry.models),
                "preferred_model": cfg.geometry.preferred_model,
                "min_candidates": cfg.decision.min_candidates,
                "min_inliers": cfg.decision.min_inliers,
                "min_inlier_ratio": cfg.decision.min_inlier_ratio,
                "max_runtime_seconds": cfg.decision.max_runtime_seconds,
            },
            "latest_run": self.latest_for_pair(pair_id),
        }


__all__ = [
    "TrustGateService",
    "trust_run_summary",
    "decision_tone",
]