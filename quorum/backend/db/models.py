"""backend/db/models.py — ORM models (the system of record).

Maps the design proposal's schema. JSON columns use SQLAlchemy's portable JSON
type (JSONB on Postgres, TEXT-encoded JSON on SQLite) so the same models run in
dev (SQLite) and prod (Postgres).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, JSON,
                        LargeBinary, String, Text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=_uuid)
    queries_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # sqlite|postgres|bigquery|csv|excel
    display_name: Mapped[str] = mapped_column(String(120))
    connection_meta: Mapped[dict] = mapped_column(JSON, default=dict)  # NON-secret
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="connected")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DataDictionary(Base):
    __tablename__ = "data_dictionaries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    source_kind: Mapped[str] = mapped_column(String(16), default="skeleton")  # uploaded|skeleton
    entries: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SchemaScope(Base):
    __tablename__ = "schema_scopes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id"), index=True)
    tables: Mapped[list] = mapped_column(JSON, default=list)
    columns: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    data_source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"), nullable=True)
    scope_id: Mapped[str | None] = mapped_column(ForeignKey("schema_scopes.id"), nullable=True)
    parent_investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigations.id"), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[str] = mapped_column(Text, default="")
    topology: Mapped[str] = mapped_column(String(24), default="governed_chain")
    status: Mapped[str] = mapped_column(String(16), default="planning", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[str] = mapped_column(String(8), default="low")
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    followups_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Followup(Base):
    __tablename__ = "followups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[dict] = mapped_column(JSON, default=dict)
    suggested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionRoom(Base):
    """One Band room per (session, data_source) pair.

    A room is created the first time a session runs an investigation against a
    given data source. Every subsequent investigation in the same session against
    the same data source reuses the same Band room, avoiding unnecessary room
    growth.  When the user switches to a different data source a new room is
    created automatically.

    ``data_source_id`` is NULL when no explicit data source is attached (the
    investigation runs against the default / env DB), so the uniqueness key is
    (session_id, data_source_id) where NULL is treated as a single shared slot.
    """

    __tablename__ = "session_rooms"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("sessions.id"), nullable=False, index=True)
    data_source_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_sources.id"), nullable=True, index=True)
    band_room_id: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    band_room_id: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(16), default="running")
    shared_context: Mapped[dict] = mapped_column(JSON, default=dict)
    active_agents: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RoomMessage(Base):
    __tablename__ = "room_messages"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    room_id: Mapped[str] = mapped_column(ForeignKey("rooms.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sender_role: Mapped[str] = mapped_column(String(32), default="")
    target_role: Mapped[str] = mapped_column(String(32), default="")
    kind: Mapped[str] = mapped_column(String(32), default="")
    safe_summary: Mapped[str] = mapped_column(Text, default="")
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running")


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    investigator_role: Mapped[str] = mapped_column(String(48), default="")
    factor: Mapped[str] = mapped_column(String(64), default="")
    label: Mapped[str] = mapped_column(String(120), default="")
    a_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    b_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    explained_share: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(24), default="")
    evidence: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BoardDecision(Base):
    __tablename__ = "board_decisions"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    headline: Mapped[str] = mapped_column(Text, default="")
    primary_factor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ranked_factors: Mapped[list] = mapped_column(JSON, default=list)
    ruled_out: Mapped[list] = mapped_column(JSON, default=list)
    residual_share: Mapped[float] = mapped_column(Float, default=0.0)
    confidence: Mapped[str] = mapped_column(String(12), default="medium")
    recommendation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GovernanceEvent(Base):
    __tablename__ = "governance_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuthorizedResult(Base):
    __tablename__ = "authorized_results"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    sql_text: Mapped[str] = mapped_column(Text, default="")
    columns: Mapped[list] = mapped_column(JSON, default=list)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    chart_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CachedPlan(Base):
    __tablename__ = "cached_plans"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    data_source_id: Mapped[str | None] = mapped_column(ForeignKey("data_sources.id"), nullable=True)
    question_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    schema_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    sql_text: Mapped[str] = mapped_column(Text, default="")
    chart_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    event: Mapped[str] = mapped_column(String(48))
    actor_role: Mapped[str] = mapped_column(String(32), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)