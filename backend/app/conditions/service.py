"""M5 — condition estimator service.

Evaluates the intrinsic condition of each side + the pair-level relationship
BEFORE any matcher selection. Honesty rules honoured here:

    * consumes ONLY validated M2 products (READY_FOR_MATCHING state); missing
      runs/products are reported with stable codes, never simulated.
    * deterministic: fixed-stride window sampling with a recorded seed and an
      explicit sampling plan in every artifact; fixed input + fixed
      configuration + fixed libraries ⇒ identical output.
    * GSD comes from documented geometry/PDS4 sources only; when absent it is
      recorded as UNKNOWN — never inferred from pixel counts.
    * optional latest-baseline matcher observations live in a SEPARATE,
      explicitly-labelled section; they are recorded for context only and this
      layer never selects, recommends or routes a matcher.
    * artifacts land in ``data/metadata/m5_condition/<run_id>.json``
      (``derived_rel`` config); run ids are unique and never overwritten.
"""

from __future__ import annotations

import platform
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from ..config import rfc3339_now
from ..hardening import atomic_write_json
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from .config import ConditionConfig, load_condition_config
from .contract import (
    CONDITION_ESTIMATION_FAILED,
    PROCESS_NOT_READY,
    PROCESSING_NOT_RUN,
    PRODUCT_MISSING,
    assert_payload_schema_safe,
)
from .metrics import pair_comparison, side_condition

logger = get_logger(__name__)

_STATUS_SUCCESS = "SUCCESS"
_STATUS_BLOCKED = "BLOCKED"
_STATUS_FAILED = "FAILED"

_GSD_SOURCE_MAPPING = {
    "TEST_FIXTURE_OVERRIDE": "RECORDED_GEOMETRY",
    "NOMINAL": "NOMINAL_SENSOR",
    "LABEL": "PDS4_LABEL",
    "UNKNOWN": "UNKNOWN",
}


