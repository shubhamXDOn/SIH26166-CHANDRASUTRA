"""Top-level API router. Central, predictable API surface.

Future route namespaces (implemented in later milestones only):

    /api/auth/...
    /api/data/...
    /api/pairs/...
    /api/preprocess/...
    /api/analysis/...
    /api/results/...
    /api/ai/...
"""

from __future__ import annotations

from fastapi import APIRouter

from . import ai, auth, data, health, pairs

api_router = APIRouter(prefix="/api")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(data.router)
api_router.include_router(pairs.router)
api_router.include_router(ai.router)

# Future namespaces registered here, never before they are real:
# pairs    = APIRouter(prefix="/pairs")
# preprocess = APIRouter(prefix="/preprocess")
# analysis = APIRouter(prefix="/analysis")
# results  = APIRouter(prefix="/results")


__all__ = ["api_router"]