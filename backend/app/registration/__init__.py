"""M6 — Registration Engine, Verified Alignment & Jury-Ready Registration Workspace.

Consumes M5 selected_correspondences.npz, fits a transform (homography preferred, affine fallback),
validates it, warps the source image, and produces a registered output with full provenance.

All numbers are engineering diagnostics — never scientific proof of physical truth.
"""

from __future__ import annotations
