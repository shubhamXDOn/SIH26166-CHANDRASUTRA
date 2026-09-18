"""M8 unified correspondence contract (Section 6).

Every matcher output is normalised into ONE canonical structure. Each
correspondence carries identity, coordinates, tile and coordinate-space
annotations; optional matcher observations are labelled as observations and are
never allowed to be interpreted downstream as truth/accuracy/confidence.

Validation steps (Section 6):
    * finite coordinates
    * coordinate bounds (inside the source/target windows, plus margin)
    * tile identity
    * source/target space
    * duplicate correspondences
    * mask validity
    * deterministic ordering
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .base import M8AdapterOutput
from .states import TileRunOutcome

REQUIRED_SPACES = ("sensor_a_window", "sensor_b_window")


@dataclass
class ValidatedCandidates:
    """One normalised, validated candidate set from one matcher run."""

    matcher_id: str
    matcher_family: str
    matcher_version: str
    tile_id: str
    source_space: str = "sensor_a_window"
    target_space: str = "sensor_b_window"
    x_a: np.ndarray | None = None
    y_a: np.ndarray | None = None
    x_b: np.ndarray | None = None
    y_b: np.ndarray | None = None
    descriptor_distance: np.ndarray | None = None
    matcher_confidence: np.ndarray | None = None
    match_rank: np.ndarray | None = None
    funnel: dict[str, int] = field(default_factory=dict)
    outcome: str = TileRunOutcome.NO_CANDIDATES.value
    synthetically_derived: bool = False
    model_identity: str = ""
    weights_identity: str = ""

    @property
    def count(self) -> int:
        return 0 if self.x_a is None else int(len(self.x_a))

    def to_canonical(self) -> list[dict[str, Any]]:
        """Machine-readable canonical record (deterministic ordering)."""
        if self.x_a is None:
            return []
        n = self.count
        dist = np.asarray(self.descriptor_distance) if self.descriptor_distance is not None else None
        conf = np.asarray(self.matcher_confidence) if self.matcher_confidence is not None else None
        rank = np.asarray(self.match_rank) if self.match_rank is not None else None
        rows: list[dict[str, Any]] = []
        for i in range(n):
            row: dict[str, Any] = {
                "x_a": round(float(self.x_a[i]), 4),
                "y_a": round(float(self.y_a[i]), 4),
                "x_b": round(float(self.x_b[i]), 4),
                "y_b": round(float(self.y_b[i]), 4),
                "matcher_id": self.matcher_id,
                "matcher_family": self.matcher_family,
                "tile_id": self.tile_id,
                "source_space": self.source_space,
                "target_space": self.target_space,
            }
            obs: dict[str, Any] = {}
            if dist is not None:
                obs["descriptor_distance"] = round(float(dist[i]), 6)
            if conf is not None:
                obs["matcher_confidence"] = round(float(conf[i]), 6)
            if rank is not None:
                obs["match_rank"] = int(rank[i])
            if obs:
                row["matcher_observations"] = obs
            rows.append(row)
        return rows

    def summary(self) -> dict[str, Any]:
        return {
            "matcher_id": self.matcher_id,
            "matcher_family": self.matcher_family,
            "matcher_version": self.matcher_version,
            "tile_id": self.tile_id,
            "source_space": self.source_space,
            "target_space": self.target_space,
            "count": self.count,
            "outcome": self.outcome,
            "funnel": dict(self.funnel),
            "synthetically_derived": self.synthetically_derived,
            "note": "Candidate correspondences are observations — no accuracy/trust verdict (M4 Trust Gate remains authoritative).",
        }


def _finite(arr: np.ndarray) -> bool:
    return bool(np.all(np.isfinite(arr)))


def validate_and_normalize(
    output: M8AdapterOutput,
    *,
    tile_id: str,
    width_a: int,
    height_a: int,
    width_b: int,
    height_b: int,
    mask_a: np.ndarray | None,
    mask_b: np.ndarray | None,
    max_correspondences: int,
    require_finite: bool = True,
    require_mask_valid: bool = True,
    border_margin: int = 4,
    max_dimension: int = 2048,
) -> ValidatedCandidates:
    """Validate matcher output against the unified contract and order it.

    Returns a ``ValidatedCandidates`` set; funnel counts record each explicit
    rejection stage so the population attrition is always inspectable.
    """
    funnel: dict[str, int] = {"raw": output.count}
    x_a, y_a, x_b, y_b = (np.asarray(output.x_a), np.asarray(output.y_a),
                          np.asarray(output.x_b), np.asarray(output.y_b))

    valid = np.ones(output.count, dtype=bool)
    if output.count == 0 or any(a.size == 0 for a in (x_a, y_a, x_b, y_b)):
        funnel.update({"nonfinite_rejected": 0, "bounds_rejected": 0,
                       "mask_rejected": 0, "duplicates_rejected": 0,
                       "usable": 0})
        return ValidatedCandidates(
            matcher_id=output.matcher_id, matcher_family=output.matcher_family,
            matcher_version=output.matcher_version, tile_id=tile_id,
            outcome=TileRunOutcome.NO_CANDIDATES.value, funnel=funnel,
            synthetically_derived=output.synthetically_derived,
            model_identity=output.model_identity, weights_identity=output.weights_identity,
        )

    # 1) finite coordinates + observations
    dist = np.asarray(output.descriptor_distance) if output.descriptor_distance is not None else np.full(output.count, np.nan)
    conf = np.asarray(output.matcher_confidence) if output.matcher_confidence is not None else np.full(output.count, np.nan)
    finite = (
        np.isfinite(x_a) & np.isfinite(y_a) & np.isfinite(x_b) & np.isfinite(y_b)
    )
    if require_finite:
        if output.descriptor_distance is not None:
            finite &= np.isfinite(dist)
        if output.matcher_confidence is not None:
            finite &= np.isfinite(conf)
    funnel["nonfinite_rejected"] = int(np.count_nonzero(~finite))
    valid &= finite

    # 2) coordinate bounds against window dimensions (with border margin)
    margin = border_margin
    bounds = (
        (x_a >= margin) & (x_a <= width_a - 1 - margin)
        & (y_a >= margin) & (y_a <= height_a - 1 - margin)
        & (x_b >= margin) & (x_b <= width_b - 1 - margin)
        & (y_b >= margin) & (y_b <= height_b - 1 - margin)
        & (width_a > 0) & (height_a > 0) & (width_b > 0) & (height_b > 0)
    )
    funnel["bounds_rejected"] = int(np.count_nonzero(valid & ~bounds))
    valid &= bounds

    # 3) mask validity (0 == valid pixel) — evaluated only on rows that already
    #    passed finite + bounds so NaN coordinates never feed the mask sampler.
    if require_mask_valid and mask_a is not None and mask_b is not None:
        ma_, mb_ = np.asarray(mask_a), np.asarray(mask_b)
        mask_ok = np.zeros(valid.shape, dtype=bool)
        survivors = np.nonzero(valid)[0]
        if len(survivors):
            iy_a = np.clip(np.round(y_a[survivors]).astype(np.int64), 0, ma_.shape[0] - 1)
            ix_a = np.clip(np.round(x_a[survivors]).astype(np.int64), 0, ma_.shape[1] - 1)
            iy_b = np.clip(np.round(y_b[survivors]).astype(np.int64), 0, mb_.shape[0] - 1)
            ix_b = np.clip(np.round(x_b[survivors]).astype(np.int64), 0, mb_.shape[1] - 1)
            mask_ok[survivors] = (ma_[iy_a, ix_a] == 0) & (mb_[iy_b, ix_b] == 0)
        funnel["mask_rejected"] = int(np.count_nonzero(valid & ~mask_ok))
        valid &= mask_ok
    else:
        funnel["mask_rejected"] = 0

    # 4) duplicates (rounded coordinate identity, deterministic first-keeps)
    surv = np.nonzero(valid)[0]
    if len(surv):
        key = np.round(np.stack([x_a[surv], y_a[surv], x_b[surv], y_b[surv]], axis=1) * 100).astype(np.int64)
        _, first_idx = np.unique(key, axis=0, return_index=True)
        funnel["duplicates_rejected"] = int(len(surv) - len(first_idx))
        keep_idx = surv[first_idx]
    else:
        keep_idx = np.arange(0, dtype=np.int64)
        funnel["duplicates_rejected"] = 0

    # 5) deterministic ordering: ascending descriptor distance primary, then
    #    stable rounded-coordinate tuple as tie-break (byte-deterministic).
    if len(keep_idx):
        dist_k = np.round(np.asarray(dist[keep_idx]), 6) if (dist is not None and np.any(np.isfinite(dist[keep_idx]))) else None
        keys = [x_a[keep_idx], y_a[keep_idx], x_b[keep_idx], y_b[keep_idx]]
        if dist_k is not None:
            keys.append(dist_k)
        order = np.lexsort(keys)  # last key is the primary sort key
        keep_idx = keep_idx[order]

    # 6) cap, then record usable count.
    keep_idx = keep_idx[: max_correspondences] if max_correspondences > 0 else keep_idx
    funnel["max_correspondences"] = max_correspondences
    funnel["usable"] = int(len(keep_idx))

    outcome = TileRunOutcome.CANDIDATES.value if funnel["usable"] > 0 else TileRunOutcome.NO_CANDIDATES.value
    return ValidatedCandidates(
        matcher_id=output.matcher_id,
        matcher_family=output.matcher_family,
        matcher_version=output.matcher_version,
        tile_id=tile_id,
        x_a=x_a[keep_idx], y_a=y_a[keep_idx], x_b=x_b[keep_idx], y_b=y_b[keep_idx],
        descriptor_distance=dist[keep_idx] if np.any(np.isfinite(dist)) else None,
        matcher_confidence=conf[keep_idx] if np.any(np.isfinite(conf)) else None,
        match_rank=(np.arange(len(keep_idx)) + 1) if len(keep_idx) else None,
        funnel=funnel,
        outcome=outcome,
        synthetically_derived=output.synthetically_derived,
        model_identity=output.model_identity,
        weights_identity=output.weights_identity,
    )


def write_candidates_artifact(path, candidates: ValidatedCandidates) -> dict:
    """Persist the canonical candidate set deterministically (JSON array of
    canonical records). Returns the payload written."""
    import json

    payload = {
        "schema": "M8-canonical-candidates/v1",
        "tile_id": candidates.tile_id,
        "matcher_id": candidates.matcher_id,
        "matcher_family": candidates.matcher_family,
        "source_space": candidates.source_space,
        "target_space": candidates.target_space,
        "synthetically_derived": candidates.synthetically_derived,
        "count": candidates.count,
        "candidates": candidates.to_canonical(),
        "note": "Candidate correspondences are matcher observations, not verified truth.",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)
    return payload