"""Candidate correspondence model + explicit filtering (M3).

A candidate is one observed keypoint correspondence between a window on
sensor A and a window on sensor B. Candidates are observations, NOT verified
truth: no geometric verification, no inlier model, no accuracy claim —
registration/verification is delegated to the M4 Trust Gate.

Filtering is explicit and recorded:
    raw candidates -> [adapter: ratio/distance/cross-check]
    -> valid-area (mask) rejection -> border rejection -> duplicate rejection
    -> candidate set.

Candidate artifacts are stored efficiently (per-tile .npz) with a JSON
summary carrying the measured statistics and the decision that produced them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .adapters import AdapterOutput
from .config import MatcherConfig
from .states import TileOutcome

NPZ_KEYS = [
    "x_a", "y_a", "x_b", "y_b",
    "matcher_score", "descriptor_distance",
    "feature_scale_a", "feature_scale_b", "orientation_a",
]


@dataclass
class CandidateSet:
    strategy: str
    family: str
    license: str = "candidate = observation; not a verified correspondence, not a trust verdict."
    x_a: np.ndarray | None = None
    y_a: np.ndarray | None = None
    x_b: np.ndarray | None = None
    y_b: np.ndarray | None = None
    matcher_score: np.ndarray | None = None
    descriptor_distance: np.ndarray | None = None
    feature_scale_a: np.ndarray | None = None
    feature_scale_b: np.ndarray | None = None
    orientation_a: np.ndarray | None = None
    outcome: str = TileOutcome.NO_CANDIDATES.value
    threshold_counts: dict[str, int] = field(default_factory=dict)
    selection_notes: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return 0 if self.x_a is None else int(len(self.x_a))

    def diagnostics(self) -> dict[str, Any]:
        if self.count == 0:
            return {
                "count": 0,
                "threshold": self.threshold_counts.get("candidate_set_threshold", 0),
                "bbox_a": None,
                "bbox_b": None,
                "spatial_distribution": None,
            }
        xa, ya = self.x_a, self.y_a
        xb, yb = self.x_b, self.y_b
        dist = self.descriptor_distance
        score = self.matcher_score
        # Occupied quadrants over each window, as a simple spatial-dispersion
        # observation (never a geometric-consistency model).
        mins = (xa.min(), ya.min(), xb.min(), yb.min())
        maxs = (xa.max(), ya.max(), xb.max(), yb.max())
        return {
            "count": self.count,
            "threshold": self.threshold_counts.get("candidate_set_threshold", 0),
            "bbox_a": {"x_min": float(mins[0]), "y_min": float(mins[1]),
                       "x_max": float(maxs[0]), "y_max": float(maxs[1])},
            "bbox_b": {"x_min": float(mins[2]), "y_min": float(mins[3]),
                       "x_max": float(maxs[2]), "y_max": float(maxs[3])},
            "spatial_distribution": {
                "median_x_a": float(np.median(xa)), "median_y_a": float(np.median(ya)),
                "median_x_b": float(np.median(xb)), "median_y_b": float(np.median(yb)),
            },
            "distance": {
                "min": float(np.min(dist)), "median": float(np.median(dist)),
                "max": float(np.max(dist)), "mean": float(np.mean(dist)),
            },
            "matcher_score": {
                "min": float(np.min(score)), "median": float(np.median(score)),
                "max": float(np.max(score)), "mean": float(np.mean(score)),
            },
            "feature_scale_a": {
                "min": float(np.min(self.feature_scale_a)),
                "max": float(np.max(self.feature_scale_a)),
                "median": float(np.median(self.feature_scale_a)),
            },
        }

    def to_npz_dict(self) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        for key in NPZ_KEYS:
            arr = getattr(self, key)
            if arr is not None:
                out[key] = np.asarray(arr, dtype=np.float64)
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "family": self.family,
            "license": self.license,
            "count": self.count,
            "outcome": self.outcome,
            "threshold_counts": dict(self.threshold_counts),
            "diagnostics": self.diagnostics(),
        }


def filter_candidates(
    output: AdapterOutput,
    mask_a: np.ndarray | None,
    mask_b: np.ndarray | None,
    *,
    tile_a: "Any",
    tile_b: "Any",
    cfg: MatcherConfig,
) -> CandidateSet:
    """Apply the recorded candidate filters to an adapter's raw matches.

    ``tile_a``/``tile_b`` expose ``width``/``height`` (the window dims that the
    keypoint coordinates are expressed in).
    """
    threshold_counts: dict[str, int] = {}
    threshold_counts["raw_candidates"] = output.raw_candidates
    if (not output.matcher_ok) or output.pairs_i_a is None or len(output.pairs_i_a) == 0:
        return CandidateSet(
            strategy=output.strategy,
            family=output.family,
            outcome=TileOutcome.NO_CANDIDATES.value if output.matcher_ok else _outcome_from_failure(output.failure_detail),
            threshold_counts=threshold_counts,
            selection_notes=[output.failure_detail] if output.failure_detail else [],
        )

    x_a = output.keypoint_x_a[output.pairs_i_a]
    y_a = output.keypoint_y_a[output.pairs_i_a]
    x_b = output.keypoint_x_b[output.pairs_i_b]
    y_b = output.keypoint_y_b[output.pairs_i_b]
    dist = output.pairs_distance
    score_ref = output.score_reference or 1.0
    matcher_score = np.clip(1.0 - (dist / score_ref), 0.0, 1.0)
    scale_a = output.feature_scale_a[output.pairs_i_a]
    scale_b = output.feature_scale_b[output.pairs_i_b]
    orient_a = output.orientations_a[output.pairs_i_a]

    n = len(x_a)
    finite = (
        np.isfinite(x_a) & np.isfinite(y_a)
        & np.isfinite(x_b) & np.isfinite(y_b)
        & np.isfinite(dist)
        & np.isfinite(matcher_score)
        & np.isfinite(scale_a) & np.isfinite(scale_b) & np.isfinite(orient_a)
    )
    keep = finite
    threshold_counts["nonfinite_rejected"] = int(n - np.count_nonzero(finite))

    # 1) valid-area rejection: the keypoint must sit on a valid pixel in BOTH windows.
    if mask_a is not None and mask_b is not None:
        ma = np.asarray(mask_a)
        mb = np.asarray(mask_b)
        iy_a = np.clip(np.round(y_a).astype(np.int64), 0, ma.shape[0] - 1)
        ix_a = np.clip(np.round(x_a).astype(np.int64), 0, ma.shape[1] - 1)
        iy_b = np.clip(np.round(y_b).astype(np.int64), 0, mb.shape[0] - 1)
        ix_b = np.clip(np.round(x_b).astype(np.int64), 0, mb.shape[1] - 1)
        valid_a = ma[iy_a, ix_a] == 0
        valid_b = mb[iy_b, ix_b] == 0
        mask_rejected = int(np.count_nonzero(keep) - np.count_nonzero(keep & valid_a & valid_b))
        keep &= valid_a & valid_b
    else:
        mask_rejected = 0
    threshold_counts["mask_rejected"] = mask_rejected

    # 2) border rejection: stay away from window edges (edge artifacts). Only
    #    applied when the recorded tile window dimensions are known.
    margin = cfg.border_margin_px
    w_a, h_a = int(tile_a.get("width", 0)), int(tile_a.get("height", 0))
    w_b, h_b = int(tile_b.get("width", 0)), int(tile_b.get("height", 0))
    if w_a > 0 and h_a > 0 and w_b > 0 and h_b > 0:
        interior = (
            (x_a >= margin) & (y_a >= margin) & (x_a <= w_a - 1 - margin) & (y_a <= h_a - 1 - margin)
            & (x_b >= margin) & (y_b >= margin) & (x_b <= w_b - 1 - margin) & (y_b <= h_b - 1 - margin)
        )
    else:
        interior = np.ones(n, dtype=bool)
    after_mask = int(np.count_nonzero(keep))
    keep &= interior
    threshold_counts["border_margin_rejected"] = after_mask - int(np.count_nonzero(keep))

    # 3) duplicate rejection (rounded coordinate identity). Only the first
    #    occurrence of each unique rounded (x_a, y_a, x_b, y_b) tuple survives.
    surviving = np.nonzero(keep)[0]
    if len(surviving):
        rounded = np.round(np.stack([
            x_a[surviving] * 100, y_a[surviving] * 100,
            x_b[surviving] * 100, y_b[surviving] * 100,
        ], axis=1)).astype(np.int64)
        _, first_idx = np.unique(rounded, axis=0, return_index=True)
        threshold_counts["duplicates_rejected"] = int(len(surviving) - len(first_idx))
        keep_idx = surviving[first_idx]
    else:
        keep_idx = np.arange(0, dtype=np.int64)
        threshold_counts["duplicates_rejected"] = 0

    threshold_counts["candidate_set"] = int(len(keep_idx))

    tx = x_a[keep_idx]
    ty = y_a[keep_idx]
    ux = x_b[keep_idx]
    uy = y_b[keep_idx]
    td = dist[keep_idx]
    ts = matcher_score[keep_idx]
    tsca = scale_a[keep_idx]
    tscb = scale_b[keep_idx]
    tori = orient_a[keep_idx]

    # Deterministic ordering by ascending descriptor distance.
    order = np.argsort(td, kind="stable")
    tx, ty, ux, uy, td, ts = tx[order], ty[order], ux[order], uy[order], td[order], ts[order]
    tsca, tscb, tori = tsca[order], tscb[order], tori[order]

    minimum = max(cfg.minimum_candidates, 1)
    outcome = TileOutcome.SUCCESS.value
    notes: list[str] = []
    if len(td) < minimum:
        outcome = TileOutcome.INSUFFICIENT_CANDIDATES.value
        notes.append(f"{len(td)} candidate(s) < minimum_candidates={cfg.minimum_candidates}.")
    threshold_counts["candidate_set_threshold"] = cfg.minimum_candidates

    return CandidateSet(
        strategy=output.strategy,
        family=output.family,
        x_a=tx, y_a=ty, x_b=ux, y_b=uy,
        matcher_score=ts, descriptor_distance=td,
        feature_scale_a=tsca, feature_scale_b=tscb, orientation_a=tori,
        outcome=outcome,
        threshold_counts=threshold_counts,
        selection_notes=notes,
    )


def _outcome_from_failure(detail: str) -> str:
    if "features" in detail.lower():
        return TileOutcome.NO_FEATURES.value
    return TileOutcome.MATCHER_FAILED.value


def write_candidate_artifacts(
    tile_dir: Path,
    *,
    match_tile_id: str,
    candidates: CandidateSet,
    decision: dict[str, Any],
) -> dict[str, Path]:
    """Persist per-tile candidate artifacts, returning {npz, json} paths."""
    tile_dir.mkdir(parents=True, exist_ok=True)
    npz_path = tile_dir / f"{match_tile_id}.npz"
    json_path = tile_dir / f"{match_tile_id}.json"
    if candidates.count:
        with open(npz_path, "wb") as handle:
            np.savez_compressed(handle, **candidates.to_npz_dict())
    summary = candidates.summary()
    payload = {
        "match_tile_id": match_tile_id,
        "summary": summary,
        "decision": decision,
        "note": (
            "Candidate correspondences are observations localised by the chosen matcher. "
            "They are NOT verified correspondences and carry no accuracy/trust verdict (Trust Gate = M4)."
        ),
    }
    tmp = json_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    tmp.replace(json_path)
    return {"npz": npz_path, "json": json_path}