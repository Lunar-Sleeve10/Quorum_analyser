"""
band/session_context.py — Shared context store for a session.

A single SessionContext per session_id holds the schema digest, normalized
question, verified selections, revision count, and the LLM call log. Agents
reference it by context_ref (the session id) instead of inlining schema text
into Band messages. This is the single most important mechanism for keeping
Band messages lightweight.

The store is process-local and thread-safe; an in-memory dict is sufficient
per process. The interface is intentionally minimal so it can be swapped for a
shared store (e.g. Redis) later without changing agent code.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from models.state import DatabaseConfig
from core.database import DatabaseAdapter


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class LLMCallRecord:
    agent: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    timestamp: datetime = field(default_factory=_utcnow)


@dataclass(slots=True)
class ColumnInfo:
    name: str
    type: str


@dataclass(slots=True)
class TableDigest:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)


@dataclass(slots=True)
class SessionContext:
    """Per-session shared state. Written incrementally as the flow progresses."""
    session_id: str

    # Live adapter reference — never serialized into Band messages
    adapter: Optional[DatabaseAdapter] = None
    db_config: Optional[DatabaseConfig] = None

    # Compact schema view (table -> columns with types). Derived from
    # SchemaCache, holds only tables relevant to this question.
    schema_digest: dict[str, TableDigest] = field(default_factory=dict)

    # Orchestrator outputs
    normalized_question: str = ""
    query_pattern: str = ""
    complexity: str = ""
    relevant_tables: list[str] = field(default_factory=list)
    relevant_columns: dict[str, list[str]] = field(default_factory=dict)

    # Revision tracking — single source of truth, mirrored in envelopes
    revision_count: int = 0
    clarification_count: int = 0

    # NEW — independent Supervisor-owned budgets for the two new review gates.
    # These MUST NOT alias revision_count (the existing Reviewer's SQL-correctness
    # budget). Plan review and SQL plan-compliance each get their own counter so
    # the existing reviewer budget is never consumed by the new loops.
    plan_revision_count: int = 0
    sql_revision_count: int = 0

    # Locally-stored Plotly figure objects, keyed (referenced via chart_spec_ref)
    artifacts: dict[str, Any] = field(default_factory=dict)

    # Observability
    llm_call_log: list[LLMCallRecord] = field(default_factory=list)

    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def record_llm_call(
        self,
        *,
        agent: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
    ) -> None:
        self.llm_call_log.append(
            LLMCallRecord(
                agent=agent,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
            )
        )
        self.updated_at = _utcnow()

    def total_llm_calls(self) -> int:
        return len(self.llm_call_log)

    def total_tokens(self) -> int:
        return sum(r.tokens_in + r.tokens_out for r in self.llm_call_log)

    def put_artifact(self, key: str, value: Any) -> str:
        """Store a local artifact (e.g., Plotly figure) and return its ref.

        The value is stored under BOTH the raw key and the session-prefixed ref
        so that callers which pass the original key to ``get_artifact`` (and
        callers which pass the returned ref) both resolve correctly. A prior
        mismatch here silently broke the diagnostic join barrier.
        """
        ref = f"{self.session_id}:{key}"
        self.artifacts[ref] = value
        self.artifacts[key] = value
        self.updated_at = _utcnow()
        return ref

    def get_artifact(self, ref: str) -> Optional[Any]:
        # Resolve by raw key first, then by the session-prefixed ref, so the
        # read side is symmetric with put_artifact regardless of which form the
        # caller holds.
        if ref in self.artifacts:
            return self.artifacts[ref]
        return self.artifacts.get(f"{self.session_id}:{ref}")


class SessionContextStore:
    """Thread-safe registry of SessionContext objects keyed by session_id."""

    def __init__(self) -> None:
        self._store: dict[str, SessionContext] = {}
        self._lock = threading.RLock()

    def create(
        self,
        session_id: str,
        *,
        adapter: Optional[DatabaseAdapter] = None,
        db_config: Optional[DatabaseConfig] = None,
    ) -> SessionContext:
        with self._lock:
            if session_id in self._store:
                raise KeyError(f"SessionContext already exists: {session_id}")
            ctx = SessionContext(
                session_id=session_id,
                adapter=adapter,
                db_config=db_config,
            )
            self._store[session_id] = ctx
            return ctx

    def get(self, session_id: str) -> SessionContext:
        with self._lock:
            ctx = self._store.get(session_id)
            if ctx is None:
                raise KeyError(f"No SessionContext for session: {session_id}")
            return ctx

    def get_or_create(
        self,
        session_id: str,
        *,
        adapter: Optional[DatabaseAdapter] = None,
        db_config: Optional[DatabaseConfig] = None,
    ) -> SessionContext:
        with self._lock:
            ctx = self._store.get(session_id)
            if ctx is None:
                ctx = SessionContext(
                    session_id=session_id,
                    adapter=adapter,
                    db_config=db_config,
                )
                self._store[session_id] = ctx
            return ctx

    def exists(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._store

    def remove(self, session_id: str) -> None:
        with self._lock:
            ctx = self._store.pop(session_id, None)
            if ctx is not None and ctx.adapter is not None:
                try:
                    ctx.adapter.close()
                except Exception:
                    pass

    def clear(self) -> None:
        with self._lock:
            for session_id in list(self._store.keys()):
                self.remove(session_id)


# Module-level singleton
context_store = SessionContextStore()