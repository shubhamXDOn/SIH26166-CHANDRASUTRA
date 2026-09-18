"""M6 state + reason-code vocabulary for registration.

Binary, measurable, explainable outcomes. No scientific alignment claim.
"""

from __future__ import annotations

from enum import Enum


class RegistrationRunState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    INSUFFICIENT = "INSUFFICIENT"


class RegistrationBlockCode(str, Enum):
    M5_NOT_AVAILABLE = "M5_NOT_AVAILABLE"
    M5_NOT_COMPLETE = "M5_NOT_COMPLETE"
    NO_SELECTION = "NO_SELECTION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    COORDINATE_LOAD_FAILED = "COORDINATE_LOAD_FAILED"
    MAPPING_LOAD_FAILED = "MAPPING_LOAD_FAILED"
    UNKNOWN_CONFIG = "UNKNOWN_CONFIG"


class TransformType(str, Enum):
    HOMOGRAPHY = "HOMOGRAPHY"
    AFFINE = "AFFINE"


class TransformSelectionReason(str, Enum):
    PREFERRED = "PREFERRED"
    FALLBACK_DEGENERATE = "FALLBACK_DEGENERATE"
    FALLBACK_INSUFFICIENT_INLIERS = "FALLBACK_INSUFFICIENT_INLIERS"


class RegistrationValidationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT = "INSUFFICIENT"
