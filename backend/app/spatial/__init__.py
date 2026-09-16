"""M5 Spatial Reliability & Reliability-Aware Selection.

Deterministic spatial evidence representation over the M2 pair-overlap scene,
built from M3 candidates and M4 trusted tile evidence. No registration (M6)
and no scientific confidence numbers are produced here.
"""

from backend.app.spatial.service import SpatialService

__all__ = ["SpatialService"]