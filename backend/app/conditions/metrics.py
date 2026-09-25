"""Deterministic M5 condition metrics.

All metric functions are pure (input arrays + configuration => result). No
RNG state, no filesystem access, no hidden routing logic. Fixed-stride window
sampling keeps large-image runs bounded and reproducible.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import cv2

from .contract import ConditionInputError, bin_level, validate_side_input


# ---------------------------------------------------------------------------
# deterministic window sampling
# ---------------------------------------------------------------------------

def _window_grid(shape: tuple[int, int], cfg) -> dict[str, Any]:
    height, width = shape
    window = max(1, int(cfg.window_size_px))
    stride = max(1, int(cfg.stride_px))

    stride_used = stride
    while True:
        rows = list(range(0, height, stride_used))
        cols = list(range(0, width, stride_used))
        n_windows = len(rows) * len(cols)
        if n_windows <= int(cfg.max_windows) or stride_used >= max(height, width, 1):
            break
        stride_used *= 2

    windows = [(r * stride_used, c * stride_used) for r in range(len(rows)) for c in range(len(cols))]
    pixels_examined = 0
    for r, c in windows:
        rs, re = r, min(r + window, height)
        cs, ce = c, min(c + window, width)
        pixels_examined += (re - rs) * (ce - cs)

    pixels_total = height * width
    sample_fraction = pixels_examined / pixels_total if pixels_total else 0.0
    return {
        "method": "fixed_stride_grid",
        "window_size_px": window,
        "stride_used_px": stride_used,
        "seed_recorded": int(cfg.sampling_seed),
        "windows_total": len(windows),
        "pixels_examined_aggregate": int(pixels_examined),
        "pixels_total": int(pixels_total),
        "sample_fraction": round(float(min(1.0, sample_fraction)), 6),
        "note": "Windows may overlap (stride can be smaller than window), so the aggregate window area can exceed the image area; sample_fraction is capped at 1.",
    }


def _iter_windows(display: np.ndarray, mask: np.ndarray, cfg):
    height, width = display.shape
    window = max(1, int(cfg.window_size_px))
    plan = _window_grid((height, width), cfg)
    stride_used = int(plan["stride_used_px"])
    for r in range(0, height, stride_used):
        for c in range(0, width, stride_used):
            yield r, c, min(r + window, height), min(c + window, width)


# ---------------------------------------------------------------------------
# mask statistics (valid == 0 per M2 convention)
# ---------------------------------------------------------------------------

def mask_statistics(mask: np.ndarray) -> dict[str, Any]:
    total = int(mask.size)
    valid = int(np.count_nonzero(mask == 0))
    b0 = int(np.count_nonzero((mask & 1) != 0))   # nan/inf
    b1 = int(np.count_nonzero((mask & 2) != 0))   # saturated
    b2 = int(np.count_nonzero((mask & 4) != 0))   # negative
    b3 = int(np.count_nonzero((mask & 8) != 0))   # unknown
    other = max(0, total - valid - b0 - b1 - b2 - b3)
    if total == 0:
        valid_fraction = 0.0
    else:
        valid_fraction = valid / total
    return {
        "total_pixels": total,
        "valid_pixels": valid,
        "valid_fraction": round(float(valid_fraction), 6),
        "invalid_fraction": round(1.0 - float(valid_fraction), 6),
        "contributing_flags": {
            "nan_inf_pixels": b0,
            "saturated_pixels": b1,
            "negative_pixels": b2,
            "unknown_pixels": b3,
            "unspecified_invalid_pixels": other,
        },
    }


# ---------------------------------------------------------------------------
# windowed texture / appearance metrics
# ---------------------------------------------------------------------------

def _windowed_metrics(display: np.ndarray, mask: np.ndarray, cfg) -> tuple[dict[str, Any], np.ndarray]:
    sobel_ksize = int(cfg.sobel_kernel_size_px)
    if sobel_ksize % 2 == 0 or sobel_ksize < 1:
        sobel_ksize = 3
    lap_ksize = int(cfg.laplacian_kernel_size_px)
    if lap_ksize % 2 == 0 or lap_ksize < 1:
        lap_ksize = 3

    # Each examined valid pixel contributes exactly ONCE to the pooled
    # statistics. Windows may overlap (stride can be smaller than window), so
    # a naive concatenation would duplicate boundary pixels and bias the mean /
    # percentiles; accumulating into unique "seen" planes keeps the sampled
    # distribution faithful to the examined pixel set.
    seen = np.zeros(display.shape, dtype=bool)
    energy_acc = np.zeros(display.shape, dtype=np.float32)
    lap_acc = np.zeros(display.shape, dtype=np.float32)
    lap_sq_acc = np.zeros(display.shape, dtype=np.float32)
    edge_acc = np.zeros(display.shape, dtype=bool)

    for r, cs, re, ce in _iter_windows(display, mask, cfg):
        sl = (slice(r, re), slice(cs, ce))
        mwin = np.asarray(mask[sl], dtype=np.uint8)
        validv = mwin == 0
        fresh = validv & ~seen[sl]
        if not np.any(fresh):
            continue

        # texture metrics are evaluated on the unit-scaled display plane
        # ([0,1]) so thresholds are meaningful across sensors regardless of the
        # stored DN range (u16 display products).
        win_raw = np.asarray(display[sl], dtype=np.float32)
        win = np.clip(win_raw, 0.0, 65535.0) / 65535.0

        gx = cv2.Sobel(win, cv2.CV_32F, 1, 0, ksize=sobel_ksize)
        gy = cv2.Sobel(win, cv2.CV_32F, 0, 1, ksize=sobel_ksize)
        energy = (gx * gx) + (gy * gy)

        if cfg.canny_enabled:
            u8i = (win * 255.0).astype(np.uint8)
            edges = cv2.Canny(
                u8i,
                float(cfg.p("texture", "canny", "min_threshold", default=50.0)),
                float(cfg.p("texture", "canny", "max_threshold", default=150.0)),
                apertureSize=int(cfg.p("texture", "canny", "aperture_size_px", default=3)),
                L2gradient=bool(cfg.p("texture", "canny", "l2gradient", default=False)),
            )
            edge_acc[sl] = edge_acc[sl] | (edges > 0)

        lap = cv2.Laplacian(win, cv2.CV_32F, ksize=lap_ksize)

        energy_acc[sl][fresh] = energy[fresh]
        lap_acc[sl][fresh] = lap[fresh]
        lap_sq_acc[sl][fresh] = (lap * lap)[fresh]
        seen[sl][fresh] = True

    total = int(np.count_nonzero(seen))
    values = np.asarray(display[seen], dtype=np.float32) if total else np.zeros(0, dtype=np.float32)

    if total == 0:
        return {
            "gradient_energy_mean_mag_sq": None,
            "canny_edge_fraction": None,
            "canny_edge_pixels": 0,
            "laplacian_mean": None,
            "laplacian_variance": None,
            "edge_pixels_used": 0,
        }, values

    laplacian_mean = float(lap_acc[seen].sum()) / total
    laplacian_variance = float(lap_sq_acc[seen].sum()) / total - laplacian_mean * laplacian_mean
    return {
        "gradient_energy_mean_mag_sq": round(float(energy_acc[seen].sum()) / total, 6),
        "canny_edge_fraction": round(int(np.count_nonzero(edge_acc[seen])) / total, 6),
        "canny_edge_pixels": int(np.count_nonzero(edge_acc[seen])),
        "laplacian_mean": round(laplacian_mean, 6),
        "laplacian_variance": round(laplacian_variance, 6),
        "edge_pixels_used": total,
    }, values


def _analytic_histogram(values: np.ndarray, cfg) -> dict[str, Any]:
    if values.size == 0:
        return {
            "histogram_bins": int(cfg.histogram_bins),
            "bin_edges_min_max": None,
            "normalised_l1": None,
        }
    lo = float(np.min(values))
    hi = float(np.max(values))
    bins = int(cfg.histogram_bins)
    if hi - lo < 1e-9:
        hist = np.zeros(bins, dtype=np.float64)
        hist[0] = float(values.size)
    else:
        edges = np.linspace(lo, hi, bins + 1)
        hist, _ = np.histogram(values, bins=edges)
    total = float(hist.sum()) or 1.0
    return {
        "histogram_bins": bins,
        "bin_edges_min_max": [round(lo, 3), round(hi, 3)],
        "normalised_l1": [round(float(v), 6) for v in (hist / total)],
    }


def _appearance_metrics(values: np.ndarray, cfg) -> dict[str, Any]:
    if values.size == 0:
        return {
            "entropy_bits": None,
            "robust_intensity_dn": None,
            "min_dn": None,
            "max_dn": None,
        }

    lo = float(np.min(values))
    hi = float(np.max(values))
    if hi - lo < 1e-9:
        entropy = 0.0
    else:
        edges = np.linspace(lo, hi, int(cfg.histogram_bins) + 1)
        hist, _ = np.histogram(values, bins=edges)
        p = hist / max(1, hist.sum())
        entropy = -float(np.sum(p[p > 0] * np.log(p[p > 0]))) / np.log(2.0)

    percentiles = sorted(set([5.0, 25.0, 50.0, 75.0, 95.0] + list(cfg.robust_percentiles)))
    pvals = np.percentile(values, percentiles) if values.size else np.zeros(len(percentiles))
    p_map = dict(zip([float(p) for p in percentiles], [float(v) for v in pvals]))
    p5, p50, p95 = p_map[5.0], p_map[50.0], p_map[95.0]
    p25, p75 = p_map[25.0], p_map[75.0]

    std = float(np.std(values))
    rng = hi - lo
    constant = (
        std <= float(cfg.p("appearance", "constant_std_dn_tolerance", default=1.0))
        or rng <= float(cfg.p("appearance", "constant_range_dn_tolerance", default=4.0))
    )

    return {
        "entropy_bits": round(entropy, 6),
        "is_constant_layout": bool(constant),
        "std_dn": round(std, 3),
        "robust_intensity_dn": {
            "p5": round(p5, 3),
            "p50": round(p50, 3),
            "p95": round(p95, 3),
            "p25": round(p25, 3),
            "p75": round(p75, 3),
            "iqr_dn": round(p75 - p25, 3),
            "dynamic_range_p95_minus_p5_dn": round(p95 - p5, 3),
        },
        "min_dn": round(lo, 3),
        "max_dn": round(hi, 3),
    }


# ---------------------------------------------------------------------------
# per-side intrinsic condition
# ---------------------------------------------------------------------------

def side_condition(display: np.ndarray, mask: np.ndarray, cfg, *, side_id: str) -> dict[str, Any]:
    validate_side_input(display, mask)
    if cfg.p("invalid_mask", "enabled", default=True) is False:
        mask = np.zeros_like(mask) or np.zeros_like(display, dtype=np.uint8)

    mstats = mask_statistics(mask)
    plan = _window_grid(display.shape, cfg)
    windowed, values = _windowed_metrics(display, mask, cfg)
    appearance = _appearance_metrics(values, cfg)
    histogram = _analytic_histogram(values, cfg)

    texture_value = windowed["laplacian_variance"]
    appearance_value = appearance["robust_intensity_dn"]["dynamic_range_p95_minus_p5_dn"] if appearance["robust_intensity_dn"] else None

    return {
        "side_id": side_id,
        "sampling": plan,
        "invalid_mask": mstats,
        "texture": {
            "gradient_energy_mean_mag_sq": windowed["gradient_energy_mean_mag_sq"],
            "canny_edge_fraction": windowed["canny_edge_fraction"],
            "canny_edge_pixels": windowed["canny_edge_pixels"],
            "laplacian_mean": windowed["laplacian_mean"],
            "laplacian_variance": texture_value,
            "sobel_kernel_size_px": cfg.sobel_kernel_size_px,
            "laplacian_kernel_size_px": cfg.laplacian_kernel_size_px,
            "canny_thresholds": [float(cfg.p("texture", "canny", "min_threshold", default=50.0)), float(cfg.p("texture", "canny", "max_threshold", default=150.0))],
            "texture_metrics_unit": "[0,1] unit-scaled display plane (u16 display / 65535)",
        },
        "appearance": appearance,
        "condition_histogram": histogram,
        "classification": {
            "textural_complexity": _bin(
                value=texture_value,
                key=cfg.classification_key("textural_complexity"),
                fallback_metric="laplacian_variance",
            ),
            "dynamic_range": _bin(
                value=appearance_value,
                key=cfg.classification_key("dynamic_range"),
                fallback_metric="p95_minus_p5_dn",
            ),
            "invalid_fraction": _bin(
                value=mstats["invalid_fraction"],
                key=cfg.classification_key("invalid_fraction"),
                fallback_metric="invalid_fraction",
            ),
            "note": cfg.p("classification", "note", default="Engineering-level ordinal bins (LOW/MEDIUM/HIGH) with explicit thresholds recorded in every artifact. Reproducible labels for engineering use only — never a scientific quality verdict and never an input to matcher selection in this layer."),
        },
        "established_facts": {
            "native_dimensions": {"height": int(display.shape[0]), "width": int(display.shape[1])},
            "effective_processing_dimensions": {"height": int(display.shape[0]), "width": int(display.shape[1])},
            "resampling_applied": False,
        },
        "_pooled_values": values,
    }


def _bin(value: Any, key: dict[str, Any], fallback_metric: str) -> dict[str, Any]:
    if not key:
        key = {}
    metric = str(key.get("metric") or fallback_metric)
    low = float(key.get("low_lt", 0.0))
    high = float(key.get("high_ge", 1e12))
    return {
        "bin": bin_level(value, low, high) if isinstance(value, (int, float)) else "UNKNOWN",
        "metric": metric,
        "thresholds": {"low_lt": low, "high_ge": high},
        "value": None if not isinstance(value, (int, float)) else round(float(value), 6),
    }


# ---------------------------------------------------------------------------
# pair-level comparison
# ---------------------------------------------------------------------------

def histogram_distance_chi_square(hist_a: np.ndarray, hist_b: np.ndarray) -> float:
    pa = hist_a.astype(np.float64) / max(1.0, float(hist_a.sum()))
    pb = hist_b.astype(np.float64) / max(1.0, float(hist_b.sum()))
    diff = pa - pb
    denom = pa + pb
    div = np.divide(diff * diff, denom, out=np.zeros_like(diff), where=denom > 0)
    return round(float(np.sum(div) / 2.0), 6)


def shared_histograms(side_a: dict[str, Any], side_b: dict[str, Any], cfg):
    """Rebin both sides' pooled valid values onto shared bin edges so the
    distance metric is meaningful. Deterministic; no RNG."""
    bins = int(cfg.histogram_bins)
    va = side_a.get("_pooled_values")
    vb = side_b.get("_pooled_values")
    if va is None or vb is None or va.size == 0 or vb.size == 0:
        return None, None
    lo = min(float(np.min(va)), float(np.min(vb)))
    hi = max(float(np.max(va)), float(np.max(vb)))
    if hi - lo < 1e-9:
        edges = np.linspace(lo, hi + 1.0, bins + 1)
    else:
        edges = np.linspace(lo, hi, bins + 1)
    ha, _ = np.histogram(va, bins=edges)
    hb, _ = np.histogram(vb, bins=edges)
    return ha, hb


def pair_comparison(side_a: dict[str, Any], side_b: dict[str, Any], cfg, *, gsd_a: dict[str, Any] | None, gsd_b: dict[str, Any] | None) -> dict[str, Any]:
    hist_a, hist_b = shared_histograms(side_a, side_b, cfg)
    hist_distance = None
    if hist_a is not None and hist_b is not None:
        metric = cfg.p("histogram_distance", "metric", default="chi_square")
        if metric == "chi_square":
            hist_distance = histogram_distance_chi_square(hist_a, hist_b)

    fallback_gsd = {"gsd_m": None, "gsd_source": cfg.gsd_fallback}

    gsd_ratio = None
    gsd_factual_label = None
    ga = (gsd_a or {}).get("gsd_m")
    gb = (gsd_b or {}).get("gsd_m")
    if ga and gb and ga > 0 and gb > 0:
        hi, lo = (ga, gb) if ga >= gb else (gb, ga)
        gsd_ratio = round(hi / lo, 6)
        gsd_factual_label = (
            "side_b_gsd_over_side_a" if gb >= ga else "side_a_gsd_over_side_b"
        )

    dim_a = side_a["established_facts"]["native_dimensions"]
    dim_b = side_b["established_facts"]["native_dimensions"]
    native_px_a = dim_a["height"] * dim_a["width"]
    native_px_b = dim_b["height"] * dim_b["width"]
    abs_pixel_ratio = round(max(native_px_a, native_px_b) / max(1, min(native_px_a, native_px_b)), 6)

    return {
        "appearance": {
            "histogram_metric": cfg.p("histogram_distance", "metric", default="chi_square"),
            "histogram_distance_chi_square": hist_distance,
            "histogram_bins": int(cfg.histogram_bins),
        },
        "scale": {
            "side_a_gsd": gsd_a or fallback_gsd,
            "side_b_gsd": gsd_b or fallback_gsd,
            "gsd_ratio_relationship": gsd_ratio,
            "gsd_ratio_factual_label": gsd_factual_label,
            "native_scale_gap": {
                "side_a_pixels": native_px_a,
                "side_b_pixels": native_px_b,
                "absolute_pixel_ratio": abs_pixel_ratio,
                "native_vs_effective": {
                    "side_a": "native_equals_effective_true",
                    "side_b": "native_equals_effective_true",
                    "resampling_applied": False,
                },
            },
        },
        "coverage": {
            "side_a_valid_fraction": side_a["invalid_mask"]["valid_fraction"],
            "side_b_valid_fraction": side_b["invalid_mask"]["valid_fraction"],
        },
    }