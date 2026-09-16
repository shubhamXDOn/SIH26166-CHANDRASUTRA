"""Matcher adapters — a platform-neutral contract over OpenCV local features (M3).

Contract:
    * ``match()`` ingests two sensor-native window arrays (uint8, display) plus
      per-window invalid masks and returns an ``AdapterOutput`` with measured
      match statistics and raw correspondence pairs (pre-filtering).
    * Adapters are registered in a predictable order (registry); the adaptive
      engine and the API surface iterate over that same order so behaviour is
      deterministic.
    * ``matcher_score`` is defined once here as ``1 - distance/ref`` where
      ``ref`` is the configured acceptance ceiling for that strategy. It is a
      *normalized descriptor distance complement* — NOT a scientific
      confidence and never a trust verdict (that is the M4 Trust Gate's job).

Available in this build (OpenCV 5.0.0):
    * SIFT      -> strategy 'sift', family 'classical_local'  (scale-invariant, L2 descriptors)
    * ORB       -> strategy 'orb',  family 'robust_local'     (binary descriptors, Hamming)
A deep-optional boundary ("deep_optional") exists but is UNAVAILABLE here; the
adaptive engine treats it as a constraint-failed alternative instead of
fabricating results.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

from ..logging_conf import get_logger

logger = get_logger(__name__)

STRATEGY_ORDER: list[str] = ["sift", "orb", "deep_optional"]

FAMILY_LABELS: dict[str, str] = {
    "classical_local": "Classical local features",
    "robust_local": "Robust local features",
    "deep_optional": "Deep learning matcher (optional)",
}


@dataclass
class AdapterOutput:
    """Result of one matcher run over one tile pair (pre candidate filtering)."""

    strategy: str
    family: str
    keypoints_a: int = 0
    keypoints_b: int = 0
    raw_candidates: int = 0
    ratio_rejected: int = 0
    distance_rejected: int = 0
    cross_rejected: int = 0
    pairs_i_a: np.ndarray | None = None
    pairs_i_b: np.ndarray | None = None
    pairs_distance: np.ndarray | None = None
    feature_scale_a: np.ndarray | None = None
    feature_scale_b: np.ndarray | None = None
    orientations_a: np.ndarray | None = None
    keypoint_x_a: np.ndarray | None = None
    keypoint_y_a: np.ndarray | None = None
    keypoint_x_b: np.ndarray | None = None
    keypoint_y_b: np.ndarray | None = None
    matcher_ok: bool = True
    failure_detail: str = ""
    score_reference: float = 1.0
    runtime_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "family": self.family,
            "keypoints_a": self.keypoints_a,
            "keypoints_b": self.keypoints_b,
            "matching": {
                "raw_candidates": self.raw_candidates,
                "ratio_rejected": self.ratio_rejected,
                "distance_rejected": self.distance_rejected,
                "cross_rejected": self.cross_rejected,
                "surviving_pairs": 0 if self.pairs_i_a is None else int(len(self.pairs_i_a)),
            },
            "matcher_ok": self.matcher_ok,
            "failure_detail": self.failure_detail or None,
            "score_reference": self.score_reference,
            "runtime_ms": round(self.runtime_ms, 3),
            "warnings": self.warnings,
        }


class MatcherAdapter(ABC):
    """Adapter contract every concrete matcher implements."""

    strategy_id: str = ""
    family: str = ""
    display_name: str = ""
    descriptor_kind: str = ""  # 'floating' | 'binary'

    @abstractmethod
    def is_available(self) -> bool:
        """Live capability check (no fabricated availability)."""

    def capability_public(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy_id,
            "family": self.family,
            "family_label": FAMILY_LABELS.get(self.family, self.family),
            "descriptor_kind": self.descriptor_kind,
            "available": self.is_available(),
            "note": "Routing scores are what-to-try weights, never a scientific verdict.",
        }

    @abstractmethod
    def match(
        self,
        img_a: np.ndarray,
        img_b: np.ndarray,
        mask_a: np.ndarray | None,
        mask_b: np.ndarray | None,
        *,
        detector_params: dict[str, Any],
        matching_params: dict[str, Any],
    ) -> AdapterOutput:
        """Match two grayscale uint8 windows (valid where mask == 0)."""


# ---------------------------------------------------------------------------
# Shared OpenCV implementation
# ---------------------------------------------------------------------------
def _valid_mask(mask: np.ndarray | None, shape) -> np.ndarray:
    """Convert the invalid mask (0 = valid) into an OpenCV mask (255 = used)."""
    if mask is None:
        return np.full(shape, 255, dtype=np.uint8)
    m = np.asarray(mask)
    return np.where(m == 0, 255, 0).astype(np.uint8)


def _as_u8(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr)
    if a.dtype == np.uint8:
        return a
    if a.dtype in (np.uint16, np.int16):
        return (a >> 8).astype(np.uint8)
    return (np.clip(a, 0, 255)).astype(np.uint8)


class _CvFeatureMatcher(MatcherAdapter):
    """Shared machinery for OpenCV detector/matcher adapters."""

    descriptor_kind = "floating"
    _norm_type = cv2.NORM_L2

    def detector(self, params: dict[str, Any]):
        raise NotImplementedError

    def _score_reference(self, matching_params: dict[str, Any]) -> float:
        return float(matching_params.get("max_distance", 1.0))

    def match(
        self,
        img_a: np.ndarray,
        img_b: np.ndarray,
        mask_a: np.ndarray | None,
        mask_b: np.ndarray | None,
        *,
        detector_params: dict[str, Any],
        matching_params: dict[str, Any],
    ) -> AdapterOutput:
        start = time.perf_counter()
        a = _as_u8(img_a)
        b = _as_u8(img_b)
        mka = _valid_mask(mask_a, a.shape)
        mkb = _valid_mask(mask_b, b.shape)
        cross_check = bool(matching_params.get("cross_check", True))
        ratio_threshold = float(matching_params.get("ratio_threshold", 0.8))
        max_distance = float(matching_params.get("max_distance", 100.0))
        ref = self._score_reference(matching_params)
        warnings: list[str] = []

        try:
            det = self.detector(detector_params)
            kp_a, des_a = det.detectAndCompute(a, mka)
            kp_b, des_b = det.detectAndCompute(b, mkb)
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - start) * 1000.0
            return AdapterOutput(
                strategy=self.strategy_id,
                family=self.family,
                matcher_ok=False,
                failure_detail=f"Detector raised: {exc}",
                score_reference=ref,
                runtime_ms=elapsed,
            )

        n_a = len(kp_a) if kp_a is not None else 0
        n_b = len(kp_b) if kp_b is not None else 0
        if n_a < 2 or n_b < 2 or des_a is None or des_b is None or des_a.shape[0] < 2 or des_b.shape[0] < 2:
            elapsed = (time.perf_counter() - start) * 1000.0
            return AdapterOutput(
                strategy=self.strategy_id,
                family=self.family,
                keypoints_a=n_a,
                keypoints_b=n_b,
                matcher_ok=False,
                failure_detail=f"Not enough features to match (A={n_a}, B={n_b}).",
                score_reference=ref,
                runtime_ms=elapsed,
            )

        matcher = cv2.BFMatcher(self._norm_type, crossCheck=False)
        knn = matcher.knnMatch(des_a, des_b, k=2)

        i_a: list[int] = []
        i_b: list[int] = []
        distances: list[float] = []
        ratio_rejected = 0
        for pair in knn:
            if not pair:
                continue
            best = pair[0]
            second = pair[1] if len(pair) > 1 else None
            if second is not None and best.distance >= second.distance * ratio_threshold:
                ratio_rejected += 1
                continue
            i_a.append(best.queryIdx)
            i_b.append(best.trainIdx)
            distances.append(float(best.distance))

        if cross_check and i_a:
            des_b_sel = des_b[np.array(i_b)]
            rev = cv2.BFMatcher(self._norm_type, crossCheck=False).knnMatch(des_b_sel, des_a, k=1)
            keep = [
                idx
                for idx, rev_list in enumerate(rev)
                if rev_list and rev_list[0].trainIdx == i_a[idx] and distances[idx] <= max_distance
            ]
            distance_rejected = sum(1 for idx, d in enumerate(distances) if d > max_distance)
            cross_rejected_here = len(distances) - distance_rejected - len(keep)
            i_a = [i_a[idx] for idx in keep]
            i_b = [i_b[idx] for idx in keep]
            distances = [distances[idx] for idx in keep]
        else:
            if i_a:
                keep2 = [idx for idx, d in enumerate(distances) if d <= max_distance]
                distance_rejected = len(distances) - len(keep2)
                i_a = [i_a[idx] for idx in keep2]
                i_b = [i_b[idx] for idx in keep2]
                distances = [distances[idx] for idx in keep2]
            cross_rejected_here = 0

        pairs_i_a = np.asarray(i_a, dtype=np.int64)
        pairs_i_b = np.asarray(i_b, dtype=np.int64)
        pairs_distance = np.asarray(distances, dtype=np.float64)
        elapsed = (time.perf_counter() - start) * 1000.0

        out = AdapterOutput(
            strategy=self.strategy_id,
            family=self.family,
            keypoints_a=n_a,
            keypoints_b=n_b,
            raw_candidates=len(knn),
            ratio_rejected=ratio_rejected,
            distance_rejected=distance_rejected,
            cross_rejected=cross_rejected_here,
            pairs_i_a=pairs_i_a if len(pairs_i_a) else None,
            pairs_i_b=pairs_i_b if len(pairs_i_b) else None,
            pairs_distance=pairs_distance if len(pairs_distance) else None,
            feature_scale_a=np.asarray([kp.size for kp in kp_a], dtype=np.float64),
            feature_scale_b=np.asarray([kp.size for kp in kp_b], dtype=np.float64),
            orientations_a=np.asarray([kp.angle for kp in kp_a], dtype=np.float64),
            keypoint_x_a=np.asarray([kp.pt[0] for kp in kp_a], dtype=np.float64),
            keypoint_y_a=np.asarray([kp.pt[1] for kp in kp_a], dtype=np.float64),
            keypoint_x_b=np.asarray([kp.pt[0] for kp in kp_b], dtype=np.float64),
            keypoint_y_b=np.asarray([kp.pt[1] for kp in kp_b], dtype=np.float64),
            matcher_ok=True,
            score_reference=ref,
            runtime_ms=elapsed,
            warnings=warnings,
        )
        return out


class SiftAdapter(_CvFeatureMatcher):
    strategy_id = "sift"
    family = "classical_local"
    display_name = "SIFT (scale-invariant feature transform)"
    descriptor_kind = "floating"
    _norm_type = cv2.NORM_L2

    def is_available(self) -> bool:
        return hasattr(cv2, "SIFT_create")

    def detector(self, params: dict[str, Any]):
        kw = {
            "nfeatures": int(params.get("nfeatures", 2000)),
            "contrastThreshold": float(params.get("contrast_threshold", 0.04)),
            "edgeThreshold": float(params.get("edge_threshold", 10.0)),
            "sigma": float(params.get("sigma", 1.6)),
        }
        return cv2.SIFT_create(**kw)


class OrbAdapter(_CvFeatureMatcher):
    strategy_id = "orb"
    family = "robust_local"
    display_name = "ORB (oriented FAST & rotated BRIEF)"
    descriptor_kind = "binary"
    _norm_type = cv2.NORM_HAMMING

    def is_available(self) -> bool:
        return hasattr(cv2, "ORB_create")

    def detector(self, params: dict[str, Any]):
        kw = {
            "nfeatures": int(params.get("nfeatures", 2000)),
            "scaleFactor": float(params.get("scale_factor", 1.2)),
            "nlevels": int(params.get("nlevels", 8)),
            "edgeThreshold": int(params.get("edge_threshold", 31)),
            "fastThreshold": int(params.get("fast_threshold", 20)),
        }
        return cv2.ORB_create(**kw)


class DeepOptionalAdapter(MatcherAdapter):
    """Declared boundary for a future deep matcher.

    The availability probe is a capability check, not a placeholder: no deep
    model is checked into this repository, so the adapter is truthfully
    UNAVAILABLE and the routing engine records it as constraint-failed.
    """

    strategy_id = "deep_optional"
    family = "deep_optional"
    display_name = "Deep learning matcher (optional — not available)"
    descriptor_kind = "ai"

    def is_available(self) -> bool:
        return False

    def match(self, *args: Any, **kwargs: Any) -> AdapterOutput:
        return AdapterOutput(
            strategy=self.strategy_id,
            family=self.family,
            matcher_ok=False,
            failure_detail="Deep matcher is not available in this build (no model checked in).",
        )


_REGISTRY: dict[str, MatcherAdapter] = {}


def _register(adapter: MatcherAdapter) -> None:
    _REGISTRY[adapter.strategy_id] = adapter


_register(SiftAdapter())
_register(OrbAdapter())
_register(DeepOptionalAdapter())


def get_adapter(strategy_id: str) -> MatcherAdapter | None:
    return _REGISTRY.get(strategy_id)


def available_matchers() -> list[MatcherAdapter]:
    return [_REGISTRY[sid] for sid in STRATEGY_ORDER if sid in _REGISTRY and _REGISTRY[sid].is_available()]


def all_matchers() -> list[MatcherAdapter]:
    return [_REGISTRY[sid] for sid in STRATEGY_ORDER if sid in _REGISTRY]


def register_adapter(adapter: MatcherAdapter) -> None:
    """Hook for tests to inject fakes/slow adapters into the deterministic registry."""
    _REGISTRY[adapter.strategy_id] = adapter
    if adapter.strategy_id not in STRATEGY_ORDER:
        STRATEGY_ORDER.append(adapter.strategy_id)