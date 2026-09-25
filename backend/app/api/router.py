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

from . import ai, auth, conditions, data, health, m12, m13, matching, metrics, metrics_m10, ops, pairs, processing, registration, registration_m9, routing, spatial, spatial_m8, trust, trust_gate

api_router = APIRouter(prefix="/api")

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(data.router)
api_router.include_router(pairs.router)
api_router.include_router(processing.router)
api_router.include_router(matching.router)
api_router.include_router(routing.capability_router)
api_router.include_router(routing.routing_router)
api_router.include_router(routing.pair_router)
api_router.include_router(conditions.router)
api_router.include_router(trust.router)
api_router.include_router(trust_gate.trust_router)
api_router.include_router(trust_gate.pair_router)
api_router.include_router(spatial.router)
api_router.include_router(spatial_m8.spatial_router)
api_router.include_router(spatial_m8.pair_router)
api_router.include_router(registration.router)
api_router.include_router(registration_m9.reg_router)
api_router.include_router(registration_m9.pair_router)
api_router.include_router(metrics.router)
api_router.include_router(metrics_m10.router)
api_router.include_router(ai.router)
api_router.include_router(ops.router)
api_router.include_router(m12.router)
api_router.include_router(m13.router)

# Future namespaces registered here, never before they are real:
# analysis = APIRouter(prefix="/analysis")
# results  = APIRouter(prefix="/results")


__all__ = ["api_router"]