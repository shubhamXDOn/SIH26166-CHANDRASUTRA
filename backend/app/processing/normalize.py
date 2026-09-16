"""Display normalization (explicitly not radiometric) for M2."""

from __future__ import annotations

import numpy as np


def display_normalize(arr: np.ndarray, mask: np.ndarray, low_pct: float, high_pct: float) -> tuple[np.ndarray, dict]:
    """Percentile-stretch valid pixels to the full 16-bit range.

    This is a DISPLAY remap only — it deliberately carries no claim about
    physical radiance, reflectance or calibration. Values outside the window
    are clipped; masked pixels are set to 0 in the display product and are
    tracked by the mask everywhere else.
    """
    arr_f = np.asarray(arr, dtype=np.float64)
    valid = mask == 0
    valid_values = arr_f[valid]
    if valid_values.size == 0:
        lo, hi = 0.0, 1.0
    else:
        lo = float(np.percentile(valid_values, low_pct))
        hi = float(np.percentile(valid_values, high_pct))
    if hi - lo < 1e-6:
        hi = lo + 1.0
    out = np.clip((arr_f - lo) / (hi - lo) * 65535.0, 0.0, 65535.0).astype(np.uint16)
    out[~valid] = 0
    stats = {
        "mode": "percentile_1_99",
        "low_percentile": low_pct,
        "high_percentile": high_pct,
        "low_dn": round(lo, 2),
        "high_dn": round(hi, 2),
        "out_dtype": str(out.dtype),
        "masked_set_to_zero": True,
        "note": "Display normalization only — no radiometric calibration claim.",
    }
    return out, stats