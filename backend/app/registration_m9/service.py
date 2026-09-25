"""M9 REGISTRATION — service (run, read, list, status, persistence).

Consumes ONE usable M8 spatial-selection artifact (explicit ``m8_run_id`` or
the latest usable run for the pair), never raw M3/M4 or arbitrary M7 inliers.
The standard path is M2 -> M3/M4 (-> M6 adaptivity) -> M7 trust gate ->
M8 spatial selection -> M9 registration. M9:

* estimates the smallest technically valid declared transform (affine
  preferred, normalized-DLT homography only on explicit escalation);
* independently validates inputs and the transform on their own merits;
* records residual diagnostics in px of the effective matcher plane;
* produces a derived aligned/warped output where the effective-plane source
  image is available;
* never rewrites the M7 verdict or the M8 status, never claims physical
  accuracy, never emits confidence vocabulary, and never overwrites runs.

Artifacts live under ``data/metadata/m9_registration/<run_id>.json`` (plus
derived warp/visualization assets under ``data/metadata/m9_registration/warp``)
with relative paths only.
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
from ..hardening import atomic_write_json, atomic_write_npy
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from ..state import get_state
from . import states
from .config import RegistrationM9Config, load_registration_m9_config
from .contract import assert_artifact_vocabulary_safe, license_text
from .fit import choose_and_fit
from .points import validate_selected_points
from .validate import validate_transform
from .warp import (
    build_before_after,
    build_checkerboard,
    build_difference_map,
    build_overlay,
    build_residual_vectors,
    to_dtype,
    warp_to_frame,
    write_preview_png,
)

logger = get_logger(__name__)

_REGISTRATION_CHAIN = (
    "M2 -> M3/M4 (-> M6 adaptivity) -> M7 trust gate "
    "-> M8 spatial selection -> M9 registration"
)
_VALID_MODELS = ("auto", "affine", "homography")


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

    try:
        from PIL import Image  # noqa: PLC0415

        pil_version = Image.__version__ or "unknown"
    except Exception:  # noqa: BLE001
        pil_version = "unknown"
    return {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "numpy_version": numpy.__version__,
        "opencv_version": cv2.__version__,
        "pillow_version": pil_version,
        "rng": "NONE",
        "rng_seed_policy": "No random sampling; every step is fully deterministic.",
    }


def _configuration_dict(cfg: RegistrationM9Config) -> dict[str, Any]:
    return json.loads(json.dumps(dataclasses.asdict(cfg)))


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _transform_hash(matrix: Any) -> str:
    blob = json.dumps(
        [[round(float(v), 9) for v in row] for row in matrix.tolist()],
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _decision_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _rel(data_root: Path, path: Path) -> str:
    return str(path.relative_to(data_root)).replace("\\", "/")


def m9_run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    decision = payload.get("decision") or {}
    registration = payload.get("registration") or {}
    warp = payload.get("warp") or {}
    return {
        "run_id": payload.get("run_id"),
        "pair_id": payload.get("pair_id"),
        "created_at_utc": payload.get("created_at_utc"),
        "m8_run_id": payload.get("m8_run_id"),
        "m7_trust_run_id": payload.get("m7_trust_run_id"),
        "matcher_run_id": payload.get("matcher_run_id"),
        "matcher_id": payload.get("matcher_id"),
        "state": decision.get("state"),
        "reason_codes": decision.get("reasons"),
        "block_code": decision.get("block_code"),
        "abstain_code": decision.get("abstain_code"),
        "explanation": decision.get("explanation"),
        "decision_hash": decision.get("decision_hash") or payload.get("decision_hash"),
        "model_type": registration.get("model_type"),
        "selection_reason": registration.get("selection_reason"),
        "accepted": registration.get("accepted"),
        "selected_count": registration.get("selected_count"),
        "residual_rmse_px": (registration.get("residual_statistics") or {}).get("rmse"),
        "warp_available": warp.get("available"),
        "synthetically_derived": payload.get("synthetically_derived"),
        "configuration_id": payload.get("configuration_id"),
        "runtime_ms": payload.get("runtime_ms"),
        "tone": states.tone(decision.get("state")),
    }


class RegistrationM9Service:
    """Run, read, list and stat M9 registration runs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_state().settings
        self.config: RegistrationM9Config = load_registration_m9_config()
        self.metadata_root = (
            self.settings.data_root_path / Path(self.config.derived_rel)
        )
        self.warp_root = (
            self.settings.data_root_path / Path(self.config.derived_rel) / "warp"
        )
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def _warp_dir(self, run_id: str) -> Path:
        return self.warp_root / run_id

    def _new_run_id(self, pair_id: str) -> str:
        while True:
            run_id = f"m9r-{pair_id}-{uuid.uuid4().hex[:8]}"
            if not self.artifact_path(run_id).exists():
                return run_id

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            raise OSError(f"Refusing to overwrite existing M9 registration artifact {path.name}")
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
            rows.append(m9_run_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------ resolution of M8 input
    def _resolve_m8_artifact(self, pair_id: str, m8_run_id: str | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Return (m8_artifact, decision) or (None, block_dict)."""
        from ..spatial_m8.service import SpatialSelectionService

        m8 = SpatialSelectionService(self.settings)
        payload: dict[str, Any] | None = None
        if m8_run_id:
            payload = m8.read(m8_run_id)
            if payload is None:
                return None, self._blocked(
                    states.M8_SELECTION_NOT_AVAILABLE,
                    f"No M8 spatial selection run with id {m8_run_id} exists.",
                )
            if payload.get("pair_id") != pair_id:
                return None, self._blocked(
                    states.INPUT_ARTIFACT_INVALID,
                    f"M8 run {m8_run_id} belongs to a different pair "
                    f"({payload.get('pair_id')!r}), not {pair_id!r}.",
                )
        else:
            rows = m8.list_runs(pair_id)
            for row in rows:
                if row.get("state") in states.M8_USABLE_STATES:
                    art = m8.read(str(row["run_id"]))
                    if art is not None:
                        payload = art
                        break
            if payload is None:
                if rows:
                    latest_state = rows[0].get("state")
                    return None, self._blocked(
                        states.M8_SELECTION_NOT_AVAILABLE,
                        f"No usable (SELECTED / SELECTED_WITH_WARNINGS) M8 spatial "
                        f"selection exists for this pair (latest M8 state: "
                        f"{latest_state}). Registration refuses to bypass M8 and "
                        "fall back to M7 or raw candidates.",
                    )
                return None, self._blocked(
                    states.M8_SELECTION_NOT_AVAILABLE,
                    "No M8 spatial selection exists for this pair — run M8 "
                    "SPATIAL SELECTION first.",
                )

        decision = payload.get("decision")
        if not isinstance(decision, dict) or decision.get("state") not in states.M8_USABLE_STATES:
            return None, self._blocked(
                states.M8_SELECTION_NOT_AVAILABLE,
                f"The resolved M8 artifact decision.state is "
                f"{decision.get('state') if isinstance(decision, dict) else None!r}; "
                "a usable spatial selection is required and M8 is never overridden.",
            )
        return payload, None

    # ------------------------------------------------ frames
    @staticmethod
    def _frame_dims(m8_artifact: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        evidence = m8_artifact.get("evidence") or {}
        frame = evidence.get("frame") or {}
        side_a = (frame.get("side_a") or {}).get("effective_dimensions") or {}
        side_b = (frame.get("side_b") or {}).get("effective_dimensions") or {}
        dims_a = {"height": side_a.get("height"), "width": side_a.get("width")}
        dims_b = {"height": side_b.get("height"), "width": side_b.get("width")}
        if not (dims_a["height"] and dims_a["width"] and dims_b["height"] and dims_b["width"]):
            return None, None
        return dims_a, dims_b

    # ------------------------------------------------ images for warp
    def _resolve_display_arrays(self, pair_id: str) -> dict[str, Any]:
        """Load effective-plane display arrays for both sides (M2 products)."""
        from ..processing.service import ProcessingService

        try:
            proc = ProcessingService(self.settings)
            status = proc.read_status(pair_id)
        except Exception:  # noqa: BLE001
            return {}
        products = (status or {}).get("products") or {}
        arrays: dict[str, Any] = {}
        root = self.settings.data_root_path
        for side, key in (("a", "display_rel"), ("b", "display_rel")):
            prod = products.get(side) or {}
            rel = prod.get(key) or prod.get("display_rel")
            if not rel:
                continue
            path = root / rel
            if not path.is_file():
                continue
            try:
                arr = np_load_2d(path)
            except Exception:  # noqa: BLE001
                continue
            if arr is not None:
                arrays[side] = {
                    "array": arr,
                    "rel": _rel(root, path),
                    "sha256": _sha256_of(path),
                    "shape": list(arr.shape),
                }
        return arrays

    # ------------------------------------------------ run
    def run(self, pair_id: str, m8_run_id: str | None = None, model: str = "auto") -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        cfg = self.config
        run_id = self._new_run_id(pair_id)
        created_at = rfc3339_now()
        base = self._base_artifact(record, run_id, created_at)
        budget_ms = int(cfg.execution.max_runtime_seconds) * 1000
        t0 = time.monotonic()

        try:
            if model not in _VALID_MODELS:
                base["decision"] = self._blocked_decision(
                    states.INPUT_ARTIFACT_INVALID,
                    f"Unknown model request {model!r}; expected one of {_VALID_MODELS}.",
                )
            else:
                self._run_registration(record, base, m8_run_id, model)
        except NotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("M9 registration failed for %s", pair_id)
            base["decision"] = {
                "state": states.FAILED, "reasons": [states.TRANSFORM_FIT_ERROR],
                "explanation": f"M9 registration failed: {exc}",
                "block_code": None, "abstain_code": None,
            }
            base["errors"] = [str(exc)]

        elapsed_ms = int(round((time.monotonic() - t0) * 1000))
        base["runtime_ms"] = elapsed_ms
        if isinstance(base.get("performance"), dict):
            base["performance"]["total_runtime_ms"] = elapsed_ms
        if elapsed_ms > budget_ms and base["decision"]["state"] in (
            states.SUCCESS, states.SUCCESS_WITH_WARNINGS, states.ABSTAIN,
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
                "Runtime exceeded the declared max_runtime_seconds; result "
                "overridden to ABSTAIN/RESOURCE_LIMIT."
            ]

        base["decision_hash"] = _decision_hash(base["decision"])
        base["provenance"] = {
            "chain": _REGISTRATION_CHAIN,
            "m8_run": base.get("m8_run_id"),
            "m7_run": base.get("m7_trust_run_id"),
            "matcher_run": base.get("matcher_run_id"),
            "m9_run": run_id,
        }
        base["license"] = license_text()

        try:
            path = self.write_artifact(run_id, base)
        except OSError as exc:  # pragma: no cover - unique run_id protects us
            base["decision"] = {
                "state": states.FAILED, "reasons": [states.ARTIFACT_WRITE_FAILED],
                "explanation": f"M9 artifact write failed: {exc}",
                "block_code": None, "abstain_code": None,
            }
            base["decision_hash"] = _decision_hash(base["decision"])
            base["errors"] = base.get("errors", []) + [str(exc)]
            atomic_write_json(self.artifact_path(run_id), base)
            path = self.artifact_path(run_id)
        logger.info("M9 registration run recorded for %s -> %s [%s]",
                    pair_id, path.name, base["decision"]["state"])
        return base

    # ------------------------------------------------ run internals
    def _run_registration(
        self,
        record,
        base: dict[str, Any],
        m8_run_id: str | None,
        model: str,
    ) -> None:
        cfg = self.config
        t_fit = time.monotonic()

        m8_artifact, block = self._resolve_m8_artifact(record.pair_id, m8_run_id)
        if block is not None:
            base["decision"] = block["decision"]
            base["errors"] = [block["explanation"]]
            return
        if m8_artifact is None:  # pragma: no cover - defensive
            base["decision"] = self._blocked_decision(
                states.M8_SELECTION_NOT_AVAILABLE, "M8 artifact could not be resolved.")
            base["errors"] = [base["decision"]["explanation"]]
            return

        base["m8_run_id"] = m8_artifact.get("run_id") or m8_artifact.get("m8_spatial_run_id")
        base["m7_trust_run_id"] = m8_artifact.get("trust_run_id")
        base["matcher_run_id"] = m8_artifact.get("matcher_run_id")
        base["matcher_id"] = m8_artifact.get("matcher_id")
        base["synthetically_derived"] = bool(m8_artifact.get("synthetically_derived", False))
        base["experiment_id"] = (
            f"EXP-M9-{m8_artifact.get('run_id') or m8_artifact.get('m8_spatial_run_id')}-"
            f"{str(base.get('matcher_id') or 'MATCHER')}-{cfg.configuration_id}"
        )
        base["upstream"] = {
            "m8_run_id": base["m8_run_id"],
            "m8_status": (m8_artifact.get("decision") or {}).get("state"),
            "m7_trust_run_id": m8_artifact.get("trust_run_id"),
            "m7_decision": (m8_artifact.get("m7_decision") or {})
            or self._m7_decision_from_m8(m8_artifact),
            "matcher_run_id": m8_artifact.get("matcher_run_id"),
            "matcher_id": m8_artifact.get("matcher_id"),
            "m8_configuration_id": m8_artifact.get("configuration_id"),
            "m8_decision_hash": m8_artifact.get("decision_hash"),
        }
        if base.get("m8_run_id"):
            from ..spatial_m8.service import SpatialSelectionService

            m8_path = SpatialSelectionService(self.settings).artifact_path(base["m8_run_id"])
            base["input_hashes"] = {"m8_artifact": _sha256_of(m8_path) if m8_path.is_file() else None}

        # real-data gate: never run synthetic M8 over a REAL pair
        if record.data_source_gate == "PATH_A_REAL_DATA" and bool(m8_artifact.get("synthetically_derived")):
            base["decision"] = self._blocked_decision(
                states.REAL_DATA_BLOCKED,
                "This pair is REAL data but the resolved M8 artifact is "
                "synthetically derived; a registration would be misleading "
                "and is refused.",
            )
            base["errors"] = [base["decision"]["explanation"]]
            return

        dims_a, dims_b = self._frame_dims(m8_artifact)
        if dims_a is None or dims_b is None:
            base["decision"] = self._blocked_decision(
                states.INVALID_COORDINATE_FRAME,
                "The M8 artifact does not declare effective dimensions for both "
                "sides; registration cannot declare its coordinate frame.",
            )
            base["errors"] = [base["decision"]["explanation"]]
            return

        evidence = m8_artifact.get("evidence") or {}
        selection_record = evidence.get("selection_record") or {}
        selected = selection_record.get("selected")
        if not isinstance(selected, list):
            base["decision"] = self._blocked_decision(
                states.INPUT_ARTIFACT_INVALID,
                "The M8 selection record carries no selected correspondences.",
            )
            base["errors"] = [base["decision"]["explanation"]]
            return

        base["frame"] = {
            "frame": "EFFECTIVE_MATCHER_PLANE",
            "coordinate_convention": "top_left_origin, x = column, y = row",
            "unit": "px",
            "side_a": {"effective_dimensions": dims_a},
            "side_b": {"effective_dimensions": dims_b},
            "source_frame": {"side": "a", "dimensions": dims_a},
            "target_frame": {"side": "b", "dimensions": dims_b},
            "model_frame": "EFFECTIVE_MATCHER_PLANE",
            "warp_frame": "TARGET_B_EFFECTIVE_FRAME",
            "resample_factor_note": "M9 consumes the effective matcher plane as declared by the M8 artifact; no silent rescaling.",
        }

        points = validate_selected_points(selected, cfg)
        base["input_validation"] = points.to_record()
        if not points.ok:
            base["warnings"] = list(points.warnings)
            base["decision"] = self._abstain_decision(
                points.abstain_code or states.INSUFFICIENT_SELECTED_POINTS,
                points.explanation,
            )
            base["errors"] = [points.explanation]
            return

        pts_a = points.pts_a
        pts_b = points.pts_b
        fit = choose_and_fit(pts_a, pts_b, cfg, requested_model=model)
        model_type = fit.model_type
        if fit.matrix is None or fit.error:
            base["decision"] = {
                "state": states.FAILED, "reasons": [states.TRANSFORM_FIT_ERROR],
                "explanation": f"Transform fit failed: {fit.error}", "block_code": None,
                "abstain_code": None,
            }
            base["errors"] = [fit.error or "TRANSFORM_FIT_ERROR"]
            base["registration"] = {
                "model_type": model_type, "algorithm": fit.algorithm,
                "selection_reason": fit.selection_reason,
                "transform_matrix": None, "transform_valid": False,
                "accepted": False, "fit_diagnostics": fit.fit_diagnostics,
                "selected_count": len(points.entries),
            }
            return

        outcome = validate_transform(fit.matrix, model_type, fit.algorithm,
                                     cfg, pts_a, pts_b, dims_a, dims_b)
        fit_ms = int(round((time.monotonic() - t_fit) * 1000))
        reg = outcome.to_registration_block()
        reg["selection_reason"] = fit.selection_reason
        reg["fit_diagnostics"] = fit.fit_diagnostics
        reg["transform_hash"] = _transform_hash(fit.matrix)
        base["registration"] = reg
        from .validate import residual_vector_lengths

        residual_lens = residual_vector_lengths(pts_a, pts_b, fit.matrix)
        base["points"] = []
        for e in points.entries:
            rv = float(residual_lens[int(e["m9_index"])])
            base["points"].append({
                "m9_index": int(e["m9_index"]),
                "m8_index": int(e["m8_index"]),
                "m7_index": int(e.get("m7_index", e.get("m8_index", 0))),
                "match_index_a": e.get("match_index_a"),
                "match_index_b": e.get("match_index_b"),
                "x_a": float(e["x_a"]), "y_a": float(e["y_a"]),
                "x_b": float(e["x_b"]), "y_b": float(e["y_b"]),
                "residual_px": round(rv, 9) if np.isfinite(rv) else None,
            })
        base["performance"] = {
            "selected_correspondence_count": len(points.entries),
            "input_dimensions": {"side_a": dims_a, "side_b": dims_b},
            "transform_fit_runtime_ms": fit_ms,
            "warp_runtime_ms": None,
            "total_runtime_ms": None,
        }

        warnings = list(points.warnings) + list(outcome.warnings)
        if not outcome.accepted:
            base["warnings"] = list(dict.fromkeys(warnings))
            base["decision"] = self._abstain_decision(
                states.NO_VALID_TRANSFORM,
                "The fitted transform did not pass the declared engineering "
                f"acceptance criteria: {'; '.join(outcome.issues)}.",
            )
            base["errors"] = list(outcome.issues)
            return

        # ---- warp / derived aligned output --------------------------------
        t_warp = time.monotonic()
        warp_block: dict[str, Any] = {
            "available": False,
            "output_dimensions": [int(dims_b["height"]), int(dims_b["width"])],
            "interpolation": cfg.warp.interpolation,
            "border_mode": cfg.warp.border_mode,
            "fill_value": cfg.warp.fill_value,
            "dtype": cfg.warp.dtype,
            "artifact_ref": None,
        }
        images = self._resolve_display_arrays(record.pair_id)
        src_a = images.get("a")
        src_b = images.get("b")
        if src_a is None or src_b is None:
            warnings.append(states.WARP_INPUT_MISSING)
            warp_block["reason"] = "Effective-plane display arrays are not available for both sides."
        else:
            out_h = int(dims_b["height"])
            out_w = int(dims_b["width"])
            b_shape = src_b["shape"]
            if b_shape != [out_h, out_w]:
                warnings.append(states.BOUNDS_WARNED)
            result = warp_to_frame(
                src_a["array"], fit.matrix, out_h, out_w, cfg,
                source_sha256=src_a["sha256"],
            )
            if "error" in result:
                warnings.append(states.WARP_OUTPUT_SKIPPED)
                warp_block["reason"] = f"Warp skipped: {result.get('reason')}"
            else:
                run_warp_dir = self._warp_dir(base["run_id"])
                run_warp_dir.mkdir(parents=True, exist_ok=True)
                warped = to_dtype(result["warped"], cfg.warp.dtype)
                valid_mask = np.asarray(result["valid_mask"], dtype=bool)
                atomic_write_npy(run_warp_dir / "registered_image.npy", warped)
                atomic_write_npy(run_warp_dir / "valid_mask.npy", valid_mask)
                write_preview_png(result["warped"], run_warp_dir / "registered_preview.png")
                valid_fraction = float(np.mean(valid_mask)) if valid_mask.size else 0.0

                try:
                    build_before_after(src_a["array"], src_b["array"], result["warped"],
                                       run_warp_dir / "visualization_before_after.png")
                    build_checkerboard(src_b["array"], result["warped"],
                                       run_warp_dir / "visualization_checkerboard.png")
                    build_difference_map(src_b["array"], result["warped"],
                                         run_warp_dir / "visualization_difference.png")
                    build_overlay(src_b["array"], result["warped"],
                                  run_warp_dir / "visualization_overlay.png")
                    build_residual_vectors(points.entries, fit.matrix, out_h, out_w,
                                           run_warp_dir / "visualization_residual_vectors.png")
                except Exception:  # noqa: BLE001 - visualization is best effort
                    warnings.append(states.HOLE_FILLED_VISUALIZATION)

                warp_block.update({
                    "available": True,
                    "output_dimensions": [int(out_h), int(out_w)],
                    "interpolation": result["interpolation"],
                    "border_mode": result["border_mode"],
                    "fill_value": result["fill_value"],
                    "dtype": str(warped.dtype),
                    "artifact_ref": _rel(self.settings.data_root_path, run_warp_dir),
                    "registered_image_rel": _rel(self.settings.data_root_path, run_warp_dir / "registered_image.npy"),
                    "valid_mask_rel": _rel(self.settings.data_root_path, run_warp_dir / "valid_mask.npy"),
                    "preview_rel": _rel(self.settings.data_root_path, run_warp_dir / "registered_preview.png"),
                    "valid_pixel_fraction": round(valid_fraction, 6),
                    "source_product_sha256": src_a["sha256"],
                })
                base["performance"]["warp_runtime_ms"] = int(round((time.monotonic() - t_warp) * 1000))
                if not isinstance(base.get("input_hashes"), dict):
                    base["input_hashes"] = {}
                base["input_hashes"]["image_a_display"] = src_a["sha256"]
                base["input_hashes"]["image_b_display"] = src_b["sha256"]

        base["warp"] = warp_block
        base["warnings"] = list(dict.fromkeys(warnings))
        state = states.SUCCESS_WITH_WARNINGS if warnings else states.SUCCESS
        base["decision"] = {
            "state": state,
            "reasons": list(dict.fromkeys(warnings)) if warnings else ["TRANSFORM_VALID"],
            "explanation": (
                "A declared geometric transform was estimated from the M8-selected "
                f"correspondences ({len(points.entries)}), validated independently "
                "against the declared engineering criteria"
                + (f" with warnings ({', '.join(sorted(set(warnings)))})" if warnings else "")
                + ". Internal registration residuals are geometric measurements in "
                "the effective matcher plane, not physical accuracy."
            ),
            "block_code": None, "abstain_code": None,
        }

    @staticmethod
    def _m7_decision_from_m8(m8_artifact: dict[str, Any]) -> dict[str, Any] | None:
        recovery = m8_artifact.get("recovery") or {}
        if isinstance(recovery, dict) and recovery.get("recovered_decision_hash"):
            return {"state": "ACCEPT",
                    "recovered_decision_hash": recovery["recovered_decision_hash"]}
        decision = m8_artifact.get("decision") or {}
        return {"state": decision.get("state"), "reason_codes": decision.get("reasons")}

    # ------------------------------------------------ decision helpers
    def _blocked(self, code: str, explanation: str) -> dict[str, Any]:
        return {
            "decision": self._blocked_decision(code, explanation),
            "explanation": explanation,
        }

    def _blocked_decision(self, code: str, explanation: str) -> dict[str, Any]:
        return {
            "state": states.BLOCKED, "reasons": [code],
            "explanation": explanation,
            "block_code": code, "abstain_code": None,
        }

    def _abstain_decision(self, code: str, explanation: str) -> dict[str, Any]:
        return {
            "state": states.ABSTAIN, "reasons": [code],
            "explanation": explanation,
            "block_code": None, "abstain_code": code,
        }

    # ------------------------------------------------ base artifact
    def _base_artifact(self, record, run_id: str, created_at: str) -> dict[str, Any]:
        cfg = self.config
        return {
            "run_id": run_id,
            "pair_id": record.pair_id,
            "experiment_id": None,
            "created_at_utc": created_at,
            "m8_run_id": None,
            "m7_trust_run_id": None,
            "matcher_run_id": None,
            "matcher_id": None,
            "upstream": {},
            "frame": None,
            "source_gate": {
                "data_source_gate": record.data_source_gate,
                "source_class_a": record.source_class_a,
                "source_class_b": record.source_class_b,
            },
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
            "data_source_gate": record.data_source_gate,
            "synthetically_derived": bool(_synthetic_like(record)),
            "configuration_id": cfg.configuration_id,
            "configuration_version": cfg.configuration_version,
            "configuration": _configuration_dict(cfg),
            "reference_status": cfg.reference_status,
            "decision": {
                "state": states.BLOCKED, "reasons": [],
                "explanation": "Pre-flight registration gates not satisfied.",
                "block_code": None, "abstain_code": None,
            },
            "registration": None,
            "warp": None,
            "performance": None,
            "input_validation": None,
            "input_hashes": None,
            "runtime_ms": None,
            "warnings": [],
            "errors": [],
            "environment": _environment_snapshot(),
        }

    # ------------------------------------------------ status
    def status(self, pair_id: str) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            raise NotFoundError(f"No pair with ID {pair_id} is registered.")
        cfg = self.config
        latest = self.latest_for_pair(pair_id)
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
                "model_preference": cfg.model.preference,
                "min_points_affine": cfg.model.min_points_affine,
                "min_points_homography": cfg.model.min_points_homography,
                "max_rmse_px": cfg.validation.max_rmse_px,
                "max_p95_px": cfg.validation.max_p95_px,
                "max_runtime_seconds": cfg.execution.max_runtime_seconds,
            },
            "requires": {
                "input": "ONE usable M8 spatial-selection artifact (SELECTED / SELECTED_WITH_WARNINGS)",
                "block_codes": list(states.BLOCK_CODES),
                "abstain_codes": list(states.ABSTAIN_CODES),
            },
            "latest_run": latest,
        }


def np_load_2d(path: Path) -> Any:
    arr = np_load(path)
    if arr is None or arr.ndim != 2:
        return None
    return arr


def np_load(path: Path) -> Any:
    import numpy as np  # noqa: PLC0415

    try:
        return np.load(path, allow_pickle=False)
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "RegistrationM9Service",
    "m9_run_summary",
]