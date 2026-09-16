"""Scene-condition estimation per tile/product (M2).

Every indicator is a deterministic function of the actual tile data and
delivered as ``{value, status, quality, reason}`` so downstream code and the
UI can never mistake a number for a scientific conclusion. When computation
is not possible (empty valid area, blocked overlap) the indicator reports
status UNKNOWN/BLOCKED, quality "N/A" and a human reason — it is never
silently zeroed or guessed.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import ProcessingConfig


def _ind(value: Any, status: str, quality: Any, reason: str = "") -> dict[str, Any]:
    return {"value": value, "status": status, "quality": quality, "reason": reason}


def _quality_of(valid_fraction: float, empty_valid_fraction: float) -> tuple[str, float]:
    if valid_fraction < empty_valid_fraction:
        return "N/A", 0.0
    return "OK", round(float(np.clip(valid_fraction, 0.0, 1.0)), 3)


def analyze_tile(
    display: np.ndarray,
    mask: np.ndarray,
    *,
    tile_id: str,
    sensor: str,
    cfg: ProcessingConfig,
    too_small: bool = False,
) -> dict[str, Any]:
    """Compute per-tile condition indicators + a classification."""
    values = display[mask == 0].astype(np.float64)
    total = display.size
    valid_fraction = round(float(np.count_nonzero(mask == 0)) / total, 6) if total else 0.0
    low_dn = cfg.texture_low_dn
    high_dn = cfg.texture_high_dn

    if too_small or values.size == 0:
        reason = "TILE_TOO_SMALL" if too_small else "EMPTY_VALID_AREA"
        indicators = {
            "valid_coverage": _ind(valid_fraction, "BLOCKED" if too_small else "UNKNOWN", "N/A", reason),
            "illumination_range": _ind("N/A", "BLOCKED" if too_small else "UNKNOWN", "N/A", reason),
            "brightness_mean": _ind("N/A", "BLOCKED" if too_small else "UNKNOWN", "N/A", reason),
            "texture": _ind("N/A", "BLOCKED" if too_small else "UNKNOWN", "N/A", reason),
            "saturation": _ind("N/A", "BLOCKED" if too_small else "UNKNOWN", "N/A", reason),
        }
        classification = {
            "level": "BLOCKED" if too_small else "UNKNOWN",
            "confidence": 0.0,
            "rationale": f"Conditions not evaluated — {reason}.",
        }
        return {"tile_id": tile_id, "sensor": sensor, "indicators": indicators, "classification": classification}

    mean = float(np.mean(values))
    std = float(np.std(values))
    med = float(np.median(values))
    p2 = float(np.percentile(values, 2))
    p98 = float(np.percentile(values, 98))
    sat_count = int(np.count_nonzero((mask & 2) != 0))  # MASK_SATURATED

    quality = _quality_of(valid_fraction, cfg.empty_valid_fraction)

    texture_status = "NORMAL"
    if std < low_dn:
        texture_status = "LOW"
    elif std > high_dn:
        texture_status = "HIGH"

    indicators = {
        "valid_coverage": _ind(valid_fraction, "OK" if valid_fraction >= cfg.empty_valid_fraction else "LOW", quality[1], ""),
        "illumination_range": _ind({"min": round(p2, 1), "max": round(p98, 1)}, "OK", quality[1],
                                   "display-DN percentiles (2-98); display-only, not radiance."),
        "brightness_mean": _ind({"mean": round(mean, 2), "median": round(med, 2), "std": round(std, 2)}, "OK", quality[1], ""),
        "texture": _ind(round(std, 3), texture_status, quality[1],
                        f"std of display-DN on valid pixels (engineering thresholds {low_dn}/{high_dn})."),
        "saturation": _ind(round(sat_count / total, 6), "HIGH" if sat_count > 0 else "OK", quality[1],
                           "saturated pixels carry no usable signal."),
    }

    level = "TEXTURED" if texture_status == "NORMAL" else texture_status + "_TEXTURE"
    confidence = quality[1] if texture_status in ("LOW", "NORMAL", "HIGH") else 0.0
    classification = {
        "level": level,
        "confidence": confidence,
        "rationale": (
            f"Texture {texture_status} on {round(valid_fraction * 100, 1)}% valid coverage; "
            f"reliability is a function of valid data, not of absolute brightness."
        ),
    }
    return {"tile_id": tile_id, "sensor": sensor, "indicators": indicators, "classification": classification}


def summarize(tile_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-tile results into a pair-level condition summary."""
    if not tile_results:
        return {
            "tiles": 0,
            "assessed": 0,
            "distribution": {},
            "note": "No tiles were assessed — conditions were NOT_RUN for this pair.",
        }
    levels: dict[str, int] = {}
    confidences: list[float] = []
    for tr in tile_results:
        level = tr["classification"]["level"]
        levels[level] = levels.get(level, 0) + 1
        confidence = float(tr["classification"].get("confidence", 0.0))
        if level not in ("UNKNOWN", "BLOCKED"):
            confidences.append(confidence)
    return {
        "tiles": len(tile_results),
        "assessed": len(confidences),
        "distribution": levels,
        "mean_confidence": round(float(np.mean(confidences)), 3) if confidences else 0.0,
        "note": (
            "Condition indicators are engineering observations for matcher-readiness only; "
            "they carry no standalone scientific conclusion."
        ),
    }