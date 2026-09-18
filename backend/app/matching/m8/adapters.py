"""M8 matcher registry — classical wrappers over the M3 adapters plus deep
adapters, unified under one capability-checked interface (Section 5/7)."""

from __future__ import annotations

from typing import Any

import numpy as np

from .base import BaseMatcherAdapter, M8AdapterOutput
from .deep.adapter import SuperPointSuperGlueAdapter
from .deep.loftr import LoFTRAdapter

MATCHER_ORDER: list[str] = ["sift", "orb", "superpoint_superglue", "loftr"]


class ClassicalM8Adapter(BaseMatcherAdapter):
    """Wrap an M3 adapter (SIFT/ORB) behind the unified M8 interface.

    The M3 adapter already performs ratio-test, cross-check and max-distance
    filtering; coordinates are projected into the sensor-native window space.
    """

    family = "classical"

    def __init__(self, m3_adapter, *, detector_params: dict | None = None,
                 matching_params: dict | None = None):
        from ..adapters import MatcherAdapter

        if not isinstance(m3_adapter, MatcherAdapter):
            raise TypeError("ClassicalM8Adapter expects an M3 MatcherAdapter.")
        self.m3_adapter = m3_adapter
        self.matcher_id = m3_adapter.strategy_id
        self.display_name = m3_adapter.display_name
        self.descriptor_kind = m3_adapter.descriptor_kind
        self.family = "classical"
        self.runtime_name = m3_adapter.__class__.__name__
        self.detector_params = dict(detector_params or {})
        self.matching_params = dict(matching_params or {})

    def is_available(self) -> bool:
        return self.m3_adapter.is_available()

    def match(self, tile_pair: dict[str, Any]) -> M8AdapterOutput:
        out = self.m3_adapter.match(
            tile_pair["window_a"],
            tile_pair["window_b"],
            tile_pair.get("mask_a"),
            tile_pair.get("mask_b"),
            detector_params=self.detector_params,
            matching_params=self.matching_params,
        )
        if not out.matcher_ok:
            failure = out.failure_detail or "Matcher failed."
            code = "INSUFFICIENT" if "Not enough features" in failure else "MATCHER_FAILED"
            return M8AdapterOutput(
                matcher_id=self.matcher_id,
                matcher_family=self.family,
                matcher_version=self.matcher_version,
                ok=False,
                failure_code=code,
                failure_detail=failure,
                runtime_ms=out.runtime_ms,
            )
        if out.pairs_i_a is None or not len(out.pairs_i_a):
            return M8AdapterOutput(
                matcher_id=self.matcher_id,
                matcher_family=self.family,
                matcher_version=self.matcher_version,
                ok=True,
                runtime_ms=out.runtime_ms,
                note="No candidates survived M3 ratio/cross/distance filtering.",
            )
        x_a = np.asarray(out.keypoint_x_a, dtype=np.float64)[np.asarray(out.pairs_i_a)]
        y_a = np.asarray(out.keypoint_y_a, dtype=np.float64)[np.asarray(out.pairs_i_a)]
        x_b = np.asarray(out.keypoint_x_b, dtype=np.float64)[np.asarray(out.pairs_i_b)]
        y_b = np.asarray(out.keypoint_y_b, dtype=np.float64)[np.asarray(out.pairs_i_b)]
        return M8AdapterOutput(
            matcher_id=self.matcher_id,
            matcher_family=self.family,
            matcher_version=self.matcher_version,
            ok=True,
            x_a=x_a, y_a=y_a, x_b=x_b, y_b=y_b,
            descriptor_distance=np.asarray(out.pairs_distance, dtype=np.float64),
            runtime_ms=out.runtime_ms,
            note="Classical correspondence — descriptor-space observation, not a trust verdict.",
        )


_REGISTRY: dict[str, BaseMatcherAdapter] = {}


def _build_adapter(cfg: dict[str, Any], strategy: str, model_dir: str, device: str,
                   detector_params: dict, matching_params: dict) -> BaseMatcherAdapter:
    from ..adapters import get_adapter as m3_get_adapter

    m3 = m3_get_adapter(strategy)
    if m3 is None:
        raise KeyError(f"No M3 adapter for strategy '{strategy}'.")
    return ClassicalM8Adapter(m3, detector_params=detector_params, matching_params=matching_params)


def build_registry(cfg: dict[str, Any], model_dir: str = "", device: str = "auto") -> dict[str, BaseMatcherAdapter]:
    """Build the M8 registry from DeepMatcherConfig-derived dict.

    ``cfg`` is the ``defaults`` portion of the M8 configuration containing
    ``classical_strategies``, ``deep_strategies``, runtime ``device``, plus the
    detector/matching params for classical matchers.
    """
    from .capabilities import get_device, get_model_dir

    model_dir = model_dir or get_model_dir()
    device = device or get_device()
    reg: dict[str, BaseMatcherAdapter] = {}
    for strategy in (cfg.get("classical") or {}).get("strategies", ["sift", "orb"]):
        if strategy in reg:
            continue
        reg[strategy] = _build_adapter(
            cfg, strategy, model_dir, device,
            (cfg.get("classical") or {}).get(strategy, {}).get("detector", {}),
            (cfg.get("classical") or {}).get(strategy, {}).get("matching", {}),
        )
    for strategy in (cfg.get("deep") or {}).get("strategies", ["superpoint_superglue", "loftr"]):
        if strategy == "superpoint_superglue":
            reg[strategy] = SuperPointSuperGlueAdapter(model_dir=model_dir, device=device)
        elif strategy == "loftr":
            reg[strategy] = LoFTRAdapter(model_dir=model_dir, device=device)
    return reg


def get_matcher(registry: dict[str, BaseMatcherAdapter], matcher_id: str) -> BaseMatcherAdapter | None:
    return registry.get(matcher_id)


def matcher_ids(registry: dict[str, BaseMatcherAdapter]) -> list[str]:
    return [mid for mid in MATCHER_ORDER if mid in registry]