class ConditionEstimationService:
    """Run, read and list M5 condition-estimator runs over M2 products."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.config: ConditionConfig = load_condition_config()
        self.metadata_root = (
            self.settings.data_root_path / Path(self.config.p("derived_rel", default="metadata/m5_condition"))
        )
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def capabilities_public(self) -> dict[str, Any]:
        from .config import configurations_public

        gate = real_data_gate(self.settings)
        return {
            "condition_estimator_configuration_id": self.config.configuration_id,
            "configuration_version": self.config.configuration_version,
            "name": self.config.name,
            "configuration": configurations_public()[0] if configurations_public() else None,
            "data_gate": gate,
            "note": (
                "This layer characterizes the pair from M2 validated products "
                "only. It never selects, recommends or routes a matcher and "
                "never reports a confidence or a scientific quality verdict. "
                "Classification bins are engineering-level ordinals with "
                "explicit thresholds recorded in every artifact."
            ),
        }

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            raise OSError(f"Refusing to overwrite existing M5 condition-artifact {path.name}")
        assert_payload_schema_safe(payload)
        atomic_write_json(path, payload)
        return path

    def read(self, run_id: str) -> dict[str, Any] | None:
        if not _safe_run_id(run_id):
            return None
        path = self.artifact_path(run_id)
        if not path.is_file():
            return None
        try:
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def list_runs(self, pair_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.metadata_root.is_dir():
            return rows
        for p in sorted(self.metadata_root.glob("*.json")):
            try:
                import json

                payload = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if payload.get("pair_id") != pair_id:
                continue
            rows.append(condition_run_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ run
    def resolve_processed_inputs(self, pair_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """Return (blocker_or_none, inputs) reading M2 validated products."""
        from ..processing.service import ProcessingService

        proc = ProcessingService(self.settings)
        status = proc.read_status(pair_id)
        state = (status or {}).get("state") or ""
        if state != "READY_FOR_MATCHING":
            return {
                "error_code": PROCESSING_NOT_RUN,
                "reason": (
                    f"No validated M2 products are READY_FOR_MATCHING for pair {pair_id} "
                    f"(current state: {state or 'none'}). Run M2 PREPARE first; the "
                    "condition estimator only consumes validated products."
                ),
            }, {}
        products = (status or {}).get("products") or {}
        if not products:
            return {
                "error_code": PROCESSING_NOT_RUN,
                "reason": (
                    f"No M2 validated products exist for pair {pair_id}. Run M2 PREPARE "
                    "first; the condition estimator only consumes validated products."
                ),
            }, {}
        run_dir = proc.find_run_for_pair(pair_id)
        if run_dir is None:
            return {
                "error_code": PROCESS_NOT_READY,
                "reason": f"No on-disk M2 processing run directory found for pair {pair_id}.",
            }, {}

        try:
            inputs: dict[str, Any] = {}
            for side in ("a", "b"):
                prod = products.get(side) or {}
                display_rel = prod.get("display_rel")
                mask_rel = prod.get("mask_rel")
                base = self.settings.data_root_path
                display_path = base / display_rel if display_rel else None
                mask_path = (base / mask_rel) if mask_rel else None
                if display_path is None or not display_path.is_file():
                    return {
                        "error_code": PRODUCT_MISSING,
                        "reason": f"Preprocessed display product missing for side {side.upper()}: {display_rel}",
                    }, {}
                if mask_path is None or not mask_path.is_file():
                    return {
                        "error_code": PRODUCT_MISSING,
                        "reason": f"Preprocessed mask product missing for side {side.upper()}: {mask_rel}",
                    }, {}
                arr = np.asarray(np.load(display_path, mmap_mode="r")).copy()
                mask = np.asarray(np.load(mask_path, mmap_mode="r")).copy()
                inputs[side] = {
                    "sensor": prod.get("sensor"),
                    "array": arr,
                    "mask": mask,
                    "display_path": display_path,
                    "mask_path": mask_path,
                    "sha256": _sha256_file(display_path),
                }
            return None, {
                "inputs": inputs,
                "status": status,
                "run_dir": run_dir,
            }
        except (OSError, ValueError) as exc:
            return {
                "error_code": PRODUCT_MISSING,
                "reason": f"Could not load M2 validated products for pair {pair_id}: {exc}",
            }, {}

    def run(self, pair_id: str) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            from ..errors import NotFoundError

            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        created_at = rfc3339_now()
        run_id = self._new_run_id(pair_id)
        started = time.perf_counter()

        blocker, resolved = self.resolve_processed_inputs(pair_id)
        if blocker is not None:
            payload = {
                "run_id": run_id,
                "pair_id": pair_id,
                "created_at_utc": created_at,
                "status": _STATUS_BLOCKED,
                "state": "BLOCKED",
                "error_code": blocker["error_code"],
                "error_detail": blocker["reason"],
                "configuration_id": self.config.configuration_id,
                "configuration_version": self.config.configuration_version,
                "configuration": self.config.as_manifest_snapshot(),
                "environment": _environment_snapshot(),
                "determinism": self._determinism_snapshot(),
                "runtime_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "source_gate": self._source_gate(record),
                "synthetically_derived": self._synthetic(record),
                "estimated": None,
                "intrinsic_image_condition": None,
                "pair_comparison": None,
                "matcher_derived_observations": None,
                "processing": None,
                "license": _LICENSE,
            }
            self.write_artifact(run_id, payload)
            return payload

        status = resolved["status"]
        run_dir = resolved["run_dir"]
        inputs = resolved["inputs"]

        try:
            cfg = self.config
            side_a_geo, side_b_geo = self._gsd_facts(run_dir, inputs["a"]["sensor"], inputs["b"]["sensor"])

            cond_a = side_condition(inputs["a"]["array"], inputs["a"]["mask"], cfg, side_id="a")
            cond_b = side_condition(inputs["b"]["array"], inputs["b"]["mask"], cfg, side_id="b")
            comparison = pair_comparison(cond_a, cond_b, cfg, gsd_a=side_a_geo, gsd_b=side_b_geo)

            intrinsic = {
                "side_a": _public_side(cond_a, inputs["a"], self.settings),
                "side_b": _public_side(cond_b, inputs["b"], self.settings),
            }
            observations = self._matcher_observations(pair_id)

            payload = {
                "run_id": run_id,
                "pair_id": pair_id,
                "created_at_utc": created_at,
                "status": _STATUS_SUCCESS,
                "state": "SUCCESS",
                "error_code": None,
                "error_detail": None,
                "configuration_id": cfg.configuration_id,
                "configuration_version": cfg.configuration_version,
                "configuration": cfg.as_manifest_snapshot(),
                "environment": _environment_snapshot(),
                "determinism": self._determinism_snapshot(),
                "runtime_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "source_gate": self._source_gate(record),
                "synthetically_derived": self._synthetic(record),
                "geometry_source": self._geometry_source(run_dir),
                "processing": {
                    "processing_configuration_id": status.get("configuration_id"),
                    "processing_state": status.get("state"),
                    "processing_run_rel": _rel(self.settings.data_root_path, run_dir),
                    "processing_status_rel": _rel(self.settings.data_root_path, run_dir / "processing_status.json"),
                    "note": "M2 validated products consumed as-is; no re-preprocessing occurred.",
                },
                "estimated": {
                    "scientifically_tuned": cfg.scientifically_tuned,
                    "level": "CONDITION_ESTIMATION",
                    "note": cfg.p("classification", "note", default="Engineering-level ordinal bins (LOW/MEDIUM/HIGH) with explicit thresholds recorded in every artifact. Reproducible labels for engineering use only — never a scientific quality verdict and never an input to matcher selection in this layer."),
                },
                "intrinsic_image_condition": intrinsic,
                "pair_comparison": comparison,
                "matcher_derived_observations": observations,
                "license": _LICENSE,
            }
        except Exception as exc:  # noqa: BLE001
            payload = {
                "run_id": run_id,
                "pair_id": pair_id,
                "created_at_utc": created_at,
                "status": _STATUS_FAILED,
                "state": "FAILED",
                "error_code": CONDITION_ESTIMATION_FAILED,
                "error_detail": f"Condition estimation raised: {exc}",
                "configuration_id": self.config.configuration_id,
                "configuration_version": self.config.configuration_version,
                "configuration": self.config.as_manifest_snapshot(),
                "environment": _environment_snapshot(),
                "determinism": self._determinism_snapshot(),
                "runtime_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "source_gate": self._source_gate(record),
                "synthetically_derived": self._synthetic(record),
                "estimated": None,
                "intrinsic_image_condition": None,
                "pair_comparison": None,
                "matcher_derived_observations": None,
                "processing": None,
                "license": _LICENSE,
            }
            logger.exception("M5 condition estimation failed for %s", pair_id)
            self.write_artifact(run_id, payload)
            return payload

        self.write_artifact(run_id, payload)
        return payload

    # ------------------------------------------------------------------ facts
    def _geometry_source(self, run_dir: Path) -> str:
        from ..processing.manifest import load_manifest

        manifest = load_manifest(run_dir / "processing_manifest.json")
        geo = (manifest or {}).get("geometry")
        if isinstance(geo, dict) and geo.get("source"):
            return str(geo["source"])
        return "UNKNOWN"

    def _gsd_facts(self, run_dir: Path, sensor_a: str, sensor_b: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Recorded GSD per side, mapped onto the documented source taxonomy."""
        if not self.config.gsd_enabled:
            return None, None
        from ..processing.manifest import load_manifest

        manifest = load_manifest(run_dir / "processing_manifest.json")
        geo = (manifest or {}).get("geometry")
        if not isinstance(geo, dict):
            return _unknown_gsd(), _unknown_gsd()
        products = geo.get("products") or {}
        reference = str(geo.get("reference") or "")
        by_sensor = {str(g.get("sensor")): g for g in products.values() if isinstance(g, dict)}

        def _for(sensor: str) -> dict[str, Any] | None:
            g = by_sensor.get(sensor) if products else None
            if g is None:
                return None
            gsd_m = g.get("gsd_m")
            if not isinstance(gsd_m, (int, float)) or gsd_m <= 0:
                return None
            raw_source = str(g.get("gsd_source") or "UNKNOWN")
            return {
                "gsd_m": float(gsd_m),
                "gsd_source": _GSD_SOURCE_MAPPING.get(raw_source, raw_source),
                "gsd_source_detail": raw_source,
                "reference": reference,
                "geometry_source": str(geo.get("source") or "UNKNOWN"),
            }

        g_a = _for(sensor_a) if sensor_a else None
        g_b = _for(sensor_b) if sensor_b else None
        return g_a, g_b

    def _matcher_observations(self, pair_id: str) -> dict[str, Any] | None:
        if not self.config.matcher_observations_enabled:
            return None
        baseline_cfg = str(self.config.p("matcher_observations", "baseline_configuration", default="MB-M3-001"))
        try:
            from ..matching.baseline import BaselineMatcherService

            latest = BaselineMatcherService(self.settings).latest_for_pair(pair_id)
        except Exception:  # noqa: BLE001
            latest = None
        if not latest:
            return None
        counts = {}
        matcher = latest.get("matcher_id")
        if matcher:
            counts[matcher] = int((latest.get("counts") or {}).get("candidates", 0))
        return {
            "source": "M3_BASELINE_OBSERVATION",
            "baseline_configuration": baseline_cfg,
            "latest_baseline_run_id": latest.get("run_id"),
            "latest_baseline_status": latest.get("status"),
            "candidate_counts_by_matcher": counts,
            "note": (
                "Separate, explicitly labelled observations from the M3 baseline matcher, "
                "recorded for context only. The M5 condition estimator performed no matcher "
                "selection; this section never influences the intrinsic condition estimates."
            ),
        }

    def _source_gate(self, record) -> dict[str, Any]:
        return {
            "data_source_gate": record.data_source_gate,
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
        }

    def _synthetic(self, record) -> bool:
        ids = f"{record.source_class_a} {record.source_class_b}"
        if "FIXTURE" in ids.upper() or "fixture" in ids:
            return True
        if record.data_source_gate != "PATH_A_REAL_DATA":
            return True
        return False

    def _new_run_id(self, pair_id: str) -> str:
        while True:
            run_id = f"ce-{pair_id}-{uuid.uuid4().hex[:8]}"
            if not self.artifact_path(run_id).exists():
                return run_id

    def _determinism_snapshot(self) -> dict[str, Any]:
        return {
            "guarantee": "Fixed input (M2 validated products) + fixed configuration + fixed libraries produce identical output; sampling is a deterministic fixed-stride grid.",
            "seed_recorded": self.config.sampling_seed,
            "verified_by": "deterministic rerun equality (see M5 tests)",
            "window_size_px": self.config.window_size_px,
            "stride_px": self.config.stride_px,
            "max_windows": self.config.max_windows,
        }


