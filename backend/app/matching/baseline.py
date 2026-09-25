"""M3 — classical baseline matcher: SIFT (primary), AKAZE (recommended), ORB (auxiliary).

One explicit, common matcher contract (``MatcherInput`` → ``MatcherOutput``)
across all three classical detectors. The output is a set of CANDIDATE
correspondences — raw, filtered descriptor matches produced by fully explicit
filters (Lowe ratio test, cross-check, distance ceiling). Candidates are
observations; they are NEVER inliers, trusted or registered matches. Only the
M4 Trust Gate (later milestone) may verify geometry, and only the M6
registration engine may register.

Honesty rules honoured here:
    * availability is probe-checked at runtime (``AKAZE_create`` is absent in
      this OpenCV build ⇒ AKAZE is truthfully reported NOT_AVAILABLE with the
      reason; it is never simulated or silently skipped).
    * explicit configuration is recorded in every artifact (no silent OpenCV
      defaults): detector + matching parameters are resolved and snapshotted.
    * determinism: fixed input + fixed configuration ⇒ fixed output within a
      library build; environment/version details are recorded so a rerun is
      reproducible and comparable.
    * resource safety: inputs are downsized to a recorded ``max_image_dimension``
      before detector/matcher work (CH-2 sensors are large), and every effective
      dimension + resample factor is recorded. There is no naive full-resolution
      processing.
    * run ids are unique and never overwritten; artifacts land in
      ``data/metadata/m3_matching/<run_id>.json`` (via ``derived_rel`` config).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import m3_baseline_config
from ..hardening import atomic_write_json
from ..logging_conf import get_logger
from ..pairs import PairRegistry
from .adapters import _valid_mask

logger = get_logger(__name__)

BASELINE_MATCHER_IDS: tuple[str, ...] = ("sift", "akaze", "orb")

# Public, deterministic order used by the API capability surface.
BASELINE_MATCHER_META: dict[str, dict[str, str]] = {
    "sift": {
        "display_name": "SIFT (primary baseline)",
        "descriptor_kind": "floating",
        "role": "primary",
    },
    "akaze": {
        "display_name": "AKAZE (recommended baseline)",
        "descriptor_kind": "binary",
        "role": "recommended",
    },
    "orb": {
        "display_name": "ORB (auxiliary baseline)",
        "descriptor_kind": "binary",
        "role": "auxiliary",
    },
}

_STATUS_SUCCESS = "SUCCESS"
_STATUS_BLOCKED = "BLOCKED"
_STATUS_FAILED = "FAILED"

ERR_MATCHER_NOT_AVAILABLE = "MATCHER_NOT_AVAILABLE"
ERR_PROCESSING_NOT_RUN = "PROCESSING_NOT_RUN"
ERR_PRODUCT_MISSING = "PRODUCT_MISSING"
ERR_INVALID_INPUT = "INVALID_INPUT"
ERR_RUNTIME_ERROR = "RUNTIME_ERROR"
ERR_CROP_NOT_AVAILABLE = "CROP_NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Common matcher contract
# ---------------------------------------------------------------------------
@dataclass
class MatcherInput:
    """What a baseline matcher consumes (images are uint8 display, 2-D)."""

    matcher_id: str
    image_a: np.ndarray
    image_b: np.ndarray
    mask_a: np.ndarray | None = None  # 0 = valid
    mask_b: np.ndarray | None = None  # 0 = valid
    configuration: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_2d("image_a", self.image_a)
        _require_2d("image_b", self.image_b)


def _require_2d(name: str, arr: np.ndarray) -> None:
    a = np.asarray(arr)
    if a.ndim != 2:
        raise ValueError(f"{name} must be a 2-D grayscale array; got {a.ndim} dims")


@dataclass
class Correspondence:
    """One candidate correspondence (an observation, never a verdict)."""

    x_a: float
    y_a: float
    x_b: float
    y_b: float
    score: float          # normalized descriptor-distance complement in [0, 1]
    descriptor_distance: float
    match_index_a: int    # index into keypoints/descriptors of A
    match_index_b: int    # index into keypoints/descriptors of B


@dataclass
class MatcherOutput:
    """A full baseline matcher run result, fully JSON-serializable."""

    matcher_id: str
    matcher_name: str
    matcher_version: str
    status: str                       # SUCCESS | BLOCKED | FAILED
    keypoint_count_a: int
    keypoint_count_b: int
    raw_match_count: int
    candidate_match_count: int
    correspondences: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, Any] = field(default_factory=dict)  # distance + score summaries
    runtime_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_detail: str | None = None
    configuration: dict[str, Any] = field(default_factory=dict)
    deterministic_seed: int | None = None
    determinism: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    filters: dict[str, Any] = field(default_factory=dict)  # explicit funnel counts
    input: dict[str, Any] = field(default_factory=dict)    # effective dims / masks
    # M4 strong-deep-matcher extension fields. Empty/None for classical
    # baseline runs so the shared M3 contract stays byte-compatible while the
    # deep matcher records model-native evidence, provenance and source gate.
    model_family: str | None = None
    model_evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    source_gate: dict[str, Any] = field(default_factory=dict)

    def as_blocked(self, code: str, detail: str) -> "MatcherOutput":
        return MatcherOutput(
            matcher_id=self.matcher_id,
            matcher_name=self.matcher_name,
            matcher_version=self.matcher_version,
            status=_STATUS_BLOCKED,
            keypoint_count_a=0,
            keypoint_count_b=0,
            raw_match_count=0,
            candidate_match_count=0,
            error_code=code,
            error_detail=detail,
            configuration=self.configuration,
            deterministic_seed=self.deterministic_seed,
            environment=self.environment,
            warnings=list(self.warnings),
        )


def _matcher_reason() -> str:
    try:
        return f"OpenCV {cv2.__version__}"
    except Exception:  # noqa: BLE001
        return "OpenCV"

# ---------------------------------------------------------------------------
# Availability probing (honest — never fabricated)
# ---------------------------------------------------------------------------
def _akaze_available() -> tuple[bool, str]:
    if hasattr(cv2, "AKAZE_create"):
        return True, "AKAZE is compiled into this OpenCV build."
    return False, (
        "AKAZE_create is not present in this OpenCV build (OpenCV 5.0.0). "
        "AKAZE is registered as a baseline matcher but is NOT_AVAILABLE here; "
        "nothing is simulated and no package is auto-installed."
    )


def matcher_available(matcher_id: str) -> tuple[bool, str]:
    if matcher_id == "sift":
        return hasattr(cv2, "SIFT_create"), "SIFT_create availability probed at runtime."
    if matcher_id == "akaze":
        return _akaze_available()
    if matcher_id == "orb":
        return hasattr(cv2, "ORB_create"), "ORB_create availability probed at runtime."
    return False, f"Unknown baseline matcher id {matcher_id!r}."


def capability_public(matcher_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or m3_baseline_config()
    available, reason = matcher_available(matcher_id)
    meta = BASELINE_MATCHER_META.get(matcher_id, {})
    return {
        "matcher_id": matcher_id,
        "matcher_name": meta.get("display_name", matcher_id),
        "descriptor_kind": meta.get("descriptor_kind", "unknown"),
        "role": meta.get("role", "unknown"),
        "available": available,
        "reason": reason if not available else "available",
        "defaults": resolved_detector_params(matcher_id, cfg),
        "not_available_detail": None if available else reason,
    }


def capabilities_public(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or m3_baseline_config()
    return {
        "m3_baseline_configuration_id": cfg.get("configuration_id", "MB-M3-001"),
        "matchers": [capability_public(mid, cfg) for mid in BASELINE_MATCHER_IDS],
        "note": (
            "Candidate correspondences are observations, not verified alignment. "
            "AKAZE is registered but reports NOT_AVAILABLE when the OpenCV build "
            "lacks it; no matcher is ever simulated."
        ),
    }


def real_data_gate(settings) -> dict[str, Any]:
    """Machine-readable truth about genuine PRADAN data availability.

    Real PRADAN matching is only meaningful when genuine raw products exist;
    synthetic/fixture data can never satisfy that gate. ``settings`` is the
    Settings object (scan_raw_products consumes it).
    """
    from ..pairs import scan_raw_products

    try:
        inventory = scan_raw_products(settings)
    except Exception:
        return {
            "code": "REAL_DATA_STATUS_UNKNOWN",
            "message": "Raw product inventory could not be scanned.",
            "real_data_available": False,
        }
    real = [e for e in inventory if e.get("source_class") == "REAL_PRADAN"]
    if real:
        return {
            "code": "REAL_DATA_AVAILABLE",
            "message": f"{len(real)} genuine PRADAN product(s) detected.",
            "real_data_available": True,
        }
    return {
        "code": "REAL_DATA_BLOCKED",
        "message": "No genuine PRADAN raw products are present; only TEST_FIXTURE (synthetic) data is available. Real PRADAN matching remains blocked pending operator data.",
        "real_data_available": False,
    }


# ---------------------------------------------------------------------------
# Explicit configuration resolution (recorded in full, never silently defaulted)
# ---------------------------------------------------------------------------
RESOLVED_NORM: dict[str, int] = {
    "sift": cv2.NORM_L2,
    "akaze": cv2.NORM_HAMMING,
    "orb": cv2.NORM_HAMMING,
}

_AKAZE_DESCRIPTORS = {
    "KAZE_UPRIGHT": getattr(cv2, "KAZE_UPRIGHT", 2),
    "MLDB": getattr(cv2, "AKAZE_DESCRIPTOR_MLDB", 5),
    "MLDB_UPRIGHT": getattr(cv2, "AKAZE_DESCRIPTOR_MLDB_UPRIGHT", 7),
}

_AKAZE_DIFFUSIVITIES = {
    "PM_G1": getattr(cv2, "DIFFUSIVITY_PM_G1", 1),
    "PM_G2": getattr(cv2, "DIFFUSIVITY_PM_G2", 2),
    "WEICKERT": getattr(cv2, "DIFFUSIVITY_WEICKERT", 3),
    "CHARBONNIER": getattr(cv2, "DIFFUSIVITY_CHARBONNIER", 4),
}


def resolved_detector_params(matcher_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Detector parameters resolved from config with explicit names (JSON-safe)."""
    d = ((cfg or {}).get("defaults") or {}).get(matcher_id, {}).get("detector", {})
    if matcher_id == "sift":
        return {
            "nfeatures": int(d.get("nfeatures", 2000)),
            "n_octave_layers": int(d.get("n_octave_layers", 3)),
            "contrast_threshold": float(d.get("contrast_threshold", 0.04)),
            "edge_threshold": float(d.get("edge_threshold", 10.0)),
            "sigma": float(d.get("sigma", 1.6)),
        }
    if matcher_id == "akaze":
        descriptor = str(d.get("descriptor", "MLDB"))
        if descriptor.startswith("MLDB") and hasattr(cv2, "AKAZE_DESCRIPTOR_MLDB"):
            descriptor_type = getattr(cv2, "AKAZE_DESCRIPTOR_MLDB_UPRIGHT", 7) if "UPRIGHT" in descriptor else getattr(cv2, "AKAZE_DESCRIPTOR_MLDB", 5)
        else:
            descriptor_type = _AKAZE_DESCRIPTORS.get(descriptor, getattr(cv2, "KAZE_UPRIGHT", 2))
        return {
            "descriptor": descriptor,
            "descriptor_type": int(descriptor_type),
            "descriptor_size": int(d.get("descriptor_size", 0)),
            "descriptor_channels": int(d.get("descriptor_channels", 3)),
            "threshold": float(d.get("threshold", 0.001)),
            "n_octaves": int(d.get("n_octaves", 4)),
            "n_octave_layers": int(d.get("n_octave_layers", 4)),
            "diffusivity": str(d.get("diffusivity", "PM_G2")),
            "diffusivity_type": int(_AKAZE_DIFFUSIVITIES.get(str(d.get("diffusivity", "PM_G2")), getattr(cv2, "DIFFUSIVITY_PM_G2", 2))),
        }
    if matcher_id == "orb":
        return {
            "nfeatures": int(d.get("nfeatures", 2000)),
            "scale_factor": float(d.get("scale_factor", 1.2)),
            "nlevels": int(d.get("nlevels", 8)),
            "edge_threshold": int(d.get("edge_threshold", 31)),
            "fast_threshold": int(d.get("fast_threshold", 20)),
        }
    raise ValueError(f"Unknown baseline matcher id {matcher_id!r}")


