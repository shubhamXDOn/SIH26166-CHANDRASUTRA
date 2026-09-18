"""M8 matcher capability registry (Section 5).

Every matcher lists its honest, runtime-checked capability. Nothing is claimed
"available" without a live probe. The DeepMatcherConfig settings are resolved
from ``m8_config`` so the same configuration drives both the engine and the
capability surface.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ...config import m8_config
from . import device as _device

_M8_DEFAULTS_CACHE: dict[str, Any] | None = None
_REGISTRY_CACHE: dict[str, Any] | None = None


def get_settings_cfg() -> dict[str, Any]:
    global _M8_DEFAULTS_CACHE

    if _M8_DEFAULTS_CACHE is None:
        _M8_DEFAULTS_CACHE = m8_config()["defaults"]
    return _M8_DEFAULTS_CACHE


def get_model_dir() -> str:
    from ...state import get_state

    return get_state().settings.m8_model_path


def get_device() -> str:
    return str(get_settings_cfg().get("runtime", {}).get("device", "auto"))


@lru_cache(maxsize=1)
def _registry(model_dir: str, device: str):
    from .adapters import build_registry

    return build_registry(get_settings_cfg(), model_dir, device)


def resolve_registry() -> dict[str, Any]:
    """Return the built registry keyed by matcher_id (cached, rebuildable)."""
    global _REGISTRY_CACHE

    if _REGISTRY_CACHE is None:
        _REGISTRY_CACHE = _registry(get_model_dir(), get_device())
    return _REGISTRY_CACHE


def reset_registry() -> None:
    """Clear cached registry (used by tests to re-probe availability)."""
    global _REGISTRY_CACHE, _M8_DEFAULTS_CACHE

    _REGISTRY_CACHE = None
    _M8_DEFAULTS_CACHE = None
    _registry.cache_clear()


def capabilities_public(registry: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Deterministic capability list for /api/matching/capabilities."""
    registry = registry or resolve_registry()
    entries = [reg.capability() for mid in _ORDERED if (reg := registry.get(mid))]
    return entries


_ORDERED = ["sift", "orb", "superpoint_superglue", "loftr"]


def device_public() -> dict[str, Any]:
    """Device/dependency summary for the capabilities endpoint."""
    return _device.device_public()


def configurations_public() -> list[dict[str, Any]]:
    """List the M8 configuration snapshot (like M3's /configurations)."""
    cfg = get_settings_cfg()
    classical = cfg.get("classical") or {}
    deep = cfg.get("deep") or {}
    return [{
        "configuration_id": m8_config()["configuration_id"],
        "configuration_version": m8_config()["configuration_version"],
        "name": m8_config()["name"],
        "classical_strategies": classical.get("strategies", []),
        "deep_strategies": deep.get("strategies", []),
        "classical_enabled": classical.get("enabled", True),
        "deep_enabled": deep.get("enabled", True),
        "preferred_matcher": cfg.get("preferred_matcher", "auto"),
        "runtime": cfg.get("runtime", {}),
        "candidates": cfg.get("candidates", {}),
        "routing": cfg.get("routing", {}),
        "benchmark": cfg.get("benchmark", {}),
    }]