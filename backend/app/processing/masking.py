"""Invalid-data masking (M2).

Builds an explicit, bit-flagged invalid-data mask from the raw array. The
mask is a first-class derived artifact stored alongside the preprocessed
product — every downstream statistic can re-derive it and never has to guess
which pixels were excluded.
"""

from __future__ import annotations

import numpy as np

MASK_NAN_INF = 1
MASK_SATURATED = 2
MASK_NEGATIVE = 4
MASK_UNKNOWN = 8


def flag_names(value: int) -> list[str]:
    names: list[str] = []
    if value & MASK_NAN_INF:
        names.append("NAN_INF")
    if value & MASK_SATURATED:
        names.append("SATURATED")
    if value & MASK_NEGATIVE:
        names.append("NEGATIVE")
    if value & MASK_UNKNOWN:
        names.append("UNKNOWN")
    return names


def build_invalid_mask(arr: np.ndarray, masking_params: dict | None) -> tuple[np.ndarray, dict]:
    """Return (mask uint8, stats). mask==0 means valid; each value is a bitfield."""
    masking = masking_params or {}
    arr_f = np.asarray(arr)
    mask = np.zeros(arr_f.shape, dtype=np.uint8)
    finite = np.isfinite(arr_f)

    if masking.get("nan_inf", True):
        mask = mask | np.where(~finite, MASK_NAN_INF, 0).astype(np.uint8)

    if masking.get("saturated", True):
        dn = float(masking.get("saturation_dn", 65535))
        mask = mask | np.where(finite & (arr_f >= dn), MASK_SATURATED, 0).astype(np.uint8)

    if masking.get("negative", True):
        mask = mask | np.where(finite & (np.asarray(arr) < 0), MASK_NEGATIVE, 0).astype(np.uint8)

    invalid = mask != 0
    total = int(np.prod(arr_f.shape)) if arr_f.size else 0
    stats = {
        "total": total,
        "valid": int(np.count_nonzero(~invalid)),
        "invalid": int(np.count_nonzero(invalid)),
        "valid_fraction": round(float(np.count_nonzero(~invalid)) / total, 6) if total else 0.0,
        "nan_inf": int(np.count_nonzero((mask & MASK_NAN_INF) != 0)),
        "saturated": int(np.count_nonzero((mask & MASK_SATURATED) != 0)),
        "negative": int(np.count_nonzero((mask & MASK_NEGATIVE) != 0)),
        "unknown": int(np.count_nonzero((mask & MASK_UNKNOWN) != 0)),
        "policy": masking,
    }
    return mask, stats