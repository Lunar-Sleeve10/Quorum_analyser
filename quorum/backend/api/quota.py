"""backend/api/quota.py — remaining investigations / follow-ups for the session."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models
from backend.deps import get_or_create_session
from backend.services import quota

router = APIRouter(prefix="/quota", tags=["quota"])


@router.get("")
def get_quota(
    session: models.Session = Depends(get_or_create_session),
    db: DbSession = Depends(get_db),
) -> dict:
    out = quota.remaining(db, session)
    out["session_token"] = session.token
    return out
