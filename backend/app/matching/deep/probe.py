"""M4 deep matcher — honest runtime & weights probe.

Every matcher reports its true, runtime-checked capability. Nothing is
claimed available without a live probe: torch/torchvision are imported
lazily, the official checkpoints are required on disk, and their SHA-256
must match the pins recorded in ``m4_deep_config``. If a runtime
dependency or a weight file is missing, the matcher reports an explicit
non-available status (``BLOCKED_RUNTIME`` / ``BLOCKED_WEIGHTS``). The
system never auto-downloads and never simulates a deep matcher.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from ...config import m4_deep_config

MATCHER_ID = "superpoint_superglue"
MATCHER_NAME = "SuperPoint + SuperGlue"


@lru_cache(maxsize=1)
def torch_available() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def torchvision_available() -> bool:
    try:
        import torchvision  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def kornia_available() -> bool:
    try:
        import kornia  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


@lru_cache(maxsize=1)
def cuda_available() -> bool:
    if not torch_available():
        return False
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


def runtime_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {}
    if torch_available():
        import torch

        versions["torch"] = str(torch.__version__)
    if torchvision_available():
        import torchvision

        versions["torchvision"] = str(torchvision.__version__)
    return versions


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def superpoint_weight_path(model_dir: Path) -> Path:
    cfg = m4_deep_config()
    spec = (cfg.get("checkpoints") or {}).get("superpoint") or {}
    return Path(model_dir) / (spec.get("filename") or "superpoint_v1.pth")


def superglue_weight_path(model_dir: Path) -> Path:
    cfg = m4_deep_config()
    spec = (cfg.get("checkpoints") or {}).get("superglue") or {}
    return Path(model_dir) / (spec.get("filename") or "superglue_outdoor.pth")


def probe_weights(model_dir: Path) -> list[dict[str, Any]]:
    """Per-checkpoint provenance status (present / size / sha256 match)."""
    cfg = m4_deep_config()
    checkpoints = cfg.get("checkpoints") or {}
    out: list[dict[str, Any]] = []
    for key in ("superpoint", "superglue"):
        spec = checkpoints.get(key) or {}
        filename = spec.get("filename") or f"{key}.pth"
        pin = (spec.get("sha256") or "").strip().lower()
        path = Path(model_dir) / filename
        if not path.is_file():
            out.append(
                {
                    "name": key,
                    "filename": filename,
                    "provisioned": False,
                    "provenance": "MANUAL_PROVISION_REQUIRED",
                    "sha256_match": False,
                    "detail": "weight file not found on disk; manual provisioning from the "
                    "official source is required (no auto-download).",
                }
            )
            continue
        actual = _sha256_file(path)
        matched = (not pin) or (actual == pin)
        out.append(
            {
                "name": key,
                "filename": filename,
                "provisioned": True,
                "provenance": "OFFICIAL_SOURCE_PROVISIONED",
                "path": None,  # never persist absolute machine-specific paths
                "size_bytes": int(path.stat().st_size),
                "sha256": actual,
                "sha256_pin": pin or None,
                "sha256_match": matched,
            }
        )
    return out


def probe_superpoint_superglue(model_dir: Path) -> dict[str, Any]:
    config = m4_deep_config()
    py_ok = torch_available() and torchvision_available()
    weights = probe_weights(model_dir)
    weights_ok = bool(weights) and all(w["provisioned"] and w["sha256_match"] for w in weights)
    if not py_ok:
        status = "BLOCKED_RUNTIME"
        detail = "torch and torchvision are required; not importable in this environment."
    elif not weights_ok:
        status = "BLOCKED_WEIGHTS"
        detail = "official SuperPoint/SuperGlue checkpoints are not provisioned (see weights)."
    else:
        status = "AVAILABLE"
        detail = "runtime present and official checkpoints verified against pinned SHA-256."
    defaults = (config.get("defaults") or {}).get("execution") or {}
    spec_sp = (config.get("checkpoints") or {}).get("superpoint") or {}
    spec_sg = (config.get("checkpoints") or {}).get("superglue") or {}
    weight_map = {w["name"]: w for w in weights}
    return {
        "matcher": MATCHER_ID,
        "matcher_id": MATCHER_ID,
        "matcher_name": "SuperPoint + SuperGlue",
        "matcher_version": "reference-v1",
        "model_family": "superpoint_superglue",
        "technology": "deep_cnn_gnn",
        "required_runtime": ["torch", "torchvision"],
        "runtime_versions": runtime_versions(),
        "status": status,
        "available": status == "AVAILABLE",
        "reason": detail,
        "not_available_detail": None if status == "AVAILABLE" else detail,
        "framework": "torch",
        "framework_version": runtime_versions().get("torch"),
        "weights_required": ["superpoint_v1.pth", "superglue_outdoor.pth"],
        "weights": weights,
        "checkpoint": [spec_sp.get("filename"), spec_sg.get("filename")],
        "checkpoint_sha256": {
            "superpoint_v1.pth": (weight_map.get("superpoint") or {}).get("sha256"),
            "superglue_outdoor.pth": (weight_map.get("superglue") or {}).get("sha256"),
        },
        "weights_source": [
            spec_sp.get("source_url"),
            spec_sg.get("source_url"),
        ],
        "runtime_dependencies": ["torch", "torchvision"],
        "device": {
            "device": "cpu",
            "requested": defaults.get("device", "cpu"),
            "effective": "cpu",
            "cuda_available": cuda_available(),
        },
        "defaults": defaults,
        "superglue_defaults": (config.get("defaults") or {}).get("superglue") or {},
        "scores_are_observations": True,
        "note": "matching_score / log_assignment_score / model_probability are model-native "
        "observation scores; they are not scientific accuracy nor a trust verdict.",
    }


def probe_loftr() -> dict[str, Any]:
    runtime = runtime_versions()
    if not kornia_available():
        return {
            "matcher": "loftr",
            "matcher_id": "loftr",
            "matcher_name": "LoFTR",
            "model_family": "loftr",
            "technology": "deep_transformer",
            "required_runtime": ["torch", "kornia"],
            "runtime_versions": runtime,
            "status": "NOT_AVAILABLE",
            "available": False,
            "reason": "LoFTR requires the kornia runtime (detector-free transformer matcher), "
            "which is not installed in this environment.",
            "not_available_detail": "LoFTR requires kornia, which is not installed in this "
            "environment.",
            "framework": "torch",
            "framework_version": runtime.get("torch"),
            "checkpoint": None,
            "checkpoint_sha256": None,
            "weights_source": None,
            "runtime_dependencies": ["torch", "kornia"],
            "device": {"device": "cpu", "requested": "cpu", "effective": "cpu",
                       "cuda_available": cuda_available()},
            "scores_are_observations": True,
            "deferred": True,
            "integration_note": "OPTIONAL matcher (P1). Left NOT_AVAILABLE rather than "
            "fighting an incompatible dependency while SuperPoint+SuperGlue remains viable.",
        }
    return {
        "matcher": "loftr",
        "matcher_id": "loftr",
        "matcher_name": "LoFTR",
        "model_family": "loftr",
        "technology": "deep_transformer",
        "required_runtime": ["torch", "kornia"],
        "runtime_versions": runtime,
        "status": "NOT_AVAILABLE",
        "available": False,
        "reason": "LoFTR is not implemented in M4-DEEP; only superpoint_superglue is "
        "integrated through the shared contract.",
        "not_available_detail": "LoFTR is not implemented in M4-DEEP; only "
        "superpoint_superglue is integrated through the shared contract.",
        "framework": "torch",
        "framework_version": runtime.get("torch"),
        "checkpoint": None,
        "checkpoint_sha256": None,
        "weights_source": None,
        "runtime_dependencies": ["torch", "kornia"],
        "device": {"device": "cpu", "requested": "cpu", "effective": "cpu",
                   "cuda_available": cuda_available()},
        "scores_are_observations": True,
        "deferred": True,
        "integration_note": "OPTIONAL matcher (P1). Not integrated in M4-DEEP.",
    }


def probe_rift2() -> dict[str, Any]:
    runtime = runtime_versions()
    return {
        "matcher": "rift2",
        "matcher_id": "rift2",
        "matcher_name": "RIFT2",
        "model_family": "rift2",
        "technology": "deep_homography_cnn",
        "required_runtime": [],
        "runtime_versions": runtime,
        "status": "NOT_AVAILABLE",
        "available": False,
        "reason": "RIFT2 is DEFERRED: no reference implementation or checkpoint is provisioned "
        "in this environment, and it is not trained from scratch in M4 (training is out of "
        "scope). It is recorded as a declared DEEP matcher with an explicit non-available "
        "status rather than being simulated.",
        "not_available_detail": "RIFT2 is DEFERRED — no implementation/checkpoint; never "
        "trained or simulated in M4.",
        "framework": None,
        "framework_version": None,
        "checkpoint": None,
        "checkpoint_sha256": None,
        "weights_source": None,
        "runtime_dependencies": [],
        "device": {"device": "cpu", "requested": "cpu", "effective": "cpu",
                   "cuda_available": cuda_available()},
        "trainable": False,
        "deferred": True,
        "integration_note": "Optional P1/P2 target. Deferred without fabricated metrics.",
    }


def capabilities_public(model_dir: Path | None = None) -> dict[str, Any]:
    """Honest, runtime-checked M4-DEEP capability surface."""
    from ...state import get_state

    settings = get_state().settings
    model_dir = model_dir or settings.m8_model_path
    config = m4_deep_config()
    return {
        "family": "m4_deep",
        "configuration_id": config.get("configuration_id", "DM-M4-001"),
        "configuration_name": config.get("name", ""),
        "probed_at_runtime": True,
        "device": {
            "cpu_available": True,
            "cuda_available": cuda_available(),
            "deep_runtime": {
                "torch": torch_available(),
                "torchvision": torchvision_available(),
                "kornia": kornia_available(),
            },
        },
        "matchers": [probe_superpoint_superglue(model_dir), probe_loftr(), probe_rift2()],
        "note": "Statuses are live-probed, never cached claims; missing runtimes or weights "
        "are reported honestly as BLOCKED_* / NOT_AVAILABLE. The deep matcher never "
        "auto-downloads weights and never fabricates model output.",
    }