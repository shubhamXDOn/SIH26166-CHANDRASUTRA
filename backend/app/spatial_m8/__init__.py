"""M8 SPATIAL RELIABILITY & BALANCED CORRESPONDENCE SELECTION.

Consumes an ACCEPTED M7 trust gate artifact and its referenced M3/M4 matcher
run, recovers the trusted inlier correspondences by deterministic geometric
re-verification (never by re-deciding the M7 verdict), computes per-side
spatial bookkeeping evidence in the declared effective matcher plane, and
records a deterministic GRID_BALANCED selection as a never-overwritten
artifact under ``data/metadata/m8_spatial``.

This layer:
    * never overrides, mutates or downgrades an M7 verdict;
    * never introduces points absent from the M7 trusted set;
    * never claims accuracy, probability or registration semantics
      (reference_status stays REFERENCE_UNAVAILABLE);
    * is deterministic (no RNG anywhere) and O(N)/O(N log N).
"""

from . import states  # noqa: F401
from .config import SpatialSelectionConfig, load_spatial_selection_config  # noqa: F401
from .engine import analyze_and_select  # noqa: F401
from .service import SpatialSelectionService  # noqa: F401
from .recovery import recover_trusted  # noqa: F401
from . import contract  # noqa: F401

__all__ = [
    "SpatialSelectionConfig",
    "load_spatial_selection_config",
    "analyze_and_select",
    "SpatialSelectionService",
    "recover_trusted",
    "contract",
    "states",
]