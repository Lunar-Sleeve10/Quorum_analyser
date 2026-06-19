"""backend/api/health.py — liveness/readiness for Render health checks."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.services.orchestration import band_available

router = APIRouter(tags=["system"])


@router.get("/healthz")
def healthz(db: DbSession = Depends(get_db)) -> dict:
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": db_ok, "band_configured": band_available()}
