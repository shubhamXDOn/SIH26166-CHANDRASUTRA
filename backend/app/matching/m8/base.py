"""Base matcher adapter contract for M8 (Section 7).

Every matcher — classical, deep, or declared-unavailable — implements the same
adapter interface so downstream M4/M5/M6 code does not care which matcher
generated the candidates. Availability comes from a real capability probe, never
from "the package is installed".
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class M8AdapterOutput:
    """Normalized raw output of ONE matcher run over ONE tile pair.

    Coordinates are expressed in the sensor-native window coordinate space
    (columns=x, rows=y). All matcher-origin values are observations and are
    explicitly NOT trust/accuracy/scientific-confidence.
    """

    matcher_id: str
    matcher_family: str  # "classical" | "deep"
    matcher_version: str = ""
    ok: bool = True
    failure_code: str = ""
    failure_detail: str = ""
    x_a: np.ndarray | None = None
    y_a: np.ndarray | None = None
    x_b: np.ndarray | None = None
    y_b: np.ndarray | None = None
    descriptor_distance: np.ndarray | None = None
    matcher_confidence: np.ndarray | None = None
    match_rank: np.ndarray | None = None
    runtime_ms: float = 0.0
    runtime_name: str = ""
    synthetically_derived: bool = False
    model_identity: str = ""
    weights_identity: str = ""
    note: str = ""

    @property
    def count(self) -> int:
        if self.x_a is None:
            return 0
        return int(len(self.x_a))

    def observation_keys(self) -> dict[str, Any]:
        """Matcher observations, explicitly labelled as observational."""
        obs: dict[str, Any] = {}
        if self.descriptor_distance is not None:
            obs["descriptor_distance"] = np.round(np.asarray(self.descriptor_distance), 6).tolist()
        if self.matcher_confidence is not None:
            obs["matcher_confidence"] = np.round(np.asarray(self.matcher_confidence), 6).tolist()
        if self.match_rank is not None:
            obs["match_rank"] = [int(rank) for rank in np.asarray(self.match_rank)]
        return obs


class BaseMatcherAdapter(ABC):
    """Common adapter interface (M8 spec section 5 + 7)."""

    matcher_id: str = ""
    family: str = ""  # "classical" | "deep"
    display_name: str = ""
    requires_weights: bool = False
    supports_cpu: bool = True
    supports_gpu: bool = False
    max_recommended_dimension: int = 2048
    runtime_name: str = ""

    # -- capability ---------------------------------------------------------
    def runtime_available(self) -> bool:
        """Whether the execution runtime dependency is present."""
        return True

    def weights_available(self) -> bool:
        """Whether the required model weights actually exist on disk."""
        return not self.requires_weights

    def reason_if_unavailable(self) -> str:
        """Stable code explaining an unavailable state (or empty when ready)."""
        if not self.runtime_available():
            return "RUNTIME_UNAVAILABLE"
        if self.requires_weights and not self.weights_available():
            return "MODEL_WEIGHTS_NOT_CONFIGURED"
        return ""

    @abstractmethod
    def is_available(self) -> bool:
        """Live, honest capability check (never fabricated)."""

    def capability(self) -> dict[str, Any]:
        """Recorded capability entry (M8 spec section 5)."""
        return {
            "matcher_id": self.matcher_id,
            "family": self.family,
            "display_name": self.display_name,
            "available": self.is_available(),
            "device": self.device_hint(),
            "requires_weights": self.requires_weights,
            "weights_available": self.weights_available(),
            "runtime_available": self.runtime_available(),
            "supports_cpu": self.supports_cpu,
            "supports_gpu": self.supports_gpu,
            "max_recommended_dimension": self.max_recommended_dimension,
            "reason_if_unavailable": self.reason_if_unavailable(),
        }

    def device_hint(self) -> str:
        from .device import resolve_device

        return resolve_device()["device"]

    # -- lifecycle ----------------------------------------------------------
    def prepare(self) -> None:
        """Load runtime/model state (called once before a run). Real models are
        only loaded when their weights exist; otherwise availability is false."""

    def cleanup(self) -> None:
        """Release runtime/model state (best-effort)."""

    # -- matching -----------------------------------------------------------
    @abstractmethod
    def match(self, tile_pair: dict[str, Any]) -> M8AdapterOutput:
        """Run the real matcher over one tile pair and return normalized output.

        ``tile_pair`` provides pre-loaded ``window_a``/``window_b``,
        ``mask_a``/``mask_b`` plus ``tile_a``/``tile_b`` window widths/heights
        and identifying information. Implementations MUST NOT fabricate output.
        """

    def normalize_result(self, tile_pair: dict[str, Any], output: M8AdapterOutput) -> M8AdapterOutput:
        """Post-process raw output (identity by default). Concrete adapters may
        restrict to the recommended dimension or drop dustbin-only matches."""
        return output

    @property
    def matcher_version(self) -> str:
        return f"{self.family}.{self.matcher_id}"


def timed_match(adapter: BaseMatcherAdapter, tile_pair: dict[str, Any]):
    """Run ``match`` and attach a measured runtime_ms in seconds->ms."""
    start = time.perf_counter()
    try:
        output = adapter.match(tile_pair)
    except Exception as exc:  # noqa: BLE001
        output = M8AdapterOutput(
            matcher_id=adapter.matcher_id,
            matcher_family=adapter.family,
            matcher_version=adapter.matcher_version,
            ok=False,
            failure_code="MATCHER_FAILED",
            failure_detail=f"{type(exc).__name__}: {exc}",
        )
    output.runtime_ms = round((time.perf_counter() - start) * 1000.0, 3)
    return output