def resolved_matching_params(matcher_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    m = ((cfg or {}).get("defaults") or {}).get(matcher_id, {}).get("matching", {})
    return {
        "cross_check": bool(m.get("cross_check", True)),
        "ratio_threshold": float(m.get("ratio_threshold", 0.8)),
        "max_distance": float(m.get("max_distance", 100.0)),
    }


def _configuration_snapshot(matcher_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "configuration_id": cfg.get("configuration_id", "MB-M3-001"),
        "configuration_version": cfg.get("configuration_version", 1),
        "name": cfg.get("name", ""),
        "matcher_id": matcher_id,
        "detector": resolved_detector_params(matcher_id, cfg),
        "matching": resolved_matching_params(matcher_id, cfg),
        # Only the config file NAME is recorded: absolute filesystem paths must
        # never leak into persisted artifacts (M3 provenance rule).
        "source": Path(str(cfg.get("source", ""))).name,
    }


def _environment_snapshot() -> dict[str, Any]:
    import platform

    import numpy as np

    return {
        "opencv_version": getattr(cv2, "__version__", "unknown"),
        "numpy_version": getattr(np, "__version__", "unknown"),
        "matcher_library": "opencv",
        "python": platform.python_version(),
        "platform": platform.system(),
    }


# ---------------------------------------------------------------------------
# Core matcher execution (deterministic, explicit filters, honest funnel)
# ---------------------------------------------------------------------------
def _describe_mask(mask: np.ndarray | None) -> dict[str, Any]:
    if mask is None:
        return {"present": False}
    m = np.asarray(mask)
    total = m.size
    valid = int(np.count_nonzero(m == 0))
    return {
        "present": True,
        "dimensions": {"height": int(m.shape[0]), "width": int(m.shape[1])},
        "valid_pixels": valid,
        "invalid_pixels": int(total - valid),
        "valid_fraction": round(valid / total, 6) if total else 0.0,
    }


def _score_summary(values: np.ndarray | None) -> dict[str, Any]:
    if values is None or len(values) == 0:
        return {"count": 0}
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return {"count": 0}
    return {
        "count": int(len(finite)),
        "min": round(float(finite.min()), 6),
        "max": round(float(finite.max()), 6),
        "mean": round(float(finite.mean()), 6),
        "median": round(float(np.median(finite)), 6),
        "p95": round(float(np.percentile(finite, 95)), 6),
    }


def _detector_for(matcher_id: str, cfg: dict[str, Any] | None = None) -> Any:
    """Build the OpenCV detector from resolved, recorded parameters."""
    cfg = cfg or m3_baseline_config()
    params = resolved_detector_params(matcher_id, cfg)
    if matcher_id == "sift":
        return cv2.SIFT_create(
            nfeatures=params["nfeatures"],
            nOctaveLayers=params["n_octave_layers"],
            contrastThreshold=params["contrast_threshold"],
            edgeThreshold=params["edge_threshold"],
            sigma=params["sigma"],
        )
    if matcher_id == "akaze":
        return cv2.AKAZE_create(
            descriptor_type=params["descriptor_type"],
            descriptor_size=params["descriptor_size"],
            descriptor_channels=params["descriptor_channels"],
            threshold=params["threshold"],
            nOctaves=params["n_octaves"],
            nOctaveLayers=params["n_octave_layers"],
            diffusivity=params["diffusivity_type"],
        )
    if matcher_id == "orb":
        return cv2.ORB_create(
            nfeatures=params["nfeatures"],
            scaleFactor=params["scale_factor"],
            nlevels=params["nlevels"],
            edgeThreshold=params["edge_threshold"],
            fastThreshold=params["fast_threshold"],
        )
    raise ValueError(f"Unknown baseline matcher id {matcher_id!r}")


def run_baseline_contract(inp: MatcherInput, *, cfg: dict[str, Any] | None = None) -> MatcherOutput:
    """Execute one baseline matcher over two uint8 images with explicit filters.

    ``cfg`` overrides the on-file M3 baseline configuration (tests inject
    explicit configurations); production uses the registered defaults.
    """
    start = time.perf_counter()
    env = _environment_snapshot()
    cfg = cfg or m3_baseline_config()
    matcher_id = inp.matcher_id
    matched_meta = _configuration_snapshot(matcher_id, cfg)
    output = MatcherOutput(
        matcher_id=matcher_id,
        matcher_name=BASELINE_MATCHER_META.get(matcher_id, {}).get("display_name", matcher_id),
        matcher_version=env["opencv_version"],
        status=_STATUS_SUCCESS,
        keypoint_count_a=0,
        keypoint_count_b=0,
        raw_match_count=0,
        candidate_match_count=0,
        configuration=matched_meta,
        deterministic_seed=None,
        determinism={
            "guarantee": "Fixed input + fixed configuration produce fixed output within a library build.",
            "verified_by": "deterministic rerun equality (see M3 tests)",
        },
        environment=env,
        input={
            "image_a": _describe_mask(inp.mask_a),
            "image_b": _describe_mask(inp.mask_b),
        },
    )

    available, reason = matcher_available(matcher_id)
    if not available:
        return output.as_blocked(ERR_MATCHER_NOT_AVAILABLE, reason)

    a = _as_u8_2d(inp.image_a)
    b = _as_u8_2d(inp.image_b)
    mka = _valid_mask(inp.mask_a, a.shape)
    mkb = _valid_mask(inp.mask_b, b.shape)

    if a.shape[0] < 8 or a.shape[1] < 8 or b.shape[0] < 8 or b.shape[1] < 8:
        return output.as_blocked(
            ERR_INVALID_INPUT,
            "Input windows are too small for meaningful feature detection (min 8x8 px).",
        )

    matching_params = resolved_matching_params(matcher_id, cfg)
    cross_check = bool(matching_params["cross_check"])
    ratio_threshold = float(matching_params["ratio_threshold"])
    max_distance = float(matching_params["max_distance"])
    warnings: list[str] = []

    try:
        detector = _detector_for(matcher_id, cfg)
        kp_a, des_a = detector.detectAndCompute(a, mka)
        kp_b, des_b = detector.detectAndCompute(b, mkb)
    except Exception as exc:  # noqa: BLE001
        return MatcherOutput(
            matcher_id=matcher_id,
            matcher_name=BASELINE_MATCHER_META.get(matcher_id, {}).get("display_name", matcher_id),
            matcher_version=env["opencv_version"],
            status=_STATUS_FAILED,
            keypoint_count_a=0, keypoint_count_b=0,
            raw_match_count=0, candidate_match_count=0,
            error_code=ERR_RUNTIME_ERROR,
            error_detail=f"Detector/matcher raised: {exc}",
            configuration=matched_meta,
            environment=env,
            runtime_ms=round((time.perf_counter() - start) * 1000.0, 3),
            warnings=[f"Detector raised: {exc}"],
        )

    n_a = len(kp_a) if kp_a is not None else 0
    n_b = len(kp_b) if kp_b is not None else 0
    output.keypoint_count_a = n_a
    output.keypoint_count_b = n_b

    if n_a < 2 or n_b < 2 or des_a is None or des_b is None or des_a.shape[0] < 2 or des_b.shape[0] < 2:
        output.status = _STATUS_BLOCKED
        output.error_code = ERR_INVALID_INPUT
        output.error_detail = (
            f"Not enough features to match (A={n_a}, B={n_b}); baseline needs >=2 features per window."
        )
        output.runtime_ms = round((time.perf_counter() - start) * 1000.0, 3)
        return output

    norm = RESOLVED_NORM[matcher_id]
    matcher = cv2.BFMatcher(norm, crossCheck=False)
    try:
        knn = matcher.knnMatch(des_a, des_b, k=2)
    except Exception as exc:  # noqa: BLE001
        output.status = _STATUS_FAILED
        output.error_code = ERR_RUNTIME_ERROR
        output.error_detail = f"knnMatch raised: {exc}"
        output.runtime_ms = round((time.perf_counter() - start) * 1000.0, 3)
        return output

    i_a: list[int] = []
    i_b: list[int] = []
    distances: list[float] = []
    ratio_rejected = 0
    for pair in knn:
        if not pair:
            continue
        best = pair[0]
        second = pair[1] if len(pair) > 1 else None
        if second is not None and best.distance >= second.distance * ratio_threshold:
            ratio_rejected += 1
            continue
        i_a.append(best.queryIdx)
        i_b.append(best.trainIdx)
        distances.append(float(best.distance))

    distance_rejected = 0
    cross_rejected = 0
    if cross_check and i_a:
        des_b_sel = des_b[np.array(i_b, dtype=np.int64)]
        rev = cv2.BFMatcher(norm, crossCheck=False).knnMatch(des_b_sel, des_a, k=1)
        keep: list[int] = []
        for idx, rev_list in enumerate(rev):
            if rev_list and rev_list[0].trainIdx == i_a[idx] and distances[idx] <= max_distance:
                keep.append(idx)
        distance_rejected = sum(1 for d in distances if d > max_distance)
        cross_rejected = len(distances) - distance_rejected - len(keep)
        i_a = [i_a[i] for i in keep]
        i_b = [i_b[i] for i in keep]
        distances = [distances[i] for i in keep]
    else:
        if i_a:
            keep2 = [idx for idx, d in enumerate(distances) if d <= max_distance]
            distance_rejected = len(distances) - len(keep2)
            i_a = [i_a[idx] for idx in keep2]
            i_b = [i_b[idx] for idx in keep2]
            distances = [distances[idx] for idx in keep2]
        cross_rejected = 0

    output.raw_match_count = len(knn)
    output.candidate_match_count = len(i_a)
    output.filters = {
        "ratio_test": {"applied": True, "rejected": ratio_rejected},
        "cross_check": {"applied": cross_check, "rejected": cross_rejected},
        "distance": {"applied": True, "rejected": distance_rejected, "max_distance": max_distance},
        "funnel": {
            "raw_matches": len(knn),
            "after_ratio": len(knn) - ratio_rejected,
            "candidates": len(i_a),
        },
    }

    if not i_a:
        output.status = _STATUS_SUCCESS
        output.warnings = warnings + [
            "No candidate correspondences survived the explicit baseline filters."
        ]
        output.runtime_ms = round((time.perf_counter() - start) * 1000.0, 3)
        return output

    ref = max(float(max_distance), 1e-9)
    scores = np.clip(1.0 - np.asarray(distances, dtype=np.float64) / ref, 0.0, 1.0)
    for (
        mi_a, mi_b, d, s
    ) in zip(i_a, i_b, distances, scores, strict=False):
        output.correspondences.append({
            "x_a": float(kp_a[mi_a].pt[0]),
            "y_a": float(kp_a[mi_a].pt[1]),
            "x_b": float(kp_b[mi_b].pt[0]),
            "y_b": float(kp_b[mi_b].pt[1]),
            "score": round(float(s), 6),
            "descriptor_distance": round(float(d), 6),
            "match_index_a": int(mi_a),
            "match_index_b": int(mi_b),
        })

    output.scores = {
        "descriptor_distance": _score_summary(np.asarray(distances, dtype=np.float64)),
        "score": _score_summary(scores),
    }
    output.runtime_ms = round((time.perf_counter() - start) * 1000.0, 3)
    output.warnings = warnings
    return output


def _as_u8_2d(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr)
    if a.ndim == 3:
        a = a[:, :, 0]
    if a.ndim != 2:
        raise ValueError(f"expected a 2-D grayscale window; got {a.ndim} dims")
    out = _as_u8_flat(a)
    return out


def _as_u8_flat(arr: np.ndarray) -> np.ndarray:
    from .adapters import _as_u8

    return _as_u8(arr)


# ---------------------------------------------------------------------------
# Input resolution from M2 derived products (resource safe, recorded)
# ---------------------------------------------------------------------------
def _resize_recorded(arr: np.ndarray, mask: np.ndarray | None, max_dim: int) -> tuple[
    np.ndarray, np.ndarray | None, dict[str, Any]
]:
    a = np.asarray(arr)
    if a.ndim == 2 and max_dim and max(a.shape) > max_dim:
        scale = max_dim / float(max(a.shape))
        new_h = max(int(round(a.shape[0] * scale)), 1)
        new_w = max(int(round(a.shape[1] * scale)), 1)
        resized = cv2.resize(a, (new_w, new_h), interpolation=cv2.INTER_AREA)
        info = {
            "resampled": True,
            "original_dimensions": {"height": int(a.shape[0]), "width": int(a.shape[1])},
            "effective_dimensions": {"height": int(new_h), "width": int(new_w)},
            "resample_factor": round(float(scale), 6),
            "interpolation": "INTER_AREA",
        }
        rmask = None
        if mask is not None:
            m = np.asarray(mask)
            rm = cv2.resize(m, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
            rmask = np.where(rm > 0, 255, 0).astype(np.uint8)
        return resized, rmask, info
    info = {
        "resampled": False,
        "original_dimensions": {"height": int(a.shape[0]), "width": int(a.shape[1])},
        "effective_dimensions": {"height": int(a.shape[0]), "width": int(a.shape[1])},
        "resample_factor": 1.0,
        "interpolation": None,
    }
    nmask = None
    if mask is not None:
        nmask = np.where(np.asarray(mask) == 0, 0, 255).astype(np.uint8)
    return a, nmask, info


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class BaselineMatcherService:
    """Run, read and list M3 baseline matcher runs over validated products.

    Inputs come from M2 derived (validated) products:
    ``derived/processing/<pair>/<processing_configuration>/<sensor>/``
    ``preprocessed_display_u16.npy`` + ``invalid_mask_u8.npy``. The images are
    display-normalized u16 (resampled with a recorded factor to
    ``max_image_dimension`` before matching). Nothing is ever processed at
    naive full resolution.
    """

    def __init__(self, settings) -> None:
        self.settings = settings
        self.cfg = m3_baseline_config()
        self.metadata_root = (
            self.settings.data_root_path / "metadata" / "m3_matching"
        )
        self.viz_dir = self.settings.data_root_path / "derived" / "visualizations" / "baseline_matching"
        self.metadata_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths
    def capabilities_public(self) -> dict[str, Any]:
        return capabilities_public(self.cfg)

    def artifact_path(self, run_id: str) -> Path:
        return self.metadata_root / f"{run_id}.json"

    def visualization_path(self, run_id: str) -> Path | None:
        art = self.read(run_id)
        if not art:
            return None
        rel = art.get("visualization_rel")
        if not rel:
            return None
        p = self.settings.data_root_path / rel
        return p if p.is_file() else None

    # ------------------------------------------------------------------ files
    def write_artifact(self, run_id: str, payload: dict[str, Any]) -> Path:
        path = self.artifact_path(run_id)
        if path.exists():
            # Never overwrite: a run id is unique by construction; if the file
            # already exists this is a defensive halt, not a silent clobber.
            raise OSError(f"Refusing to overwrite existing M3 baseline artifact {path.name}")
        atomic_write_json(path, payload)
        return path

    def read(self, run_id: str) -> dict[str, Any] | None:
        if not _safe_run_id(run_id):
            return None
        path = self.artifact_path(run_id)
        if not path.is_file():
            return None
        try:
            import json

            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    def list_runs(self, pair_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not self.metadata_root.is_dir():
            return rows
        for p in sorted(self.metadata_root.glob("*.json")):
            try:
                payload = json_load(p)
            except Exception:  # noqa: BLE001
                continue
            if payload.get("pair_id") != pair_id:
                continue
            rows.append(run_summary(payload))
        rows.sort(key=lambda r: r.get("created_at_utc") or "", reverse=True)
        return rows

    def latest_for_pair(self, pair_id: str) -> dict[str, Any] | None:
        rows = self.list_runs(pair_id)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ run
    def resolve_processed_inputs(self, pair_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return (blocker_or_none, inputs) reading M2 validated products."""
        from ..processing.service import ProcessingService

        proc = ProcessingService(self.settings)
        status = proc.read_status(pair_id)
        state = (status or {}).get("state") or ""
        if state != "READY_FOR_MATCHING":
            return {
                "error_code": ERR_PROCESSING_NOT_RUN,
                "reason": (
                    f"No validated M2 products are READY_FOR_MATCHING for pair {pair_id} "
                    f"(current state: {state or 'none'}). Run M2 PREPARE first; the baseline "
                    "matcher only consumes validated products."
                ),
            }, {}
        products = (status or {}).get("products") or {}
        if not products:
            return {
                "error_code": ERR_PROCESSING_NOT_RUN,
                "reason": (
                    f"No M2 validated products exist for pair {pair_id}. Run M2 PREPARE "
                    "first; the baseline matcher only consumes validated products."
                ),
            }, {}
        try:
            inputs = {}
            for side, key in (("a", "display_rel"), ("b", "display_rel")):
                prod = products.get(side) or {}
                display_rel = prod.get(key) or prod.get("display_rel")
                mask_rel = prod.get("mask_rel")
                base = self.settings.data_root_path
                display_path = base / display_rel
                mask_path = (base / mask_rel) if mask_rel else None
                if not display_path.is_file():
                    return {
                        "error_code": ERR_PRODUCT_MISSING,
                        "reason": f"Preprocessed display product missing for side {side.upper()}: {display_rel}",
                    }, {}
                store = np.load(display_path, mmap_mode="r")
                arr = np.asarray(store)
                mask = None
                if mask_path and mask_path.is_file():
                    mask = np.asarray(np.load(mask_path, mmap_mode="r"))
                inputs[side] = {
                    "sensor": prod.get("sensor"),
                    "array": arr,
                    "mask": mask,
                    "display_path": display_path,
                    "mask_path": mask_path,
                    "sha256": _sha256_file(display_path),
                }
            return None, inputs
        except (OSError, ValueError) as exc:
            return {
                "error_code": ERR_PRODUCT_MISSING,
                "reason": f"Could not load M2 validated products for pair {pair_id}: {exc}",
            }, {}

    def run(self, pair_id: str, matcher_id: str) -> dict[str, Any]:
        record = PairRegistry(self.settings).get(pair_id)
        if record is None:
            from ..errors import NotFoundError

            raise NotFoundError(f"No pair with ID {pair_id} is registered.")

        if matcher_id not in BASELINE_MATCHER_IDS:
            from ..errors import ValidationError

            raise ValidationError(
                f"Unknown baseline matcher {matcher_id!r}; choose one of {list(BASELINE_MATCHER_IDS)}."
            )

        created_at = _now_utc()
        run_id = self._new_run_id(pair_id, matcher_id)

        blocker, inputs = self.resolve_processed_inputs(pair_id)
        if blocker is not None:
            env = _environment_snapshot()
            payload = {
                "run_id": run_id,
                "pair_id": pair_id,
                "matcher_id": matcher_id,
                "created_at_utc": created_at,
                "status": _STATUS_BLOCKED,
                "state": "BLOCKED",
                "error_code": blocker["error_code"],
                "error_detail": blocker["reason"],
                "configuration_id": self.cfg.get("configuration_id", "MB-M3-001"),
                "configuration": _configuration_snapshot(matcher_id, self.cfg),
                "environment": env,
                "source_gate": self._source_gate(record),
                "synthetically_derived": self._synthetic(record),
                "matcher": None,
            }
            self.write_artifact(run_id, payload)
            return payload

        detector_args = resolved_detector_params(matcher_id, self.cfg)
        execution = (self.cfg.get("defaults") or {}).get("execution", {})
        max_dim = int(execution.get("max_image_dimension", 2048))
        img_a, mask_a, info_a = _resize_recorded(inputs["a"]["array"], inputs["a"]["mask"], max_dim)
        img_b, mask_b, info_b = _resize_recorded(inputs["b"]["array"], inputs["b"]["mask"], max_dim)

        matcher_input = MatcherInput(
            matcher_id=matcher_id,
            image_a=img_a,
            image_b=img_b,
            mask_a=mask_a,
            mask_b=mask_b,
            configuration=detector_args,
        )
        out: MatcherOutput = run_baseline_contract(matcher_input)

        matcher_payload = asdict(out)

        viz_rel = None
        try:
            viz_rel = self._write_visualization(run_id, out, img_a, img_b)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Baseline visualization failed for %s: %s", run_id, exc)

        payload: dict[str, Any] = {
            "run_id": run_id,
            "pair_id": pair_id,
            "matcher_id": matcher_id,
            "created_at_utc": created_at,
            "state": "SUCCESS" if out.status == _STATUS_SUCCESS else out.status,
            "status": out.status,
            "error_code": out.error_code,
            "error_detail": out.error_detail,
            "configuration_id": self.cfg.get("configuration_id", "MB-M3-001"),
            "configuration": _configuration_snapshot(matcher_id, self.cfg),
            "environment": out.environment,
            "source_gate": self._source_gate(record),
            "synthetically_derived": self._synthetic(record),
            "input": {
                "image_a": {
                    **info_a,
                    **self._side_input_meta(inputs["a"], info_a),
                    "sha256": inputs["a"]["sha256"],
                },
                "image_b": {**info_b, **self._side_input_meta(inputs["b"], info_b),
                            "sha256": inputs["b"]["sha256"]},
            },
            "license": (
                "Candidate correspondences are observations, not verified alignment; "
                "the M4 Trust Gate remains authoritative and no result here is a "
                "scientific accuracy or trust verdict."
            ),
            "visualization_rel": viz_rel,
            "matcher": matcher_payload,
        }
        self.write_artifact(run_id, payload)
        return payload

    def _side_input_meta(self, side_input: dict[str, Any], resize_info: dict[str, Any]) -> dict[str, Any]:
        arr = side_input["array"]
        mask = side_input.get("mask")
        return {
            "source_product": {
                "sensor": side_input.get("sensor"),
                "rel": str(Path(side_input["display_path"]).relative_to(self.settings.data_root_path))
                if side_input.get("display_path") else None,
            },
            "native_dimensions": {"height": int(arr.shape[0]), "width": int(arr.shape[1])},
            "mask": _describe_mask(mask),
        }

    def _source_gate(self, record) -> dict[str, Any]:
        return {
            "data_source_gate": record.data_source_gate,
            "source_class_a": record.source_class_a,
            "source_class_b": record.source_class_b,
        }

    def _synthetic(self, record) -> bool:
        ids = f"{record.source_class_a} {record.source_class_b}"
        if "FIXTURE" in ids.upper() or "fixture" in ids:
            return True
        if record.data_source_gate != "PATH_A_REAL_DATA":
            return True
        return False

    def _new_run_id(self, pair_id: str, matcher_id: str) -> str:
        while True:
            run_id = f"m3-{pair_id}-{matcher_id}-{uuid.uuid4().hex[:8]}"
            if not self.artifact_path(run_id).exists():
                return run_id

    def _write_visualization(self, run_id: str, out: MatcherOutput,
                             img_a: np.ndarray, img_b: np.ndarray) -> str | None:
        viz_cfg = (self.cfg.get("defaults") or {}).get("visualization", {})
        if not viz_cfg.get("enabled", True):
            return None
        max_lines = int(viz_cfg.get("max_lines", 120))
        max_side = int(viz_cfg.get("max_side_px", 960))
        cands = out.correspondences
        if not cands:
            return None

        a = _as_u8_2d(img_a)
        b = _as_u8_2d(img_b)

        def scale_for(img: np.ndarray, limit: int) -> tuple[np.ndarray, float]:
            longest = max(img.shape)
            if longest <= limit:
                return img, 1.0
            f = limit / float(longest)
            nh = max(int(round(img.shape[0] * f)), 1)
            nw = max(int(round(img.shape[1] * f)), 1)
            return cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA), f

        a, fa = scale_for(a, max_side)
        b, fb = scale_for(b, max_side)
        gap = 12
        height = max(a.shape[0], b.shape[0])
        canvas = np.zeros((height, a.shape[1] + gap + b.shape[1], 3), dtype=np.uint8)
        canvas[: a.shape[0], : a.shape[1]] = cv2.cvtColor(a, cv2.COLOR_GRAY2BGR)
        canvas[: b.shape[0], a.shape[1] + gap:] = cv2.cvtColor(b, cv2.COLOR_GRAY2BGR)

        offset_x = a.shape[1] + gap
        lines = cands[:max_lines]
        rng = np.random.default_rng(20260321)  # deterministic palette, but nothing here is a verdict
        for i, c in enumerate(lines):
            color = (int(rng.integers(40, 220)), int(rng.integers(40, 200)), 255)
            p1 = (int(c["x_a"] * fa), int(c["y_a"] * fa))
            p2 = (int(c["x_b"] * fb) + offset_x, int(c["y_b"] * fb))
            cv2.line(canvas, p1, p2, color, 1, cv2.LINE_AA)
        if a.shape[0] < height:
            canvas[a.shape[0]:, :a.shape[1]] = 20
        if b.shape[0] < height:
            canvas[b.shape[0]:, offset_x:] = 20

        self.viz_dir.mkdir(parents=True, exist_ok=True)
        vpath = self.viz_dir / f"{run_id}.png"
        ok = cv2.imwrite(str(vpath), canvas)
        if not ok:
            return None
        return str(Path(vpath).relative_to(self.settings.data_root_path))


def run_summary(payload: dict[str, Any]) -> dict[str, Any]:
    matcher = payload.get("matcher") or {}
    scores = matcher.get("scores") or {}
    return {
        "run_id": payload.get("run_id"),
        "pair_id": payload.get("pair_id"),
        "matcher_id": payload.get("matcher_id"),
        "status": payload.get("status"),
        "state": payload.get("state"),
        "created_at_utc": payload.get("created_at_utc"),
        "configuration_id": payload.get("configuration_id"),
        "error_code": payload.get("error_code"),
        "error_detail": payload.get("error_detail"),
        "synthetically_derived": payload.get("synthetically_derived"),
        "source_gate": payload.get("source_gate"),
        "counts": {
            "keypoints_a": matcher.get("keypoint_count_a", 0),
            "keypoints_b": matcher.get("keypoint_count_b", 0),
            "candidates": matcher.get("candidate_match_count", 0),
        },
        "scores": scores,
        "runtime_ms": matcher.get("runtime_ms"),
        "visualization_rel": payload.get("visualization_rel"),
        "license": payload.get("license"),
    }


def _safe_run_id(run_id: str) -> bool:
    import re

    return bool(re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id or ""))


def _now_utc() -> str:
    from ..config import rfc3339_now

    return rfc3339_now()


def json_load(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))