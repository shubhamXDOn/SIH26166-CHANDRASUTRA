"""M9 short-lived AI sessions.

Sessions are in-memory, TTL-capped and strictly pair-isolated: a session_id
bound to pair A can never be used to read state under pair B. Only validated
answers are remembered (as short summaries); prompts, raw provider output and
secret material are never stored here.
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from dataclasses import dataclass, field


class SessionIsolationError(Exception):
    """Raised when a session is reused across different pair_ids."""


@dataclass
class AISession:
    session_id: str
    pair_id: str
    created_at: float
    last_accessed_at: float
    recent_questions: deque[str] = field(default_factory=lambda: deque(maxlen=8))
    recent_answers: deque[dict] = field(default_factory=lambda: deque(maxlen=8))

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "pair_id": self.pair_id,
            "created_at": self.created_at,
            "last_accessed_at": self.last_accessed_at,
            "recent_questions": list(self.recent_questions),
            "recent_answers": list(self.recent_answers),
        }


class SessionStore:
    def __init__(self, *, max_sessions: int = 200, ttl_seconds: int = 3600):
        self._max_sessions = max(1, max_sessions)
        self._ttl_seconds = max(60, ttl_seconds)
        self._sessions: dict[str, AISession] = {}

    # ------------------------------------------------------------------
    def resolve(self, session_id: str | None, pair_id: str) -> AISession:
        """Return an existing session for the pair or create a new one.

        Reusing a session_id across different pairs raises
        :class:`SessionIsolationError` (hard isolation, never silent).
        """
        now = time.time()
        self._prune(now)
        if session_id:
            existing = self._sessions.get(session_id)
            if existing is not None and existing.pair_id != pair_id:
                raise SessionIsolationError(
                    f"Session {session_id} belongs to pair {existing.pair_id} and cannot be reused for {pair_id}."
                )
            if existing is not None:
                existing.last_accessed_at = now
                return existing

        session = AISession(
            session_id=secrets.token_hex(12),
            pair_id=pair_id,
            created_at=now,
            last_accessed_at=now,
        )
        self._sessions[session.session_id] = session
        if len(self._sessions) > self._max_sessions:
            self._evict_oldest()
        return session

    def record(self, session_id: str, question: str, validated_answer: dict) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        if question.strip():
            session.recent_questions.append(question.strip()[:300])
        if validated_answer and validated_answer.get("answer"):
            session.recent_answers.append({
                "answer": validated_answer["answer"][:200],
                "status": "VALIDATED",
                "evidence_refs": len(validated_answer.get("evidence") or []),
            })

    def reset(self, session_id: str) -> bool:
        removed = self._sessions.pop(session_id, None)
        return removed is not None

    # ------------------------------------------------------------------
    def _prune(self, now: float) -> None:
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.last_accessed_at > self._ttl_seconds
        ]
        for sid in expired:
            self._sessions.pop(sid, None)

    def _evict_oldest(self) -> None:
        if not self._sessions:
            return
        oldest = min(
            self._sessions.values(), key=lambda s: s.last_accessed_at
        )
        self._sessions.pop(oldest.session_id, None)


__all__ = ["AISession", "SessionStore", "SessionIsolationError"]