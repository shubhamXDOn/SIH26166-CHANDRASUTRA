"""M9 REGISTRATION — selected-correspondence input validation.

M8 selected points originate from an ACCEPTED M7 gate, but M9 still validates
its own inputs: NaN/Inf, duplicate/degenerate geometry, insufficient points and
collinear source or target sets are never assumed away because an upstream stage
accepted. The smallest usable finite set is retained; every removal is recorded
as warning evidence so the caller can decide honestly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .config import RegistrationM9Config
from . import states


@dataclass
class PointValidation:
    ok: bool
    entries: list[dict[str, Any]] = field(default_factory=list)
    pts_a: np.ndarray | None = None
    pts_b: np.ndarray | None = None
    dropped_non_finite: int = 0
    dropped_duplicates: int = 0
    n_input: int = 0
    n_usable: int = 0
    warnings: list[str] = field(default_factory=list)
    abstain_code: str | None = None
    explanation: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "n_input": self.n_input,
            "n_usable": self.n_usable,
            "dropped_non_finite": self.dropped_non_finite,
            "dropped_duplicates": self.dropped_duplicates,
            "warnings": list(self.warnings),
            "abstain_code": self.abstain_code,
            "explanation": self.explanation,
        }


def _finite_mask(coords: np.ndarray) -> np.ndarray:
    if coords.size == 0:
        return np.ones(0, dtype=bool)
    return np.isfinite(coords).all(axis=1)


def _is_collinear(pts: np.ndarray) -> bool:
    n = len(pts)
    if n < 3:
        return False
    centered = pts - pts.mean(axis=0)
    try:
        _, s, _ = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError:
        return True
    if s.size < 2 or s[1] < 1e-12:
        return True
    return bool(s[1] / max(s[0], 1e-12) < 1e-6)


def validate_selected_points(
    selected: list[dict[str, Any]],
    cfg: RegistrationM9Config,
) -> PointValidation:
    """Validate M8-selected correspondence records for registration fitting.

    Deterministic: NaN/Inf entries are dropped first, then duplicate
    (rounded-to-6dp) coordinate pairs keep the first occurrence, and the
    remaining set is checked for size and collinearity in both frames.
    """
    n_input = len(selected)
    if n_input == 0:
        return PointValidation(
            ok=False, abstain_code=states.INSUFFICIENT_SELECTED_POINTS,
            n_input=0, n_usable=0,
            explanation="The M8 selection record carries no selected correspondences.",
        )

    coords = np.zeros((n_input, 4), dtype=np.float64)
    for i, e in enumerate(selected):
        coords[i] = [
            float(e.get("x_a", np.nan)), float(e.get("y_a", np.nan)),
            float(e.get("x_b", np.nan)), float(e.get("y_b", np.nan)),
        ]

    finite = _finite_mask(coords)
    dropped_non_finite = int(np.sum(~finite))
    keep_idx = np.where(finite)[0]

    # duplicate geometry (round to 6 dp, keep-first) in either frame
    seen: set[tuple] = set()
    unique_idx: list[int] = []
    for j in keep_idx:
        key = (
            round(float(coords[j, 0]), 6), round(float(coords[j, 1]), 6),
            round(float(coords[j, 2]), 6), round(float(coords[j, 3]), 6),
        )
        if key not in seen:
            seen.add(key)
            unique_idx.append(int(j))
    dropped_duplicates = int(len(keep_idx) - len(unique_idx))

    usable = np.asarray(unique_idx, dtype=int)
    pts_a = coords[usable][:, :2]
    pts_b = coords[usable][:, 2:]
    entries = [dict(selected[int(j)]) for j in usable]
    warnings: list[str] = []

    if dropped_non_finite > 0:
        warnings.append(states.NON_FINITE_POINTS_DROPPED)
    if dropped_duplicates > 0:
        warnings.append(states.DUPLICATE_POINTS_DROPPED)

    # never re-number silently: m9_index is re-assigned deterministically but the
    # original m8_index / m7_index / match indices are preserved verbatim
    for idx, e in enumerate(entries):
        e["m9_index"] = idx
        e["m8_index"] = int(e.get("m8_index", idx))
        if "x_a" in e:
            e["x_a"] = float(e["x_a"])
            e["y_a"] = float(e["y_a"])
            e["x_b"] = float(e["x_b"])
            e["y_b"] = float(e["y_b"])

    min_pts = max(cfg.model.min_points_affine, cfg.model.min_points_homography)
    if len(entries) < min_pts:
        return PointValidation(
            ok=False, entries=entries, pts_a=pts_a, pts_b=pts_b,
            dropped_non_finite=dropped_non_finite, dropped_duplicates=dropped_duplicates,
            n_input=n_input, n_usable=len(entries), warnings=warnings,
            abstain_code=states.INSUFFICIENT_SELECTED_POINTS,
            explanation=(
                f"Only {len(entries)} usable selected correspondences "
                f"(minimum fit requirement {min_pts})."
            ),
        )

    if _is_collinear(pts_a) or _is_collinear(pts_b):
        return PointValidation(
            ok=False, entries=entries, pts_a=pts_a, pts_b=pts_b,
            dropped_non_finite=dropped_non_finite, dropped_duplicates=dropped_duplicates,
            n_input=n_input, n_usable=len(entries), warnings=warnings,
            abstain_code=states.DEGENERATE_GEOMETRY,
            explanation=(
                "Source or target point set is collinear/degenerate; a declared "
                "2-D transform cannot be identified from rank-deficient geometry."
            ),
        )

    return PointValidation(
        ok=True, entries=entries, pts_a=pts_a, pts_b=pts_b,
        dropped_non_finite=dropped_non_finite, dropped_duplicates=dropped_duplicates,
        n_input=n_input, n_usable=len(entries), warnings=warnings,
        explanation=f"{len(entries)} usable correspondences after deterministic cleaning.",
    )


__all__ = ["PointValidation", "validate_selected_points"]