"""M9 Registration / Image Alignment package.

Consumes one usable M8 spatial-selection artifact, estimates a declared
geometric transform (smallest-valid policy: affine preferred, normalized-DLT
homography on explicit escalation only), validates transform and inputs
independently, records residual diagnostics in px of the effective matcher
plane and produces a derived aligned/warped output. Never rewrites M7/M8,
never claims physical accuracy, never overwrites artifacts.
"""

from . import states  # noqa: F401
from .config import RegistrationM9Config, load_registration_m9_config  # noqa: F401
from .contract import assert_artifact_valid, assert_artifact_vocabulary_safe, license_text  # noqa: F401
from .fit import choose_and_fit  # noqa: F401
from .points import validate_selected_points  # noqa: F401
from .validate import validate_transform  # noqa: F401
from .service import RegistrationM9Service, m9_run_summary  # noqa: F401

__all__ = [
    "RegistrationM9Config",
    "RegistrationM9Service",
    "assert_artifact_valid",
    "assert_artifact_vocabulary_safe",
    "choose_and_fit",
    "license_text",
    "load_registration_m9_config",
    "m9_run_summary",
    "states",
    "validate_selected_points",
    "validate_transform",
]