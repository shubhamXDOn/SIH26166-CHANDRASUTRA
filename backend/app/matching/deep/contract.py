"""M4 deep matcher — shared candidate-correspondence contract runner.

``run_deep_contract`` implements the SAME ``MatcherInput -> MatcherOutput``
contract as the M3 baseline matcher so the two are interchangeable at the
pipeline boundary. Differences are honestly recorded, never hidden:

    * extension fields ``model_family`` / ``model_evidence`` / ``provenance``
      carry model-native scores, weight provenance and the coordinate
      transform;
    * reserve frames: SuperPoint works in its ``h*8 x w*8`` score grid,
      matching happens in the grid, then every candidate is mapped back to
      the effective (model input) frame via the recorded linear transform;
    * resource safety: images are resized to ``max_image_dimension`` before
      any neural work and a time budget is enforced across the run; a
      failure to stay inside the budget is reported as ``RESOURCE_LIMIT``.

Candidates are observations, never inliers/trusted/registered (the M4 Trust
Gate and M6 registration engine stay authoritative). Model scores are
never called "confidence" and never claimed to be scientific accuracy.
"""

from __future__ import annotations

import platform
import time
from dataclasses import field
from typing import Any

import numpy as np

from ...config import m4_deep_config
from ...hardening import TimeBudget, elapsed_ms
from ..baseline import (
    MatcherInput,
    _as_u8_2d,
    _describe_mask,
    _resize_recorded,
    _score_summary,
)
from . import probe
from .models import SuperGlueNet, SuperPointNet
from .probe import probe_weights, torch_available, torchvision_available
from .transforms import (
    build_effective_to_native,
    build_grid_to_effective,
    grid_to_effective,
)

MATCHER_ID = "superpoint_superglue"
MATCHER_NAME = "SuperPoint + SuperGlue"
MIN_WINDOW = 8

ERR_MATCHER_NOT_AVAILABLE = "MATCHER_NOT_AVAILABLE"
ERR_DEEP_RUNTIME_UNAVAILABLE = "DEEP_RUNTIME_UNAVAILABLE"
ERR_DEEP_WEIGHTS_UNAVAILABLE = "DEEP_WEIGHTS_UNAVAILABLE"
ERR_RESOURCE_LIMIT = "RESOURCE_LIMIT"
ERR_INVALID_INPUT = "INVALID_INPUT"
ERR_RUNTIME_ERROR = "RUNTIME_ERROR"


# The deep matcher consumes the SAME input contract as the M3 classical
# baseline (one shared candidate-correspondence contract across the whole
# matcher family). ``DeepMatcherInput`` is kept as an alias so call sites and
# tests read naturally without a second, incompatible input type.
DeepMatcherInput = MatcherInput


def _environment_snapshot() -> dict[str, Any]:
    versions = probe.runtime_versions()
    return {
        "matcher_library": "torch",
        "torch_version": versions.get("torch", "not installed"),
        "torchvision_version": versions.get("torchvision", "not installed"),
        "numpy_version": getattr(np, "__version__", "unknown"),
        "python": platform.python_version(),
        "platform": platform.system(),
    }


def _configuration_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "configuration_id": cfg.get("configuration_id", "DM-M4-001"),
        "configuration_version": cfg.get("configuration_version", 1),
        "name": cfg.get("name", ""),
        "source": "configs/app.yaml",  # config file NAME only; no absolute paths
        "execution": (cfg.get("defaults") or {}).get("execution") or {},
        "superglue": (cfg.get("defaults") or {}).get("superglue") or {},
    }


def _valid_bool(mask: np.ndarray | None, shape) -> np.ndarray:
    """Convert an invalid-mask (0=valid, 255=invalid) to valid-True bool."""
    if mask is None:
        return np.ones(shape, dtype=bool)
    m = np.asarray(mask)
    if m.shape != shape:
        m = np.zeros(shape, dtype=m.dtype)
    return m == 0  # 0 = valid


def _filter_keypoints_by_mask(
    kpts_grid: np.ndarray, grid_dims, eff_shape, valid_eff: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, int]:
    """Keep grid-frame keypoints whose effective-frame location is valid."""
    if valid_eff is None or valid_eff.all():
        return kpts_grid, np.arange(kpts_grid.shape[0], dtype=np.int64), 0
    eff = grid_to_effective(kpts_grid, tuple(grid_dims), tuple(eff_shape))
    keep: list[int] = []
    for i, (x, y) in enumerate(eff):
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < valid_eff.shape[1] and 0 <= yi < valid_eff.shape[0] and valid_eff[yi, xi]:
            keep.append(i)
    dropped = int(kpts_grid.shape[0]) - len(keep)
    return kpts_grid[np.asarray(keep, dtype=np.int64)], np.asarray(keep, dtype=np.int64), dropped


