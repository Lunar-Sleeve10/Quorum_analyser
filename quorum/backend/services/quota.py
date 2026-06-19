"""backend/services/quota.py — per-session investigation + follow-up quotas."""
from __future__ import annotations

from sqlalchemy.orm import Session as DbSession

from backend.config import get_settings
from backend.db import models


def remaining(db: DbSession, session: models.Session) -> dict:
    s = get_settings()
    return {
        "queries_remaining": max(0, s.max_investigations_per_session - session.queries_used),
        "queries_limit": s.max_investigations_per_session,
        "followups_per_investigation": s.max_followups_per_investigation,
    }


def can_start_investigation(session: models.Session) -> bool:
    return session.queries_used < get_settings().max_investigations_per_session


def consume_investigation(db: DbSession, session: models.Session) -> None:
    session.queries_used += 1
    db.add(session)
    db.commit()


def can_followup(inv: models.Investigation) -> bool:
    return inv.followups_used < get_settings().max_followups_per_investigation


def consume_followup(db: DbSession, inv: models.Investigation) -> None:
    inv.followups_used += 1
    db.add(inv)
    db.commit()
