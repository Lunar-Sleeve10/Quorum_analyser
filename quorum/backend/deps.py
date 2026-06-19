"""backend/deps.py — request dependencies: DB session + anonymous session."""
from __future__ import annotations

from fastapi import Depends, Header
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models


def get_or_create_session(
    db: DbSession = Depends(get_db),
    x_session_token: str | None = Header(default=None),
) -> models.Session:
    """Anonymous session via the X-Session-Token header. Creates one on first use;
    the response echoes the token so the client can persist it."""
    if x_session_token:
        existing = db.query(models.Session).filter_by(token=x_session_token).first()
        if existing:
            return existing
    s = models.Session()
    db.add(s)
    db.commit()
    db.refresh(s)
    return s
