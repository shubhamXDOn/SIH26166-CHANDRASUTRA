"""Read-only funnel/evidence extraction over settled M3..M9 artefacts.

The benchmark controller is a *reader*.  It never re-runs matcher, trust,
spatial or registration logic; it reads the last settled artefact for a pair
at each milestone and describes what was observed.  When an artefact is
absent, the stage reports ``stage_observed: False`` and returns ``None`` for
that stage's numeric evidence -- never a fabricated zero or a re-derived
value.

The three-way policy from ``states.py`` is applied: a pair whose later
stages are unavailable is NOT marked FAILED just because of the gap; the
earliest missing required artefact is surfaced with an explicit reason
(MATCH_RUN_NOT_AVAILABLE / TRUST_NOT_AVAILABLE / SPATIAL_NOT_AVAILABLE),
while downstream stages stay None.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from .taxonomy import is_failed, is_abstain

_STAGE_BY_NAME = {
    "matching": "matching",
    "trust": "trust_gate",
    "spatial": "spatial_selection",
    "registration": "registration",
}


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Normalised outlook per upstream milestone: mapping real statuses to the
# collapsed M10 policy vocabulary (COMPLETE / FAILED / ABSTAIN / BLOCKED).
_REGISTERED_OK = {"SUCCESS", "SUCCESS_WITH_WARNINGS", "COMPLETE", "REGISTERED"}
_REGISTERED_FAIL = {
    "FAILED", "TRANSFORM_FIT_ERROR", "WARP_FAILED", "ARTIFACT_WRITE_FAILED",
    "VALUES_NOT_FINITE", "REGISTRATION_FAILED",
}
_SPATIAL_OK = {"SELECTED", "SELECTED_WITH_WARNINGS", "COMPLETE"}
_TRUST_OK = {"ACCEPT", "COMPLETE", "VERIFIED"}

# Upstream abstention codes that mean "insufficient evidence to reach the
# downstream stage" -- reported as ABSTAIN, never as a failure.
_ABSTAIN_CODES = {
    "ABSTAIN", "SPARSE_EVIDENCE", "MARGINAL_EVIDENCE", "BUDGET_EXCEEDED",
    "INSUFFICIENT_CANDIDATES", "INSUFFICIENT_INLIERS", "LOW_INLIER_RATIO",
    "INSUFFICIENT_SELECTED_POINTS", "DEGENERATE_GEOMETRY", "NO_VALID_MODEL",
    "NO_VALID_TRANSFORM", "ZERO_CANDIDATES", "RESIDUAL_EXCEEDED",
    "MODEL_INVALID", "SPATIAL_SANITY_FAILED",
}


def _normalise(state: str | None, *, ok_set: set[str], fail_set: set[str]) -> str | None:
    """Map an upstream state string onto the collapsed M10 vocabulary."""
    if not state:
        return None
    up = state.upper()
    if up in _REGISTERED_FAIL or up in fail_set:
        return "FAILED"
    if up in _ABSTAIN_CODES:
        return "ABSTAIN"
    if up in ok_set:
        return "COMPLETE"
    return None


def _pick(d: dict[str, Any] | None, *keys: str) -> Any:
    if not d:
        return None
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return None


def read_matching(match_service: Any, pair_id: str) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "matching",
        "stage_observed": False,
        "candidate_count": None,
        "state": None,
        "matcher_family": None,
        "run_id": None,
    }
    try:
        latest = None
        for fn in ("find_run_for_pair", "latest_for_pair"):
            if hasattr(match_service, fn):
                try:
                    latest = getattr(match_service, fn)(pair_id)
                except Exception:
                    latest = None
                if latest is not None:
                    break
        summary = getattr(match_service, "summary", None)
        if summary is not None:
            try:
                s = summary(pair_id)
                if s:
                    latest = s
            except Exception:
                pass
        if not latest:
            return record
        raw_state = _pick(latest, "state", "status", "outcome")
        if str(raw_state).upper() in ("", "NOT_STARTED"):
            # A registered pair record with nothing run yet is not a match
            # artifact; the matching stage is genuinely unobserved.
            return record
        record["stage_observed"] = True
        record["state"] = _normalise(raw_state, ok_set=_REGISTERED_OK, fail_set=_REGISTERED_FAIL)
        record["matcher_family"] = _pick(latest, "matcher_family", "family")
        record["run_id"] = _pick(latest, "run_id", "matching_run_id")
        cand = _pick(
            latest, "candidate_count", "candidates", "total_candidates", "matched_count"
        )
        record["candidate_count"] = _number(cand)
        return record
    except Exception:
        return record


def read_trust(trust_service: Any, pair_id: str, trust_run_id: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "trust_gate",
        "stage_observed": False,
        "verified_count": None,
        "inlier_count": None,
        "state": None,
        "run_id": None,
    }
    try:
        latest = None
        if trust_run_id and hasattr(trust_service, "read"):
            latest = trust_service.read(trust_run_id)
        if not latest and hasattr(trust_service, "latest_for_pair"):
            latest = trust_service.latest_for_pair(pair_id)
        if not latest:
            return record
        record["stage_observed"] = True
        record["state"] = _normalise(_pick(latest, "state", "status", "outcome", "decision"), ok_set=_TRUST_OK, fail_set=_REGISTERED_FAIL)
        record["run_id"] = _pick(latest, "run_id", "trust_run_id")
        record["verified_count"] = _number(
            _pick(latest, "verified_count", "verified", "inlier_count", "inliers")
        )
        record["inlier_count"] = _number(
            _pick(latest, "inlier_count", "inliers", "verified_count", "verified")
        )
        return record
    except Exception:
        return record


def read_spatial(spatial_service: Any, pair_id: str, spatial_run_id: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "spatial_selection",
        "stage_observed": False,
        "selected_count": None,
        "state": None,
        "run_id": None,
    }
    try:
        latest = None
        if spatial_run_id and hasattr(spatial_service, "read"):
            latest = spatial_service.read(spatial_run_id)
        if not latest and hasattr(spatial_service, "latest_for_pair"):
            latest = spatial_service.latest_for_pair(pair_id)
        if not latest:
            return record
        record["stage_observed"] = True
        record["state"] = _normalise(_pick(latest, "state", "status", "outcome"), ok_set=_SPATIAL_OK, fail_set=_REGISTERED_FAIL)
        record["run_id"] = _pick(latest, "run_id", "spatial_run_id")
        record["selected_count"] = _number(
            _pick(latest, "selected_count", "selected", "count")
        )
        return record
    except Exception:
        return record


def read_registration(reg_service: Any, pair_id: str, reg_run_id: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": "registration",
        "stage_observed": False,
        "registered_count": None,
        "registration_rmse_px": None,
        "registration_p95_px": None,
        "state": None,
        "run_id": None,
    }
    try:
        latest = None
        if reg_run_id and hasattr(reg_service, "read"):
            latest = reg_service.read(reg_run_id)
        if not latest and hasattr(reg_service, "latest_for_pair"):
            latest = reg_service.latest_for_pair(pair_id)
        if not latest:
            return record
        record["stage_observed"] = True
        record["state"] = _normalise(_pick(latest, "state", "status", "outcome"), ok_set=_REGISTERED_OK, fail_set=_REGISTERED_FAIL)
        record["run_id"] = _pick(latest, "run_id", "registration_run_id")
        record["registered_count"] = _number(
            _pick(latest, "registered_count", "registered", "inlier_count", "inliers")
        )
        record["registration_rmse_px"] = _number(
            _pick(latest, "rmse_px", "rmse", "registration_rmse_px", "residual_rmse_px")
        )
        record["registration_p95_px"] = _number(
            _pick(latest, "p95_px", "p95", "residual_p95_px", "registration_p95_px")
        )
        return record
    except Exception:
        return record


class FunnelEvidence:
    """Read-only funnel evidence for one pair across the six stages."""

    def __init__(
        self,
        pair_id: str,
        matching: dict[str, Any] | None,
        trust: dict[str, Any] | None,
        spatial: dict[str, Any] | None,
        registration: dict[str, Any] | None,
    ) -> None:
        self.pair_id = pair_id
        self.stages: dict[str, dict[str, Any]] = {}
        self.stages["input_gate"] = {"stage": "input_gate", "stage_observed": True}
        self.stages["matching"] = matching or {"stage": "matching", "stage_observed": False}
        self.stages["trust_gate"] = trust or {"stage": "trust_gate", "stage_observed": False}
        self.stages["spatial_selection"] = spatial or {
            "stage": "spatial_selection", "stage_observed": False,
        }
        self.stages["registration"] = registration or {
            "stage": "registration", "stage_observed": False,
        }

    def model_dump(self) -> dict[str, Any]:
        return {"pair_id": self.pair_id, "stages": self.stages}

    def earliest_missing(self) -> dict[str, str] | None:
        order = ("matching", "trust_gate", "spatial_selection", "registration")
        for stage in order:
            rec = self.stages.get(stage) or {}
            if not rec.get("stage_observed"):
                code = {
                    "matching": "MATCH_RUN_NOT_AVAILABLE",
                    "trust_gate": "TRUST_NOT_AVAILABLE",
                    "spatial_selection": "SPATIAL_NOT_AVAILABLE",
                    "registration": "REGISTRATION_NOT_AVAILABLE",
                }[stage]
                return {"stage": stage, "reason": code}
        return None

    def run_state(self, allow_abstain: bool = True) -> str:
        """Collapse the funnel into a settled state.

        A registration observed as COMPLETE is only trusted when the whole
        earlier funnel was observed (a missing candidate stage invalidates a
        later COMPLETE); the earliest missing stage is surfaced with its
        explicit reason and becomes an ABSTAIN (sparse evidence) or, when the
        matching stage itself has no artifact at all, a BLOCKED run that is
        never recorded as an outcome.
        """
        missing = self.earliest_missing()
        reg = self.stages.get("registration") or {}
        spa = self.stages.get("spatial_selection") or {}
        tru = self.stages.get("trust_gate") or {}
        mat = self.stages.get("matching") or {}
        if not missing and reg.get("stage_observed") and reg.get("state"):
            if is_failed(reg.get("state")):
                return "FAILED"
            if reg.get("state") == "COMPLETE":
                return "COMPLETE"
            if is_abstain(reg.get("state")):
                return "ABSTAIN"
        if missing:
            if missing["stage"] == "matching" and not mat.get("stage_observed"):
                return "FAILED" if mat.get("state") else "BLOCKED"
            return "ABSTAIN" if allow_abstain else "FAILED"
        if spa.get("state") and is_failed(spa.get("state")):
            return "FAILED"
        if tru.get("state") and is_failed(tru.get("state")):
            return "FAILED"
        return "BLOCKED"


def read_funnel(settings: Settings, services: dict[str, Any], pair_id: str, *, variant: Any = None) -> FunnelEvidence:
    """Read the funnel for one pair using the provided service accessors.

    ``services`` must expose at most one object per milestone.  Missing
    milestone objects are treated as an unavailable stage (never a computed
    value).  Variant-aware availability is respected: a FIXED_DEEP variant
    still reads the same artefacts but reports its own availability gate.
    """
    matcher = services.get("matching")
    trust = services.get("trust")
    spatial = services.get("spatial")
    registration = services.get("registration")

    matching = read_matching(matcher, pair_id) if matcher else None
    trust_rec = read_trust(trust, pair_id) if trust else None
    spatial_rec = read_spatial(spatial, pair_id) if spatial else None
    reg_rec = read_registration(registration, pair_id) if registration else None

    if variant is not None and getattr(variant, "availability", "AVAILABLE") != "AVAILABLE":
        # Availability-gated variants (e.g. FIXED_DEEP when weights missing)
        # are NOT failures: downstream reads stay None and the variant guard
        # is reported by the controller.
        reg_rec = {**(reg_rec or {}), "state": None}

    return FunnelEvidence(pair_id, matching, trust_rec, spatial_rec, reg_rec)
