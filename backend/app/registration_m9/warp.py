"""M9 REGISTRATION — derived aligned/warped output.

IMAGE WARP is deliberately separate from model fit and acceptance. The source
image is warped into the target-B effective frame using the declared transform
(inverse map, ``cv2.warpPerspective``) with explicit interpolation, border mode
and fill value. Outputs are DERIVED artifacts: raw products are never modified,
and everything produced here is a visualization/derived output carrying no
physical accuracy claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

_INTERP = {
    "linear": cv2.INTER_LINEAR,
    "nearest": cv2.INTER_NEAREST,
    "cubic": cv2.INTER_CUBIC,
}
_BORDER = {
    "constant": cv2.BORDER_CONSTANT,
    "reflect": cv2.BORDER_REFLECT101,
    "replicate": cv2.BORDER_REPLICATE,
}


@dataclass
class WarpProduct:
    warped: np.ndarray
    valid_mask: np.ndarray
    output_height: int
    output_width: int
    interpolation: str
    border_mode: str
    fill_value: int
    dtype: str
    source_sha256: str | None = None


def _to_3x3(matrix: np.ndarray) -> np.ndarray:
    m = np.asarray(matrix, dtype=np.float64)
    if m.shape == (3, 3):
        return m.copy()
    if m.shape == (2, 3):
        h = np.eye(3, dtype=np.float64)
        h[:2, :] = m
        return h
    raise ValueError(f"Unexpected transform matrix shape: {m.shape}")


def warp_to_frame(
    src: np.ndarray | None,
    matrix: np.ndarray,
    out_height: int,
    out_width: int,
    cfg,
    *,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Warp ``src`` into the target frame using the declared transform.

    Returns a dict with ``warped`` (float32), ``valid_mask`` (bool) and the
    explicit warp settings, or an error dict when the inputs are unusable.
    """
    wp = cfg.warp
    if src is None or np.asarray(src).ndim != 2 or np.asarray(src).size == 0:
        return {"error": "WARP_INPUT_MISSING", "reason": "Source image unavailable."}
    if out_height <= 0 or out_width <= 0:
        return {"error": "OUTPUT_BOUNDS_INVALID",
                "reason": f"Output dimensions must be positive; got {out_height}x{out_width}."}
    if wp.max_output_rows > 0 and out_height > wp.max_output_rows:
        return {"error": "OUTPUT_BOUNDS_INVALID",
                "reason": f"Output rows {out_height} exceed max_output_rows {wp.max_output_rows}."}
    if wp.max_output_cols > 0 and out_width > wp.max_output_cols:
        return {"error": "OUTPUT_BOUNDS_INVALID",
                "reason": f"Output cols {out_width} exceed max_output_cols {wp.max_output_cols}."}

    H = _to_3x3(matrix)
    if not np.all(np.isfinite(H)):
        return {"error": "NON_FINITE_TRANSFORM", "reason": "Transform matrix is not finite."}
    try:
        H_inv = np.linalg.inv(H)
    except np.linalg.LinAlgError:
        return {"error": "SINGULAR_TRANSFORM", "reason": "Transform matrix cannot be inverted for warping."}

    if int(out_height) * int(out_width) > 67_108_864:
        return {"error": "OUTPUT_BOUNDS_INVALID",
                "reason": f"Output {out_height}x{out_width} exceeds the maximum supported warp size."}

    interp = _INTERP.get(str(wp.interpolation).lower(), cv2.INTER_LINEAR)
    border = _BORDER.get(str(wp.border_mode).lower(), cv2.BORDER_CONSTANT)
    fill = int(wp.fill_value)

    src_f = np.asarray(src, dtype=np.float32)
    map_x, map_y = _homography_maps(H_inv, out_width, out_height)
    warped = cv2.remap(
        src_f, map_x, map_y,
        interpolation=interp, borderMode=border, borderValue=float(fill),
    )
    valid = (warped != float(fill)) & np.isfinite(warped)
    return {
        "warped": warped,
        "valid_mask": valid,
        "output_height": int(out_height),
        "output_width": int(out_width),
        "interpolation": str(wp.interpolation),
        "border_mode": str(wp.border_mode),
        "fill_value": fill,
        "dtype": str(wp.dtype),
        "source_sha256": source_sha256,
    }


def _homography_maps(
    H_inv: np.ndarray, out_width: int, out_height: int
) -> tuple[np.ndarray, np.ndarray]:
    """Explicit inverse-map coordinate grids for output pixel (x, y) -> source (sx, sy)."""
    yy, xx = np.meshgrid(
        np.arange(out_height, dtype=np.float64),
        np.arange(out_width, dtype=np.float64),
        indexing="ij",
    )
    w = H_inv[2, 0] * xx + H_inv[2, 1] * yy + H_inv[2, 2]
    sx = H_inv[0, 0] * xx + H_inv[0, 1] * yy + H_inv[0, 2]
    sy = H_inv[1, 0] * xx + H_inv[1, 1] * yy + H_inv[1, 2]
    degenerate = np.abs(w) < 1e-12
    if np.any(degenerate):
        sx[degenerate] = -1.0e6
        sy[degenerate] = -1.0e6
    else:
        sx = sx / w
        sy = sy / w
    return sx.astype(np.float32), sy.astype(np.float32)


