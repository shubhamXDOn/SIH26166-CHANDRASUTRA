"""AI assistant endpoints — REAL Gemini assistant (M9), M10-authenticated.

The frontend always talks to *this* backend for AI. The Gemini key is a
backend-only secret and is never exposed to the browser.

Every task returns the M9 envelope on success:
    {status, request_id, task, pair_id, answer, evidence[], limitations[],
     suggested_inspections[], usage, ai, created_at}
Failures (not configured, provider errors, validation refusals) surface
through the unified error envelope — never as a fabricated answer.

Since M10, the AI *execution* endpoints require an authenticated session
(any role). Identity is recorded only as contextual provenance metadata and
never enters the scientific digests.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from ..ai import AIRequest, AITask
from ..auth.dependencies import AuthServiceDeps, CurrentUser, current_user_dep
from ..state import get_state

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(current_user_dep)])


def _assistant():
    return get_state().assistant


def _identity(current) -> dict[str, str] | None:
    if current is None:
        return None
    return {"user_id": current.id, "username": current.username, "role": current.role}


def _run(task: str, payload: AIRequest, current: CurrentUser, *, full_evidence: bool = False) -> dict:
    return _assistant().execute(
        task=task,
        pair_id=payload.pair_id,
        scope=payload.scope,
        question=payload.question,
        session_id=payload.session_id,
        experiment_id=payload.experiment_id,
        executed_by=_identity(current),
        full_evidence=full_evidence,
    )


@router.get("/status")
def ai_status() -> dict:
    return _assistant().status_dict()


@router.post("/explain")
def ai_explain(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded analysis for a pair, grounded in real evidence."""
    del service
    return _run(AITask.EXPLAIN.value, payload or AIRequest(), current)


@router.post("/explain-failure")
def ai_explain_failure(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded failure/blocker(s) for a pair from real evidence."""
    del service
    return _run(AITask.EXPLAIN_FAILURE.value, payload or AIRequest(), current)


@router.post("/explain-routing")
def ai_explain_routing(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded M3/M8 adaptive matcher routing decisions."""
    del service
    return _run(AITask.EXPLAIN_ROUTING.value, payload or AIRequest(), current)


@router.post("/summarize-experiment")
def ai_summarize_experiment(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Summarize the recorded experiment measurements for a pair."""
    del service
    return _run(AITask.SUMMARIZE_EXPERIMENT.value, payload or AIRequest(), current)


@router.post("/chat")
def ai_chat(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Answer a user question about a pair, grounded in recorded evidence."""
    del service
    return _run(AITask.CHAT.value, payload or AIRequest(), current)


# ---------------------------------------------------------------------------
# M11 full-pipeline tasks (M11-EVIDENCE-001 packet over M1..M10)
# ---------------------------------------------------------------------------
@router.post("/explain-pipeline")
def ai_explain_pipeline(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded M1..M10 pipeline analysis for a pair."""
    del service
    return _run("explain-pipeline", payload or AIRequest(), current, full_evidence=True)


@router.post("/summarize-pipeline")
def ai_summarize_pipeline(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Summarize the recorded M1..M10 pipeline evidence for a pair."""
    del service
    return _run("summarize-pipeline", payload or AIRequest(), current, full_evidence=True)


@router.post("/explain-trust")
def ai_explain_trust(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded M7 trust-gate decision for a pair."""
    del service
    return _run("explain-trust", payload or AIRequest(), current, full_evidence=True)


@router.post("/explain-spatial")
def ai_explain_spatial(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded M8 spatial-selection decision for a pair."""
    del service
    return _run("explain-spatial", payload or AIRequest(), current, full_evidence=True)


@router.post("/explain-registration")
def ai_explain_registration(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded M9 registration result for a pair."""
    del service
    return _run("explain-registration", payload or AIRequest(), current, full_evidence=True)


@router.post("/explain-benchmark")
def ai_explain_benchmark(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain the recorded M10 benchmark observations for a pair."""
    del service
    return _run("explain-benchmark", payload or AIRequest(), current, full_evidence=True)


@router.post("/explain-abstention")
def ai_explain_abstention(
    service: AuthServiceDeps,
    current: CurrentUser,
    payload: AIRequest | None = Body(None),
) -> dict:
    """Explain recorded failure(s)/abstention(s) across M1..M10 for a pair."""
    del service
    return _run("explain-abstention", payload or AIRequest(), current, full_evidence=True)