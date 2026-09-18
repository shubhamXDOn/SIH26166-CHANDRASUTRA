"""Simple non-maximum suppression over a score map (M8 deep matcher support).

A 5-by-5 max pool keeps only pixels that equal their local max (within the
pool radius). Deterministic, numpy-only, and batch-agnostic enough for the
SuperPoint keypoint selection step.
"""

from __future__ import annotations

import numpy as np


def simple_nms(scores: np.ndarray, radius: int) -> np.ndarray:
    """Local-max NMS on a 2D score map.

    Returns a score map where every pixel that is not the strict maximum of its
    ``(2*radius+1)``-sized neighbourhood is suppressed to 0.
    """
    if score_map_is_empty(scores):
        return np.zeros_like(scores, dtype=np.float64)
    nms = scores.copy()
    if radius <= 0:
        return nms
    h, w = nms.shape
    pool = np.zeros_like(nms, dtype=np.float64)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            shifted = np.roll(nms, shift=(dy, dx), axis=(0, 1))
            if dy < 0:
                shifted[dy:, :] = -np.inf
            elif dy > 0:
                shifted[:dy, :] = -np.inf
            if dx < 0:
                shifted[:, dx:] = -np.inf
            elif dx > 0:
                shifted[:, :dx] = -np.inf
            pool = np.maximum(pool, shifted)
    nms[~np.isfinite(pool)] = 0.0
    nms[nms < pool] = 0.0
    return nms


def score_map_is_empty(scores: np.ndarray) -> bool:
    return scores is None or np.asarray(scores).size == 0