def real_data_gate(settings) -> dict[str, Any]:
    """Machine-readable truth about genuine PRADAN data availability.

    Mirrors the M3 baseline gate so every pair class faces the same rules:
    fixture-only environments report REAL_DATA_BLOCKED; genuine products are
    never simulated and never assumed.
    """
    from ..pairs import scan_raw_products

    try:
        inventory = scan_raw_products(settings)
    except Exception:  # noqa: BLE001
        return {
            "code": "REAL_DATA_STATUS_UNKNOWN",
            "message": "Raw product inventory could not be scanned.",
            "real_data_available": False,
        }
    real = [e for e in inventory if e.get("source_class") == "REAL_PRADAN"]
    if real:
        return {
            "code": "REAL_DATA_AVAILABLE",
            "message": f"{len(real)} genuine PRADAN product(s) detected.",
            "real_data_available": True,
        }
    return {
        "code": "REAL_DATA_BLOCKED",
        "message": "No genuine PRADAN raw products are present; only TEST_FIXTURE (synthetic) data is available. Real PRADAN condition estimation remains blocked pending operator data.",
        "real_data_available": False,
    }


def condition_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    intrinsic = payload.get("intrinsic_image_condition") or {}
    comparison = payload.get("pair_comparison") or {}
    levels: dict[str, dict[str, str]] = {}
    for side in ("side_a", "side_b"):
        side_dict = intrinsic.get(side) or {}
        cls = side_dict.get("classification") or {}
        levels[side] = {
            "textural_complexity": (cls.get("textural_complexity") or {}).get("bin", "UNKNOWN"),
            "dynamic_range": (cls.get("dynamic_range") or {}).get("bin", "UNKNOWN"),
            "invalid_fraction": (cls.get("invalid_fraction") or {}).get("bin", "UNKNOWN"),
        }
    return {
        "run_id": payload.get("run_id"),
        "pair_id": payload.get("pair_id"),
        "status": payload.get("status"),
        "state": payload.get("state"),
        "created_at_utc": payload.get("created_at_utc"),
        "configuration_id": payload.get("configuration_id"),
        "error_code": payload.get("error_code"),
        "error_detail": payload.get("error_detail"),
        "synthetically_derived": payload.get("synthetically_derived"),
        "source_gate": payload.get("source_gate"),
        "geometry_source": payload.get("geometry_source"),
        "levels": levels,
        "histogram_distance_chi_square": (comparison.get("appearance") or {}).get("histogram_distance_chi_square"),
        "gsd_ratio_relationship": (comparison.get("scale") or {}).get("gsd_ratio_relationship"),
        "runtime_ms": payload.get("runtime_ms"),
        "license": payload.get("license"),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_LICENSE = (
    "Condition estimates are reproducible engineering labels derived from the "
    "M2 validated products (texture energy, appearance statistics, invalid-"
    "mask coverage, recorded scale/geometry). They are NOT a scientific "
    "accuracy or quality verdict and they never select, recommend or route a "
    "matcher."
)


def _public_side(cond: dict[str, Any], side_input: dict[str, Any], settings) -> dict[str, Any]:
    est = {k: v for k, v in cond.items() if k not in ("_pooled_values",)}
    base = settings.data_root_path
    est["established_facts"]["product"] = {
        "sensor": side_input.get("sensor"),
        "display_rel": _rel(base, Path(side_input["display_path"])),
        "mask_rel": _rel(base, Path(side_input["mask_path"])),
        "sha256": side_input.get("sha256"),
    }
    return est


def _rel(base: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except (ValueError, OSError):
        return path.name


def _unknown_gsd() -> dict[str, Any]:
    return {"gsd_m": None, "gsd_source": "UNKNOWN", "gsd_source_detail": "UNKNOWN", "reference": None}


def _safe_run_id(run_id: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id or ""))


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _environment_snapshot() -> dict[str, Any]:
    import cv2

    return {
        "numpy_version": getattr(np, "__version__", "unknown"),
        "opencv_version": getattr(cv2, "__version__", "unknown"),
        "python": platform.python_version(),
        "platform": platform.system(),
    }


# re-export error codes used by the API layer
__all__ = [
    "ConditionEstimationService",
    "condition_run_summary",
    "real_data_gate",
]