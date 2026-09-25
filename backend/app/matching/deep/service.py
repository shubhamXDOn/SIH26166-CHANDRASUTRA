"""M4 strong-deep matcher — run, read and list deep matcher runs.

``DeepMatcherService`` mirrors the M3 ``BaselineMatcherService`` boundary:
it resolves validated M2 products, enforces the same source gates, persists
one artifact per run under ``metadata/m4_deep_matching/<run_id>.json``
(collision-safe ids, never overwritten), persists a candidate line
visualization through existing artifact conventions, and exposes an honest
capability surface. The heavy lifting (SuperPoint + SuperGlue through the
shared M3 candidate-correspondence contract) lives in ``contract.py``.

Core honesty rules:
    * a deep run only ever reports CANDIDATE correspondences — model-native
      scores are recorded witnesses of the assignment probability, never a
      trust / accuracy verdict (the M4 Trust Gate stays authoritative);
    * availability is probed live at run time; a missing runtime or an
      un-provisioned or wrong (SHA-256-mismatched) checkpoint produces an
      explicit BLOCKED outcome instead of a simulated success;
    * deep runs consume the SAME validated M2 products and the SAME resize
      discipline (``max_image_dimension``) as the classical baseline so the
      comparison is fair and fully recorded;
    * input plane is preserved: the payload records native product
      dimensions, effective (model input) dimensions and the linear
      transforms between grid / effective / native frames.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ...config import m4_deep_config
from ...hardening import atomic_write_json
from ...logging_conf import get_logger
from ...pairs import PairRegistry
from ..baseline import (
    BaselineMatcherService,
    _as_u8_2d,
    _describe_mask,
    _now_utc,
    _resize_recorded,
    _safe_run_id,
    json_load,
    run_summary,
)
from . import probe
from .contract import DeepMatcherInput, MATCHER_ID, run_deep_contract

logger = get_logger(__name__)

DEEP_MATCHER_IDS: tuple[str, ...] = (MATCHER_ID,)


class DeepMatcherService:
    """Run, persist, read and list M4 strong-deep matcher runs."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self.cfg = m4_deep_config()
        self.metadata_root = (
            self.settings.data_root_path / "metadata" / "m4_deep_matching"
        )
        self.viz_dir = self.settings.data_root_path / "derived" / "visualizations" / "deep_matching"
        self.model_dir = self.settings.m8_model_path
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def capabilities_public(self) -> dict[str, Any]:
        return probe.capabilities_public(model_dir=self.model_dir)

    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def visualization_path(self, run_id: str) -> Path | None:
        art = self.read(run_id)
        if not art:
            return None
        rel = art.get("visualization_rel")
        if not rel:
            return None
        p = self.settings.data_root_path / rel
        return p if p.is_file() else None

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            raise OSError(f"Refusing to overwrite existing M4 deep artifact {path.name}")
        atomic_write_json(path, payload)
        return path

    def read(self, run_id: str) -> dict[str, Any] | None:
        if not _safe_run_id(run_id):
            return None
        path = self.artifact_path(run_id)
        if not path.is_file():
            return None
        try:
            return json_load(path)
        except Exception:  # noqa: BLE001
            return None

    def read_any(self, run_id: str) -> dict[str, Any] | None:
        """Read a baseline or deep run artifact (the shared M3 read surface)."""
        from ..baseline import BaselineMatcherService

        baseline = BaselineMatcherService(self.settings).read(run_id)
        if baseline is not None:
            return baseline
        return self.read(run_id)

    def list_runs(self, pair_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.metadata_root.is_dir():
            return rows
        for p in sorted(self.metadata_root.glob("*.json")):
            try:
                payload = json_load(p)
            except Exception:  # noqa: BLE001
                continue
            if payload.get("pair_id") != pair_id:
                continue
            rows.append(run_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ inputs
    def resolve_processed_inputs(self, pair_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reuse the M3 baseline input resolution (same validated M2 products)."""
        return BaselineMatcherService(self.settings).resolve_processed_inputs(pair_id)

    # ------------------------------------------------------------------ run
    def run(self, pair_id: str, matcher_id: str) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            from ...errors import NotFoundError

            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        if matcher_id not in DEEP_MATCHER_IDS:
            from ...errors import ValidationError

            raise ValidationError(
                f"Unknown deep matcher {matcher_id!r}; choose one of {list(DEEP_MATCHER_IDS)}."
            )

        created_at = _now_utc()
        run_id = self._new_run_id(pair_id, matcher_id)
        cfg_snapshot = self._configuration_snapshot()
        env = self._environment_snapshot()

        cap = probe.probe_superpoint_superglue(self.model_dir)
        if not cap["available"]:
            payload = {
                "run_id": run_id,
                "pair_id": pair_id,
                "matcher_id": matcher_id,
                "created_at_utc": created_at,
                "status": "BLOCKED",
                "state": "BLOCKED",
                "error_code": cap["status"],  # MODEL/BLOCKED_* code
                "error_detail": cap["not_available_detail"],
                "configuration_id": self.cfg.get("configuration_id", "DM-M4-001"),
                "configuration": cfg_snapshot,
                "environment": env,
                "source_gate": self._source_gate(record),
                "synthetically_derived": self._synthetic(record),
                "capability": cap,
                "matcher": None,
            }
            self.write_artifact(run_id, payload)
            return payload

        blocker, inputs = self.resolve_processed_inputs(pair_id)
        if blocker is not None:
            payload = {
                "run_id": run_id,
                "pair_id": pair_id,
                "matcher_id": matcher_id,
                "created_at_utc": created_at,
                "status": "BLOCKED",
                "state": "BLOCKED",
                "error_code": blocker["error_code"],
                "error_detail": blocker["reason"],
                "configuration_id": self.cfg.get("configuration_id", "DM-M4-001"),
                "configuration": cfg_snapshot,
                "environment": env,
                "source_gate": self._source_gate(record),
                "synthetically_derived": self._synthetic(record),
                "matcher": None,
            }
            self.write_artifact(run_id, payload)
            return payload

        execution = (self.cfg.get("defaults") or {}).get("execution", {})
        max_dim = int(execution.get("max_image_dimension", 1024))
        img_a, mask_a, info_a = _resize_recorded(inputs["a"]["array"], inputs["a"]["mask"], max_dim)
        img_b, mask_b, info_b = _resize_recorded(inputs["b"]["array"], inputs["b"]["mask"], max_dim)

        matcher_input = DeepMatcherInput(
            matcher_id=matcher_id,
            image_a=img_a,
            image_b=img_b,
            mask_a=mask_a,
            mask_b=mask_b,
            configuration=dict(execution),
        )
        out = run_deep_contract(matcher_input, cfg=self.cfg, model_dir=self.model_dir)

        matcher_payload = asdict(out)

        viz_rel = None
        try:
            viz_rel = self._write_visualization(run_id, out, img_a, img_b)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Deep visualization failed for %s: %s", run_id, exc)

        payload: dict[str, Any] = {
            "run_id": run_id,
            "pair_id": pair_id,
            "matcher_id": matcher_id,
            "created_at_utc": created_at,
            "state": "SUCCESS" if out.status == "SUCCESS" else out.status,
            "status": out.status,
            "error_code": out.error_code,
            "error_detail": out.error_detail,
            "configuration_id": self.cfg.get("configuration_id", "DM-M4-001"),
            "configuration": cfg_snapshot,
            "environment": env,
            "source_gate": self._source_gate(record),
            "synthetically_derived": self._synthetic(record),
            "model_family": out.model_family,
            "input": {
                "image_a": {
                    **info_a,
                    **self._side_input_meta(inputs["a"], info_a),
                    "sha256": inputs["a"]["sha256"],
                    "model_plane": "EFFECTIVE_MODEL_INPUT",
                },
                "image_b": {
                    **info_b,
                    **self._side_input_meta(inputs["b"], info_b),
                    "sha256": inputs["b"]["sha256"],
                    "model_plane": "EFFECTIVE_MODEL_INPUT",
                },
            },
            "license": (
                "Candidate correspondences are observations, not verified alignment; "
                "model-native scores are observations, not confidence. The M4 Trust Gate "
                "remains authoritative and no result here is a scientific accuracy or "
                "trust verdict."
            ),
            "visualization_rel": viz_rel,
            "matcher": matcher_payload,
        }
        self.write_artifact(run_id, payload)
        return payload

    def _configuration_snapshot(self) -> dict[str, Any]:
        from .contract import _configuration_snapshot

        return _configuration_snapshot(self.cfg)

    def _environment_snapshot(self) -> dict[str, Any]:
        from .contract import _environment_snapshot

        return _environment_snapshot()

    def _side_input_meta(self, side_input: dict[str, Any], resize_info: dict[str, Any]) -> dict[str, Any]:
        arr = side_input["array"]
        mask = side_input.get("mask")
        return {
            "source_product": {
                "sensor": side_input.get("sensor"),
                "rel": str(Path(side_input["display_path"]).relative_to(self.settings.data_root_path))
                if side_input.get("display_path") else None,
            },
            "native_dimensions": {"height": int(arr.shape[0]), "width": int(arr.shape[1])},
            "mask": _describe_mask(mask),
        }

    def _source_gate(self, record) -> dict[str, Any]:
        return {
            "data_source_gate": record.data_source_gate,
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
        }

    def _synthetic(self, record) -> bool:
        from ..baseline import BaselineMatcherService

        return BaselineMatcherService(self.settings)._synthetic(record)

    def _new_run_id(self, pair_id: str, matcher_id: str) -> str:
        while True:
            run_id = f"m4-{pair_id}-{matcher_id}-{uuid.uuid4().hex[:8]}"
            if not self.artifact_path(run_id).exists():
                return run_id

    def _write_visualization(
        self, run_id: str, out, img_a: np.ndarray, img_b: np.ndarray
    ) -> str | None:
        import cv2
        import numpy as np

        viz_cfg = (self.cfg.get("defaults") or {}).get("visualization", {})
        if not viz_cfg.get("enabled", True):
            return None
        cands = out.correspondences
        if not cands:
            return None
        max_lines = int(viz_cfg.get("max_lines", 120))
        max_side = int(viz_cfg.get("max_side_px", 960))

        a = _as_u8_2d(img_a)
        b = _as_u8_2d(img_b)

        def scale_for(img: np.ndarray, limit: int) -> tuple[np.ndarray, float]:
            longest = max(img.shape)
            if longest <= limit:
                return img, 1.0
            f = limit / float(longest)
            nh = max(int(round(img.shape[0] * f)), 1)
            nw = max(int(round(img.shape[1] * f)), 1)
            return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA), f

        a, fa = scale_for(a, max_side)
        b, fb = scale_for(b, max_side)
        gap = 12
        height = max(a.shape[0], b.shape[0])
        canvas = np.zeros((height, a.shape[1] + gap + b.shape[1], 3), dtype=np.uint8)
        canvas[: a.shape[0], : a.shape[1]] = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
        canvas[: b.shape[0], a.shape[1] + gap:] = cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)

        offset_x = a.shape[1] + gap
        lines = cands[:max_lines]
        # Distinct warm palette (magenta/cyan, red-dominant) so a DEEP candidate
        # visualization is visually differentiated from the classical baseline.
        rng = np.random.default_rng(20260901)
        for i, c in enumerate(lines):
            color = (int(rng.integers(40, 200)), int(rng.integers(60, 220)), int(rng.integers(120, 255)))
            p1 = (int(c["x_a"] * fa), int(c["y_a"] * fa))
            p2 = (int(c["x_b"] * fb) + offset_x, int(c["y_b"] * fb))
            cv2.line(canvas, p1, p2, color, 1, cv2.LINE_AA)
        if a.shape[0] < height:
            canvas[a.shape[0]:, :a.shape[1]] = 20
        if b.shape[0] < height:
            canvas[b.shape[0]:, offset_x:] = 20

        self.viz_dir.mkdir(parents=True, exist_ok=True)
        vpath = self.viz_dir / f"{run_id}.png"
        ok = cv2.imwrite(str(vpath), canvas)
        if not ok:
            return None
        return str(Path(vpath).relative_to(self.settings.data_root_path))