def run_deep_contract(
    inp: DeepMatcherInput, *, cfg: dict[str, Any] | None = None, model_dir=None
) -> Any:
    """Execute the SuperPoint+SuperGlue pipeline over two uint8 windows."""
    from ..baseline import MatcherOutput, _as_u8_2d, _resize_recorded, _score_summary, _describe_mask

    start = time.perf_counter()
    cfg = cfg or m4_deep_config()
    execution = (cfg.get("defaults") or {}).get("execution") or {}
    max_dim = int(execution.get("max_image_dimension", 1024))
    max_runtime = float(execution.get("max_runtime_seconds", 180))

    env = _environment_snapshot()
    output = MatcherOutput(
        matcher_id=inp.matcher_id,
        matcher_name=MATCHER_NAME,
        matcher_version="reference-v1",
        status="SUCCESS",
        keypoint_count_a=0,
        keypoint_count_b=0,
        raw_match_count=0,
        candidate_match_count=0,
        configuration=_configuration_snapshot(cfg),
        determinism={
            "guarantee": "Fixed input + fixed configuration + fixed torch CPU thread count "
            "produce fixed output within a torch build.",
            "verified_by": "deterministic rerun equality (see M4 deep tests)",
        },
        environment=env,
        input={"image_a": _describe_mask(inp.mask_a), "image_b": _describe_mask(inp.mask_b)},
        model_family="superpoint_superglue",
    )

    if inp.matcher_id != MATCHER_ID:
        return output.as_blocked(
            ERR_MATCHER_NOT_AVAILABLE, "Unsupported deep matcher id for M4-DEEP"
        )

    budget = TimeBudget(max_runtime, started_at=start)

    a = _as_u8_2d(inp.image_a)
    b = _as_u8_2d(inp.image_b)
    if (
        a.shape[0] < MIN_WINDOW or a.shape[1] < MIN_WINDOW
        or b.shape[0] < MIN_WINDOW or b.shape[1] < MIN_WINDOW
    ):
        return output.as_blocked(
            ERR_INVALID_INPUT, "Input windows are too small for deep matching (min 8x8 px)."
        )

    if not torch_available() or not torchvision_available():
        return output.as_blocked(
            ERR_DEEP_RUNTIME_UNAVAILABLE,
            "torch/torchvision are required for the deep matcher and are not importable.",
        )

    import torch

    torch_threads = int(execution.get("torch_threads", 8))
    try:
        torch.set_num_threads(torch_threads)
    except Exception:  # noqa: BLE001
        pass
    env["torch_num_threads"] = torch_threads

    if model_dir is None:
        from ...state import get_state

        model_dir = get_state().settings.m8_model_path
    weights = probe_weights(model_dir)
    output.provenance = {
        "checkpoints": weights,
        "policy": "MANUAL_PROVISION_REQUIRED",
        "note": "Official checkpoints must exist on disk and match their pinned SHA-256; "
        "the system never auto-downloads weights.",
    }
    if not all(w["provisioned"] and w["sha256_match"] for w in weights):
        missing = [w["filename"] for w in weights if not w["provisioned"] or not w["sha256_match"]]
        return output.as_blocked(
            ERR_DEEP_WEIGHTS_UNAVAILABLE,
            f"Deep weights unavailable in model directory: {missing}. Provision them manually.",
        )

    # Resize to a recorded effective window before any neural work (resource safety).
    a_eff, mask_a_eff, info_a = _resize_recorded(a, inp.mask_a, max_dim)
    b_eff, mask_b_eff, info_b = _resize_recorded(b, inp.mask_b, max_dim)
    output.input = {
        "image_a": {**_describe_mask(inp.mask_a), **info_a, "plane": "MODEL_INPUT_EFFECTIVE"},
        "image_b": {**_describe_mask(inp.mask_b), **info_b, "plane": "MODEL_INPUT_EFFECTIVE"},
    }

    superpoint_cfg = {
        "nms_radius": int(execution.get("nms_radius", 4)),
        "keypoint_threshold": float(execution.get("keypoint_threshold", 0.005)),
        "max_keypoints": int(execution.get("max_keypoints", 2048)),
        "remove_borders": int(execution.get("remove_borders", 4)),
    }
    superglue_cfg = dict((cfg.get("defaults") or {}).get("superglue") or {})
    gnn_pairs = int(superglue_cfg.get("gnn_layers_self_cross_pairs", 9))
    superglue_cfg["GNN_layers"] = ["self", "cross"] * gnn_pairs

    try:
        sp = SuperPointNet(superpoint_cfg)
        sp.build("cpu")
        sp.load_weights(probe.superpoint_weight_path(model_dir))
        gl = SuperGlueNet(superglue_cfg)
        gl.build("cpu")
        gl.load_weights(probe.superglue_weight_path(model_dir))
    except Exception as exc:  # noqa: BLE001
        return output.as_blocked(ERR_DEEP_WEIGHTS_UNAVAILABLE, f"Model weights load failed: {exc}")

    if budget.expired():
        return output.as_blocked(
            ERR_RESOURCE_LIMIT,
            f"Deep run exceeded the configured {max_runtime:.0f}s time budget before inference.",
        )

    try:
        ex_a = sp.extract(a_eff)
        ex_b = sp.extract(b_eff)
    except Exception as exc:  # noqa: BLE001
        return output.as_blocked(ERR_RUNTIME_ERROR, f"SuperPoint extraction raised: {exc}")

    grid_dim_a = tuple(int(v) for v in ex_a["grid_dimensions"])  # (h, w)
    grid_dim_b = tuple(int(v) for v in ex_b["grid_dimensions"])
    valid_a = _valid_bool(mask_a_eff, a_eff.shape)
    valid_b = _valid_bool(mask_b_eff, b_eff.shape)

    kpts_a_grid, keep_a, dropped_a = _filter_keypoints_by_mask(
        ex_a["keypoints"], grid_dim_a, a_eff.shape, valid_a
    )
    kpts_b_grid, keep_b, dropped_b = _filter_keypoints_by_mask(
        ex_b["keypoints"], grid_dim_b, b_eff.shape, valid_b
    )

    raw_a = int(ex_a["keypoints"].shape[0])
    raw_b = int(ex_b["keypoints"].shape[0])
    output.keypoint_count_a = int(kpts_a_grid.shape[0])
    output.keypoint_count_b = int(kpts_b_grid.shape[0])

    if output.keypoint_count_a < 2 or output.keypoint_count_b < 2:
        return output.as_blocked(
            ERR_INVALID_INPUT,
            f"Not enough deep features to match (A={output.keypoint_count_a}, "
            f"B={output.keypoint_count_b}); SuperPoint needs >=2 keypoints per window.",
        )

    if budget.expired():
        return output.as_blocked(
            ERR_RESOURCE_LIMIT,
            f"Deep run exceeded the configured {max_runtime:.0f}s time budget before matching.",
        )

    pred = gl.match(
        ex_a["descriptors"][keep_a],
        ex_b["descriptors"][keep_b],
        kpts_a_grid,
        kpts_b_grid,
        ex_a["scores"][keep_a],
        ex_b["scores"][keep_b],
        image_dims=tuple(a_eff.shape),
    )
    if budget.expired():
        return output.as_blocked(
            ERR_RESOURCE_LIMIT,
            f"Deep run exceeded the configured {max_runtime:.0f}s time budget after matching.",
        )

    matches = pred["matches"]
    output.raw_match_count = int(matches.shape[0])

    # Correspondences are reported in the EFFECTIVE (model input) frame.
    if output.raw_match_count:
        a_grid = kpts_a_grid[matches[:, 0]]
        b_grid = kpts_b_grid[matches[:, 1]]
        c_a = grid_to_effective(a_grid, grid_dim_a, tuple(a_eff.shape))
        c_b = grid_to_effective(b_grid, grid_dim_b, tuple(b_eff.shape))
    else:
        c_a = np.zeros((0, 2), dtype=np.float64)
        c_b = np.zeros((0, 2), dtype=np.float64)

    match_probs = pred["matching_score"]
    log_probs = pred["log_assignment_score"]

    # Second mask filter on correspondence endpoints (explicit funnel, in the
    # effective frame where the endpoints physically live).
    if mask_a_eff is not None and mask_a_eff.size and output.raw_match_count:
        valid_eff_a = valid_a
        valid_eff_b = valid_b
        kept_idx: list[int] = []
        for i in range(matches.shape[0]):
            xa_i, ya_i = int(round(c_a[i, 0])), int(round(c_a[i, 1]))
            xb_i, yb_i = int(round(c_b[i, 0])), int(round(c_b[i, 1]))
            in_a = 0 <= xa_i < valid_eff_a.shape[1] and 0 <= ya_i < valid_eff_a.shape[0] and valid_eff_a[ya_i, xa_i]
            in_b = 0 <= xb_i < valid_eff_b.shape[1] and 0 <= yb_i < valid_eff_b.shape[0] and valid_eff_b[yb_i, xb_i]
            if in_a and in_b:
                kept_idx.append(i)
        mask_rejected = matches.shape[0] - len(kept_idx)
        if mask_rejected:
            k = np.asarray(kept_idx, dtype=np.int64)
            matches = matches[k]
            c_a, c_b = c_a[k], c_b[k]
            match_probs = match_probs[k]
            log_probs = log_probs[k]
    else:
        mask_rejected = 0

    output.candidate_match_count = int(matches.shape[0])
    output.filters = {
        "superpoint_keypoint_threshold": {
            "applied": True,
            "threshold": superpoint_cfg["keypoint_threshold"],
            "max_keypoints": superpoint_cfg["max_keypoints"],
            "raw_keypoints_a": raw_a,
            "raw_keypoints_b": raw_b,
        },
        "superglue_mutual_nearest": {"applied": True},
        "superglue_match_threshold": {
            "applied": True,
            "threshold": float(superglue_cfg.get("match_threshold", 0.2)),
        },
        "mask": {
            "applied": True,
            "keypoints_a_filtered": raw_a - output.keypoint_count_a,
            "keypoints_b_filtered": raw_b - output.keypoint_count_b,
            "correspondences_rejected": mask_rejected,
        },
        "funnel": {
            "raw_matches": output.raw_match_count,
            "candidates": output.candidate_match_count,
        },
    }

    if output.candidate_match_count == 0:
        output.status = "SUCCESS"
        output.warnings = [
            "No candidate correspondences survived the explicit deep filters (threshold/mask)."
        ]
        output.runtime_ms = round(elapsed_ms(start), 3)
        return output

    transform = {
        "correspondence_plane": "EFFECTIVE_MODEL_INPUT",
        "grid_dimensions": {
            "a": {"height": int(grid_dim_a[0]), "width": int(grid_dim_a[1])},
            "b": {"height": int(grid_dim_b[0]), "width": int(grid_dim_b[1])},
        },
        "grid_to_effective": {
            "a": build_grid_to_effective(grid_dim_a, tuple(a_eff.shape)),
            "b": build_grid_to_effective(grid_dim_b, tuple(b_eff.shape)),
        },
        "effective_to_native": {
            "a": build_effective_to_native(tuple(a_eff.shape), tuple(a.shape)),
            "b": build_effective_to_native(tuple(b_eff.shape), tuple(b.shape)),
        },
    }

    for i in range(matches.shape[0]):
        prob = float(match_probs[i])
        output.correspondences.append({
            "x_a": round(float(c_a[i, 0]), 6),
            "y_a": round(float(c_a[i, 1]), 6),
            "x_b": round(float(c_b[i, 0]), 6),
            "y_b": round(float(c_b[i, 1]), 6),
            "score": round(prob, 6),  # model assignment probability, not a trust value
            "matching_score": round(prob, 6),
            "log_assignment_score": round(float(log_probs[i]), 6),
            "correspondence_score": round(prob, 6),
            "model_probability": round(prob, 6),
            "match_index_a": int(matches[i, 0]),
            "match_index_b": int(matches[i, 1]),
        })

    output.model_evidence = {
        "model": "SuperPoint (keypoints/descriptors) + SuperGlue (graph matching)",
        "architecture": "reference SuperPoint + reference SuperGlue (no positional encoding)",
        "superpoint": {
            "nms_radius": superpoint_cfg["nms_radius"],
            "keypoint_threshold": superpoint_cfg["keypoint_threshold"],
            "remove_borders": superpoint_cfg["remove_borders"],
            "max_keypoints": superpoint_cfg["max_keypoints"],
            "cell": 8,
            "grid_dimensions": {
                "a": [int(grid_dim_a[0]), int(grid_dim_a[1])],
                "b": [int(grid_dim_b[0]), int(grid_dim_b[1])],
            },
        },
        "superglue": {
            "sinkhorn_iterations": int(superglue_cfg.get("sinkhorn_iterations", 100)),
            "match_threshold": float(superglue_cfg.get("match_threshold", 0.2)),
            "GNN_layers_self_cross_pairs": gnn_pairs,
            "feature_dim": 256,
        },
        "coordinate_transform": transform,
        "scores_are_observations": True,
        "note": (
            "Model-native scores (matching_score / log_assignment_score / "
            "correspondence_score / model_probability) describe assignment "
            "probability, not scientific accuracy and never a trust verdict."
        ),
    }
    output.scores = {
        "matching_score": _score_summary(np.asarray(match_probs, dtype=np.float64)),
        "correspondence_score": _score_summary(np.asarray(match_probs, dtype=np.float64)),
        "log_assignment_score": _score_summary(np.asarray(log_probs, dtype=np.float64)),
    }
    output.runtime_ms = round(elapsed_ms(start), 3)
    return output