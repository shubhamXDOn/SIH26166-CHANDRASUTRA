"""M8 device runtime detection.

Supported device states (M8 spec 1.3):
    CPU                 — classical matchers always work on CPU;
    CUDA-if-available   — deep matchers use CUDA when present;
    Unavailable         — a deep runtime dependency is missing.

Capability detection is honest and lazy: nothing heavy is imported when the
module is loaded, and an absent GPU never crashes CPU execution.
"""

from __future__ import annotations

import functools
from typing import Any


@functools.lru_cache(maxsize=1)
def torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def torchvision_available() -> bool:
    try:
        import torchvision  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def kornia_available() -> bool:
    try:
        import kornia  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@functools.lru_cache(maxsize=1)
def cuda_available() -> bool:
    if not torch_available():
        return False
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def resolve_device(requested: str = "auto") -> dict[str, Any]:
    """Resolve the effective runtime device.

    ``requested`` is normally ``auto``. If the deep runtime is missing or no
    CUDA device can be initialised, the result is an honest tie-breaker that
    always keeps CPU usable for classical matching.
    """
    requested = (requested or "auto").strip().lower()
    if requested == "cuda":
        if cuda_available():
            return {"device": "cuda", "cuda_available": True, "cpu_available": True}
        return {"device": "cpu", "cuda_available": False, "cpu_available": True,
                "note": "CUDA requested but unavailable — falling back to CPU explicitly (no silent claim)."}
    if requested == "cpu":
        return {"device": "cpu", "cuda_available": cuda_available(), "cpu_available": True}
    # auto
    if cuda_available():
        return {"device": "cuda", "cuda_available": True, "cpu_available": True}
    return {"device": "cpu", "cuda_available": False, "cpu_available": True}


def device_public() -> dict[str, Any]:
    """Non-secret device capability summary for /api/matching/capabilities."""
    return {
        "cpu": {"available": True},
        "cuda": {"available": cuda_available()},
        "deep_runtime": {
            "torch": torch_available(),
            "torchvision": torchvision_available(),
            "kornia": kornia_available(),
        },
        "effective_device": resolve_device()["device"],
        "note": "Deep matchers use CUDA when available; classical matching always works on CPU.",
    }