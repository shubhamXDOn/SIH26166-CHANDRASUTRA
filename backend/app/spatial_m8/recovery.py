"""M8 SPATIAL — deterministic recovery of the M7 trusted correspondence set.

The M7 artifact records inlier/trust counts but never the trusted coordinates
(by design). M8 recovers the exact trusted set by re-running the same
geometric verification with the SNAPSHOTTED M7 configuration against the
referenced M3/M4 matcher artifact, then verifies the recovered result is
identical to the recorded M7 verdict and evidence.

This is explicit validation/audit re-verification, never a new decision:
if the reproduced decision or inlier counts differ from the recorded M7
artifact, recovery is BLOCKED (NONDETERMINISTIC_RECOVERY) instead of silently
re-deriving a "new" trust verdict.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from . import states


def _json_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _mirror_dedup(coords: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Mirror the M7 engine's dedup (keep-first, rounding to 6 dp)."""
    n = len(coords)
    seen: dict[tuple, int] = {}
    first_idx: list[int] = []
    for i in range(n):
        key = (
            round(float(coords[i, 0]), 6), round(float(coords[i, 1]), 6),
            round(float(coords[i, 2]), 6), round(float(coords[i, 3]), 6),
        )
        if key not in seen:
            seen[key] = i
            first_idx.append(i)
    return coords[first_idx], first_idx


def _extract_correspondences(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    matcher = payload.get("matcher")
    if not isinstance(matcher, dict):
        return None
    corr = matcher.get("correspondences")
    if not isinstance(corr, list):
        return None
    return [c for c in corr if isinstance(c, dict)]


def _coords_from_correspondences(corr: list[dict[str, Any]]) -> np.ndarray:
    rows = []
    for c in corr:
        rows.append([c["x_a"], c["y_a"], c["x_b"], c["y_b"]])
    return np.asarray(rows, dtype=np.float64)


def _side_dims(input_meta: dict[str, Any], side: str) -> dict[str, Any]:
    image = input_meta.get(side) or {}
    dims = image.get("effective_dimensions") or {}
    return {"height": dims.get("height"), "width": dims.get("width")}


def recover_trusted(
    trust_artifact: dict[str, Any],
    matcher_payload: dict[str, Any],
) -> dict[str, Any]:
    """Recover the deterministic trusted correspondence set from the M7 pair.

    Returns ``{"state": "RECOVERY_OK", "trusted": [...], "dims_a": ...,
    "dims_b": ...}`` or a ``BLOCKED`` / ``ABSTAIN`` decision dict.
    """

    def blocked(code: str, explanation: str) -> dict[str, Any]:
        return {
            "state": states.BLOCKED,
            "decision": {
                "state": states.BLOCKED, "reasons": [code],
                "explanation": explanation,
                "block_code": code, "abstain_code": None,
            },
            "trusted": [],
        }

    recorded_decision = trust_artifact.get("decision") or {}
    if recorded_decision.get("state") != "ACCEPT":
        return blocked(
            states.TRUST_NOT_ACCEPTED,
            f"Recovery requires an ACCEPTED M7 trust run; recorded state is "
            f"{recorded_decision.get('state')!r}. The M7 verdict is never overridden.",
        )

    cfg_raw = trust_artifact.get("configuration")
    if not isinstance(cfg_raw, dict):
        return blocked(
            states.MATCH_RUN_UNRECOVERABLE,
            "The M7 artifact does not carry its configuration snapshot; the exact "
            "verification configuration cannot be reproduced.",
        )
    from ..trust_gate.config import TrustGateConfig

    try:
        cfg = TrustGateConfig.from_dict(cfg_raw)
    except (TypeError, ValueError) as exc:  # noqa: BLE001
        return blocked(
            states.MATCH_RUN_UNRECOVERABLE,
            f"Could not reconstruct the M7 configuration snapshot: {exc}",
        )

    input_meta = matcher_payload.get("input") or {}
    dims_a = _side_dims(input_meta, "image_a")
    dims_b = _side_dims(input_meta, "image_b")
    if not (dims_a.get("height") and dims_a.get("width")
            and dims_b.get("height") and dims_b.get("width")):
        return blocked(
            states.INVALID_COORDINATE_FRAME,
            "The referenced matcher artifact does not declare effective dimensions "
            "for both sides; recovery cannot assign a coordinate frame.",
        )

    corr = _extract_correspondences(matcher_payload)
    if not corr:
        return blocked(
            states.MATCH_RUN_UNRECOVERABLE,
            "The referenced matcher artifact carries no candidate correspondences; "
            "the M7 trusted set cannot be reproduced.",
        )

    coords = _coords_from_correspondences(corr)
    from ..trust_gate.engine import verify

    recovered = verify(coords, cfg)
    if recovered["decision"] != recorded_decision:
        return blocked(
            states.NONDETERMINISTIC_RECOVERY,
            "Re-running the M7 verification produced a decision different from the "
            "recorded artifact; the trusted set cannot be recovered deterministically.",
        )
    if _json_hash(recovered["decision"]) != trust_artifact.get("decision_hash"):
        return blocked(
            states.NONDETERMINISTIC_RECOVERY,
            "Recomputed M7 decision hash does not match the recorded artifact; "
            "the trusted set cannot be recovered deterministically.",
        )

    evidence = trust_artifact.get("evidence") or {}
    dedup, first_idx = _mirror_dedup(coords)
    if int(dedup.shape[0]) != evidence.get("deduplicated_candidate_count"):
        return blocked(
            states.NONDETERMINISTIC_RECOVERY,
            "Deduplicated candidate count disagrees with the recorded M7 artifact; "
            "recovery refused rather than guessing.",
        )

    model = recovered["evidence"].get("model") or {}
    matrix_raw = model.get("model_matrix")
    if matrix_raw is None:
        return blocked(
            states.NONDETERMINISTIC_RECOVERY,
            "The recovered model matrix is unavailable; recovery refused.",
        )
    matrix = np.asarray(matrix_raw, dtype=np.float64)
    pts_a = dedup[:, :2]
    pts_b = dedup[:, 2:]
    from ..trust.geometry import _compute_residuals_forward

    residuals = _compute_residuals_forward(pts_a, pts_b, matrix)
    threshold = float(cfg.geometry.ransac.inlier_threshold_px)
    mask = residuals < threshold
    inlier_count = int(np.sum(mask))
    if inlier_count != evidence.get("inlier_count"):
        return blocked(
            states.NONDETERMINISTIC_RECOVERY,
            f"Recovered inlier count {inlier_count} disagrees with the recorded "
            f"M7 count {evidence.get('inlier_count')}; recovery refused.",
        )

    entries: list[dict[str, Any]] = []
    for j in np.where(mask)[0]:
        idx = first_idx[int(j)]
        original = corr[idx]
        entries.append({
            "m8_index": len(entries),
            "m7_index": idx,
            "match_index_a": original.get("match_index_a"),
            "match_index_b": original.get("match_index_b"),
            "x_a": float(original["x_a"]),
            "y_a": float(original["y_a"]),
            "x_b": float(original["x_b"]),
            "y_b": float(original["y_b"]),
            "score": original.get("score"),
            "descriptor_distance": original.get("descriptor_distance"),
            "residual": float(residuals[int(j)]),
        })

    return {
        "state": states.RECOVERY_OK,
        "trusted": entries,
        "dims_a": dims_a,
        "dims_b": dims_b,
        "recovered_decision_hash": trust_artifact.get("decision_hash"),
        "trusted_chain": "M7 ACCEPT -> deterministic re-verification -> M8 trusted set",
    }


__all__ = ["recover_trusted"]