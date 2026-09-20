"""Top-level API router. Central, predictable API surface.

Future route namespaces (implemented in later milestones only):

    /api/auth/...
    /api/data/...
    /api/pairs/...
    /api/processing/...
    /api/analysis/...
    /api/results/...
    /api/ai/...
"""

from __future__ import annotations

from fastapi import APIRouter

from . import ai, auth, data, health, m12, m13, matching, metrics, ops, pairs, processing, registration, spatial, trust

api_router = APIRouter(prefix="/api")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(data.router)
api_router.include_router(pairs.router)
api_router.include_router(processing.router)
api_router.include_router(matching.router)
api_router.include_router(trust.router)
api_router.include_router(spatial.router)
api_router.include_router(registration.router)
api_router.include_router(metrics.router)
api_router.include_router(ai.router)
api_router.include_router(ops.router)
api_router.include_router(m12.router)
api_router.include_router(m13.router)

# Future namespaces registered here, never before they are real:
# analysis = APIRouter(prefix="/analysis")
# results  = APIRouter(prefix="/results")


__all__ = ["api_router"]