"""M8 deep matcher adapter — SuperPoint + SuperGlue, wired via the M8 capability.

The adapter truthfully reports availability:
    * RUNTIME_UNAVAILABLE          -> torch/torchvision missing
    * MODEL_WEIGHTS_NOT_CONFIGURED -> weights not present on disk
    * MODEL_WEIGHTS_INVALID        -> checkpoint present but shape-incompatible
    * available                    -> real inference runs with the real graph

Model weights are NEVER downloaded. The pipeline looks for files
``superpoint_v1.pth`` and ``superglue_outdoor_v1.pth`` under
``<data_root>/models/m8`` (the ``m8_model_path`` resolution).
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..base import BaseMatcherAdapter, M8AdapterOutput
from ..device import resolve_device, torch_available
from .superpoint import SuperPointNet
from .superglue import SuperGlueNet

SUPERPOINT_WEIGHT_FILENAMES = ("superpoint_v1.pth",)
SUPERGLUE_WEIGHT_FILENAMES = ("superglue_outdoor_v1.pth", "superglue_indoor_v1.pth")


@dataclass
class DeepWeightPaths:
    model_dir: str
    superpoint: str = ""
    superglue: str = ""

    def present(self) -> bool:
        return bool(self.superpoint) and bool(self.superglue)


def _first_existing(model_dir: Path, filenames: tuple[str, ...]) -> str:
    for name in filenames:
        candidate = model_dir / name
        if candidate.is_file():
            return str(candidate)
    return ""


def resolve_weights(model_dir: str | Path | None) -> DeepWeightPaths:
    """Find optional deep model weights without ever creating anything."""
    if not model_dir:
        return DeepWeightPaths(model_dir="")
    base = Path(model_dir)
    if not base.is_dir():
        return DeepWeightPaths(model_dir=str(base))
    return DeepWeightPaths(
        model_dir=str(base),
        superpoint=_first_existing(base, SUPERPOINT_WEIGHT_FILENAMES),
        superglue=_first_existing(base, SUPERGLUE_WEIGHT_FILENAMES),
    )


class SuperPointSuperGlueAdapter(BaseMatcherAdapter):
    """Deep correspondence matcher over real SuperPoint+SuperGlue networks."""

    matcher_id = "superpoint_superglue"
    family = "deep"
    display_name = "SuperPoint + SuperGlue (deep graph matcher)"
    requires_weights = True
    supports_cpu = True
    supports_gpu = True
    runtime_name = "torch"

    def __init__(self, model_dir: str = "", device: str = "auto"):
        self.model_dir = model_dir
        self.requested_device = device
        self._spin = None  # SuperPointNet
        self._glue = None  # SuperGlueNet
        self._runtime_checked: bool = False
        self._weights_checked: bool = False
        self._weights_valid: bool | None = None
        self._weights_error: str = ""
        self.device_used = ""

    # -- capability ---------------------------------------------------------
    def runtime_available(self) -> bool:
        if not self._runtime_checked:
            self._runtime_checked = True
            self._runtime_ok = torch_available()
        return self._runtime_ok

    def torchvision_ok(self) -> bool:
        from ..device import torchvision_available

        return torchvision_available()

    def weights_available(self) -> bool:
        if not self._weights_checked:
            self._weights_checked = True
            self._weight_paths = resolve_weights(self.model_dir)
            self._weights_exist = self._weight_paths.present()
        return self._weights_exist

    def reason_if_unavailable(self) -> str:
        if not self.runtime_available():
            return "RUNTIME_UNAVAILABLE"
        if not self.torchvision_ok():
            return "RUNTIME_UNAVAILABLE"
        if not self.weights_available():
            return "MODEL_WEIGHTS_NOT_CONFIGURED"
        if self._weights_valid is False:
            return "MODEL_WEIGHTS_INVALID"
        return ""

    def is_available(self) -> bool:
        return not self.reason_if_unavailable()

    # -- lifecycle ----------------------------------------------------------
    def prepare(self) -> None:
        if not self.is_available():
            raise RuntimeError(self.reason_if_unavailable())
        device = resolve_device(self.requested_device)["device"]
        self.device_used = device
        paths = self._weight_paths
        try:
            self._spin = SuperPointNet({"nms_radius": 4, "max_keypoints": 4096})
            self._spin.build(device)
            self._spin.load_weights(paths.superpoint)
            self._glue = SuperGlueNet({"sinkhorn_iterations": 50, "match_threshold": 0.2})
            self._glue.build(device)
            self._glue.load_weights(paths.superglue)
            self._weights_valid = True
        except Exception as exc:  # noqa: BLE001
            self._weights_valid = False
            self._weights_error = str(exc)
            self._spin = None
            self._glue = None
            raise RuntimeError(f"MODEL_WEIGHTS_INVALID: {exc}") from exc
        finally:
            self._weight_paths = paths

    def cleanup(self) -> None:
        self._spin = None
        self._glue = None

    # -- matching -----------------------------------------------------------
    def match(self, tile_pair: dict[str, Any]) -> M8AdapterOutput:
        if self._spin is None or self._glue is None:
            return M8AdapterOutput(
                matcher_id=self.matcher_id,
                matcher_family=self.family,
                matcher_version=self.matcher_version,
                ok=False,
                failure_code="MODEL_WEIGHTS_NOT_CONFIGURED",
                failure_detail="SuperPoint/SuperGlue weights not loaded — prepare() was not called or weights are missing.",
            )
        try:
            r_a = self._spin.extract(tile_pair["window_a"])
            r_b = self._spin.extract(tile_pair["window_b"])
            result = self._glue.match(
                r_a["descriptors"], r_b["descriptors"],
                r_a["keypoints"], r_b["keypoints"],
                r_a["scores"], r_b["scores"],
            )
        except Exception as exc:  # noqa: BLE001
            return M8AdapterOutput(
                matcher_id=self.matcher_id,
                matcher_family=self.family,
                matcher_version=self.matcher_version,
                ok=False,
                failure_code="MATCHER_FAILED",
                failure_detail=f"{type(exc).__name__}: {exc}",
            )
        pairs = result["matches"]
        if pairs is None or len(pairs) == 0:
            return M8AdapterOutput(
                matcher_id=self.matcher_id,
                matcher_family=self.family,
                matcher_version=self.matcher_version,
                ok=True,
                runtime_ms=0.0,
                note="SuperGlue produced no mutual matches above threshold.",
            )
        kp0 = r_a["keypoints"]
        kp1 = r_b["keypoints"]
        x_a = kp0[pairs[:, 0], 0]
        y_a = kp0[pairs[:, 0], 1]
        x_b = kp1[pairs[:, 1], 0]
        y_b = kp1[pairs[:, 1], 1]
        return M8AdapterOutput(
            matcher_id=self.matcher_id,
            matcher_family=self.family,
            matcher_version=self.matcher_version,
            ok=True,
            x_a=x_a, y_a=y_a, x_b=x_b, y_b=y_b,
            matcher_confidence=np.asarray(result["mscores"], dtype=np.float64),
            model_identity="SuperPoint+SuperGlue",
            weights_identity=self._identity_of(self._weight_paths),
            note="SuperGlue mutual matches — observational correspondence, not verified truth.",
        )

    def _identity_of(self, paths: DeepWeightPaths) -> str:
        import hashlib

        parts = []
        for label, path in (("sp", paths.superpoint), ("glue", paths.superglue)):
            if path:
                try:
                    h = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
                except OSError:
                    h = "unreadable"
                parts.append(f"{label}={h}")
        return ";".join(parts) or "none"

    def normalize_result(self, tile_pair: dict[str, Any], output: M8AdapterOutput) -> M8AdapterOutput:
        output.model_identity = output.model_identity or "SuperPoint+SuperGlue"
        output.weights_identity = output.weights_identity or self._identity_of(
            getattr(self, "_weight_paths", DeepWeightPaths(""))
        )
        return output