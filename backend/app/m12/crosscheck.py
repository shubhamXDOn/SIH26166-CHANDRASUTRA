"""M12 AI cross-check validator (evidence-grounded response auditing).

Independent validation of an AI explanation produced over the M9 evidence
packet. The validator trusts nothing the model says; it checks that every
claim is grounded in the evidence that actually exists and that no forbidden
claim is made. Fully deterministic and unit-testable.

Violation codes:
    * UNGROUNDED_NUMBER          — numeric value not present in the evidence
    * PHYSICAL_ACCURACY_CLAIM    — CE90/LE90 physical accuracy without reference
    * MATCHER_CONFIDENCE_AS_TRUTH— matcher confidence framed as accuracy/truth
    * BLOCKED_AS_SUCCESS         — blocked/failed stage reported as complete
    * SYNTHETIC_AS_REAL          — TEST_FIXTURE evidence described as real data
    * ABSOLUTE_PATH_LINKAGE      — absolute paths leaked into the answer
"""

from __future__ import annotations

import json
import re
from typing import Any

_ABS_WINDOWS = re.compile(r"[A-Za-z]:[\\/][^\s\",{}]+")
_ABS_POSIX = re.compile(r"(?<![\w.])/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+){1,}")
_PHYSICAL_ACCURACY = re.compile(
    r"(?i)\b(ce90|le90|physical accuracy|absolute accuracy|cross-track error|"
    r"along-track error|geolocation accuracy)\b")
_MATCHER_CONFIDENCE_AS_TRUTH = re.compile(
    r"(?i)\b(matcher|matching|deep matcher)\b.{0,30}\b(score|confidence|probability)\b.{0,30}"
    r"\b\d+(?:[.,]\d+)?%?\b.{0,40}\b(accuracy|verif)\b")
_FULL_SUCCESS_CLAIM = re.compile(
    r"(?i)((entire|full|whole)\s+(pipeline|process|system|flow)|all\s+(stages|steps|milestones))"
    r".{0,60}(complete|successful|finished|ready for science|converged)")
_REAL_DATA_CLAIM = re.compile(
    r"(?i)(real|actual|authentic|original)\s+(chandrayaan(-2)?|ohrc|tmc-2|tmc2|isro)\b|"
    r"observed\s+(ohrc|tmc-2|tmc2)\s+data")
_SYNTHETIC_MARKERS = re.compile(r"(?i)(TEST_FIXTURE|test fixture|synthetic)")
_NUMBER = re.compile(r"(?<![A-Za-z_])-?\d+(?:[.,]\d+)?(?![A-Za-z_])")

VIOLATION_CODES = (
    "UNGROUNDED_NUMBER", "PHYSICAL_ACCURACY_CLAIM", "MATCHER_CONFIDENCE_AS_TRUTH",
    "BLOCKED_AS_SUCCESS", "SYNTHETIC_AS_REAL", "ABSOLUTE_PATH_LINKAGE",
)


def _norm(value: float) -> str:
    return f"{value:.6g}"


def _evidence_number_bag(packet: dict[str, Any]) -> set[str]:
    bag: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)
        elif isinstance(value, (int, float)) and value is not None:
            bag.add(_norm(float(value)))
        elif isinstance(value, str):
            for tok in _NUMBER.findall(value):
                try:
                    bag.add(_norm(float(tok.replace(",", ""))))
                except ValueError:
                    continue

    walk(packet)
    return bag


def _packet_text(packet: dict[str, Any]) -> str:
    return json.dumps(packet, default=str, sort_keys=True)


def validate_ai_response(packet: dict[str, Any], response: str) -> dict[str, Any]:
    """Deterministically audit a candidate AI answer against the evidence."""
    violations: list[dict[str, str]] = []
    response = response or ""
    text = _packet_text(packet)
    number_bag = _evidence_number_bag(packet)

    claimed_numbers: set[str] = set()
    for tok in _NUMBER.findall(response):
        try:
            claimed_numbers.add(_norm(float(tok.replace(",", ""))))
        except ValueError:
            continue
    ungrounded = sorted(c for c in claimed_numbers if c not in number_bag)
    if ungrounded:
        violations.append({
            "code": "UNGROUNDED_NUMBER",
            "detail": "numeric claim absent from the evidence packet",
            "evidence": ", ".join(ungrounded[:10]),
        })

    if _PHYSICAL_ACCURACY.search(response):
        violations.append({
            "code": "PHYSICAL_ACCURACY_CLAIM",
            "detail": "physical accuracy asserted without a reference dataset",
            "evidence": "reference_dataset is NOT_AVAILABLE",
        })

    if _MATCHER_CONFIDENCE_AS_TRUTH.search(response):
        violations.append({
            "code": "MATCHER_CONFIDENCE_AS_TRUTH",
            "detail": "matcher confidence/score framed as alignment accuracy",
            "evidence": "deep/matcher scores are engineering diagnostics, not truth",
        })

    blocked = bool(re.search(r"(?i)\b(BLOCKED|NOT_RUN|NOT_AVAILABLE|FAILED)\w*", text))
    if blocked and _FULL_SUCCESS_CLAIM.search(response):
        violations.append({
            "code": "BLOCKED_AS_SUCCESS",
            "detail": "a blocked/failed stage reported as pipeline completion",
            "evidence": "pipeline_state contains non-complete stages",
        })

    if _SYNTHETIC_MARKERS.search(text) and _REAL_DATA_CLAIM.search(response):
        violations.append({
            "code": "SYNTHETIC_AS_REAL",
            "detail": "TEST_FIXTURE/synthetic evidence described as real mission data",
            "evidence": "geometry source is TEST_FIXTURE",
        })

    if _ABS_WINDOWS.search(response) or _ABS_POSIX.search(response):
        violations.append({
            "code": "ABSOLUTE_PATH_LINKAGE",
            "detail": "absolute path leaked into the answer",
            "evidence": "answers must reference evidence by relative identifier only",
        })

    return {
        "status": "CLEAR" if not violations else "VIOLATIONS",
        "violations": violations,
        "claimed_numbers": sorted(claimed_numbers),
    }


def validate_packet_integrity(packet: dict[str, Any], recorded_digest: str | None) -> dict[str, Any]:
    """Re-derive the canonical packet digest and compare with the recorded one."""
    try:
        from backend.app.ai.evidence import canonical_digest
        recomputed = canonical_digest(packet)
    except Exception:  # noqa: BLE001
        return {"status": "ERROR", "detail": "digest recomputation failed"}
    match = recorded_digest is None or recomputed == recorded_digest
    return {
        "status": "VERIFIED" if match else "INTEGRITY_MISMATCH",
        "recomputed_digest": recomputed,
        "recorded_digest": recorded_digest,
    }


__all__ = [
    "VIOLATION_CODES",
    "validate_ai_response",
    "validate_packet_integrity",
]