def to_dtype(arr: np.ndarray, dtype_name: str) -> np.ndarray:
    """Convert to the declared output dtype with integer-safe clipping."""
    try:
        dtype = np.dtype(dtype_name)
    except (TypeError, ValueError):
        return arr
    if dtype.kind in "ui":
        info = np.iinfo(dtype)
        return np.clip(np.round(arr), float(info.min), float(info.max)).astype(dtype)
    return arr.astype(dtype) if dtype.kind in "fc" else arr


def write_preview_png(arr: np.ndarray, out_path: Path) -> None:
    if arr.size == 0:
        return
    a = np.asarray(arr, dtype=np.float64)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo < 1e-9:
        hi = lo + 1.0
    preview = np.clip((a - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(preview, mode="L").save(str(out_path), format="PNG")


def _normalize_uint8(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 2 or a.size == 0:
        return np.zeros((16, 16), dtype=np.uint8)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return np.zeros(a.shape, dtype=np.uint8)
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo < 1e-9:
        hi = lo + 1.0
    return np.clip((a - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def _save(img: Image.Image, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), format="PNG")


def build_before_after(src_a, src_b, registered, out_path: Path) -> None:
    panels = [
        (_normalize_uint8(src_a), "Image A (source)"),
        (_normalize_uint8(src_b), "Image B (target frame)"),
        (_normalize_uint8(registered), "Registered (A warped into B frame)"),
    ]
    h = max(p[0].shape[0] for p in panels) or 1
    w = max(p[0].shape[1] for p in panels) or 1
    canvas = Image.new("L", (w * 3 + 40, h + 24), 0)
    draw = ImageDraw.Draw(canvas)
    for i, (panel, name) in enumerate(panels):
        x = 10 + i * (w + 10)
        tile = Image.fromarray(panel, mode="L").resize((w, h), Image.NEAREST)
        canvas.paste(tile, (x, 22))
        draw.text((x, 4), name, fill=255)
    _save(canvas, out_path)


def build_checkerboard(src_b, registered, out_path: Path, block: int = 32) -> None:
    b = _normalize_uint8(src_b)
    r = _normalize_uint8(registered)
    h = min(b.shape[0], r.shape[0])
    w = min(b.shape[1], r.shape[1])
    out = np.zeros((h, w, 3), dtype=np.uint8)
    bb = b[:h, :w]
    rr = r[:h, :w]
    for i in range(0, h, block):
        for j in range(0, w, block):
            from_b = ((i // block) + (j // block)) % 2 == 0
            patch = bb[i:i + block, j:j + block] if from_b else rr[i:i + block, j:j + block]
            out[i:i + block, j:j + block, 0] = patch
            out[i:i + block, j:j + block, 1] = patch
            out[i:i + block, j:j + block, 2] = patch
    _save(Image.fromarray(out, mode="RGB"), out_path)


def build_difference_map(src_b, registered, out_path: Path) -> None:
    b = np.asarray(src_b, dtype=np.float64)
    r = np.asarray(registered, dtype=np.float64)
    h = min(b.shape[0], r.shape[0]) if b.ndim == 2 and r.ndim == 2 else 0
    w = min(b.shape[1], r.shape[1]) if b.ndim == 2 and r.ndim == 2 else 0
    if h == 0 or w == 0:
        return
    diff = np.abs(b[:h, :w] - r[:h, :w])
    _save(Image.fromarray(_normalize_uint8(diff), mode="L"), out_path)


def build_overlay(src_b, registered, out_path: Path, alpha: float = 0.5) -> None:
    b = _normalize_uint8(src_b)
    r = _normalize_uint8(registered)
    h = min(b.shape[0], r.shape[0])
    w = min(b.shape[1], r.shape[1])
    canvas = np.zeros((max(b.shape[0], r.shape[0]), max(b.shape[1], r.shape[1]), 3), dtype=np.uint8)
    canvas[0:h, 0:w, 0] = b[0:h, 0:w]
    canvas[0:h, 0:w, 1] = r[0:h, 0:w]
    canvas[0:h, 0:w, 2] = 0
    _save(Image.fromarray(canvas, mode="RGB"), out_path)


def build_residual_vectors(
    entries: list[dict[str, Any]],
    matrix: np.ndarray,
    out_height: int,
    out_width: int,
    out_path: Path,
) -> None:
    """Draw source -> transformed-source -> target residual vectors (diagnostic)."""
    from .validate import apply_matrix

    canvas = Image.new("RGB", (out_width, out_height), (8, 8, 8))
    draw = ImageDraw.Draw(canvas)
    pts_a = np.asarray([[e["x_a"], e["y_a"]] for e in entries], dtype=np.float64)
    mapped = apply_matrix(matrix, pts_a)
    for i, e in enumerate(entries):
        xb, yb = float(e["x_b"]), float(e["y_b"])
        mx, my = float(mapped[i, 0]), float(mapped[i, 1])
        draw.line([(xb, yb), (mx, my)], fill=(180, 40, 40), width=1)
        draw.ellipse([xb - 2, yb - 2, xb + 2, yb + 2], fill=(120, 220, 120))
    draw.text((6, 4), "residual vectors: target (green) <- transformed source (red)", fill=(255, 255, 255))
    _save(canvas, out_path)


__all__ = [
    "WarpProduct",
    "build_before_after",
    "build_checkerboard",
    "build_difference_map",
    "build_overlay",
    "build_residual_vectors",
    "to_dtype",
    "warp_to_frame",
    "write_preview_png",
]