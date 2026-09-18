"""M6 visualization montages.

Best-effort inspection aids rendered with NumPy + Pillow. Deliberately simple
and honest: they show source/target/registered crops and where the M5-selected
evidence lies, never a claim of scientific alignment accuracy.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _normalize(arr: np.ndarray, mode: str) -> np.ndarray:
    a = np.asarray(arr, dtype=np.float64)
    if a.ndim != 2 or a.size == 0:
        return np.zeros((16, 16), dtype=np.uint8)
    finite = a[np.isfinite(a)]
    if finite.size == 0:
        return np.zeros(a.shape, dtype=np.uint8)
    lo = float(finite.min())
    hi = float(finite.max())
    if hi - lo < 1e-9:
        hi = lo + 1.0
    if str(mode).lower() == "percentile":
        lo = float(np.percentile(finite, 1))
        hi = float(np.percentile(finite, 99))
        if hi - lo < 1e-9:
            hi = lo + 1.0
    return np.clip((a - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)


def _save(img: Image.Image, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(out_path), format="PNG")


def build_side_by_side(
    src: np.ndarray,
    dst: np.ndarray,
    reg: np.ndarray,
    src_name: str = "Source A",
    dst_name: str = "Source B",
    reg_name: str = "Registered",
    out_path: Path = Path("before_after.png"),
    normalization: str = "minmax",
) -> None:
    panels = [
        (_normalize(src, normalization), src_name),
        (_normalize(dst, normalization), dst_name),
        (_normalize(reg, normalization), reg_name),
    ]
    h = max(p[0].shape[0] for p in panels) or 1
    w = max(p[0].shape[1] for p in panels) or 1
    canvas = Image.new("L", (w * len(panels) + 10 * (len(panels) + 1), h + 24), 0)
    draw = ImageDraw.Draw(canvas)
    for i, (panel, name) in enumerate(panels):
        x = 10 + i * (w + 10)
        tile = Image.fromarray(panel, mode="L").resize((w, h), Image.NEAREST)
        canvas.paste(tile, (x, 22))
        draw.text((x, 4), name, fill=255)
    _save(canvas, out_path)


def build_difference_overlay(
    dst: np.ndarray,
    reg: np.ndarray,
    out_path: Path = Path("difference_overlay.png"),
    normalization: str = "minmax",
) -> None:
    a = np.asarray(dst, dtype=np.float64)
    b = np.asarray(reg, dtype=np.float64)
    h = min(a.shape[0], b.shape[0]) if a.ndim == 2 and b.ndim == 2 else 0
    w = min(a.shape[1], b.shape[1]) if a.ndim == 2 and b.ndim == 2 else 0
    if h == 0 or w == 0:
        _save(Image.fromarray(_normalize(reg, normalization), mode="L"), out_path)
        return
    diff = np.abs(a[:h, :w] - b[:h, :w])
    _save(Image.fromarray(_normalize(diff, normalization), mode="L"), out_path)


def _draw_points(img: Image.Image, pts, color: tuple[int, int, int], label: str) -> None:
    draw = ImageDraw.Draw(img)
    if pts is not None and len(pts):
        for p in np.asarray(pts):
            x, y = float(p[0]), float(p[1])
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    if abs(dx) + abs(dy) <= 2:
                        draw.point((int(x + dx), int(y + dy)), fill=color)
    if label:
        draw.text((6, 4), label, fill=(255, 255, 255))


def build_correspondence_overlay(
    src: np.ndarray | None,
    pts_a: np.ndarray | None,
    pts_b: np.ndarray | None,
    out_path: Path = Path("correspondences.png"),
    normalization: str = "minmax",
) -> None:
    if src is None:
        _save(Image.new("L", (64, 64), 0), out_path)
        return
    a_img = Image.fromarray(_normalize(src, normalization), mode="L").convert("RGB")
    _draw_points(a_img, pts_a, (255, 0, 0), "selected evidence on source crop")
    _save(a_img, out_path)


def build_footprint_overlay(
    src: np.ndarray | None,
    dst: np.ndarray | None,
    pts_a: np.ndarray | None,
    pts_b: np.ndarray | None,
    out_path: Path = Path("footprint.png"),
    normalization: str = "minmax",
) -> None:
    if src is None and dst is None:
        _save(Image.new("L", (64, 64), 0), out_path)
        return
    panels = []
    if src is not None:
        img = Image.fromarray(_normalize(src, normalization), mode="L").convert("RGB")
        _draw_region_box(img, pts_a, (0, 255, 0), "selected region (sensor A)")
        panels.append(img)
    if dst is not None:
        img = Image.fromarray(_normalize(dst, normalization), mode="L").convert("RGB")
        _draw_region_box(img, pts_b, (0, 0, 255), "selected region (sensor B)")
        panels.append(img)
    if len(panels) == 1:
        _save(panels[0], out_path)
        return
    h = max(p.height for p in panels)
    w = max(p.width for p in panels)
    canvas = Image.new("RGB", (w * 2 + 30, h), 0)
    canvas.paste(panels[0], (10, 0))
    canvas.paste(panels[1], (w + 20, 0))
    _save(canvas, out_path)


def _draw_region_box(img: Image.Image, pts, color: tuple[int, int, int], label: str) -> None:
    draw = ImageDraw.Draw(img)
    if pts is not None and len(pts):
        xs = [float(p[0]) for p in np.asarray(pts)]
        ys = [float(p[1]) for p in np.asarray(pts)]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        draw.rectangle([x0, y0, x1, y1], outline=color, width=2)
    draw.text((6, 4), label, fill=(255, 255, 255))