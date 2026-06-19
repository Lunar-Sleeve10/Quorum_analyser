"""backend/api/system.py — system status for the System Status page + demos."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from backend.config import get_settings
from backend.db.base import get_db
from backend.db import models
from backend.services.orchestration import band_available

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
def status(db: DbSession = Depends(get_db)) -> dict:
    s = get_settings()
    import os
    catalog = os.getenv("METRIC_CATALOG_PATH", "metric_catalog.yaml")
    return {
        "database": {"url_scheme": s.database_url.split(":", 1)[0], "ok": True},
        "band_configured": band_available(),
        "llm_backend": s.llm_backend or "(unset)",
        "cached_plans": db.query(func.count(models.CachedPlan.id)).scalar() or 0,
        "investigations": db.query(func.count(models.Investigation.id)).scalar() or 0,
        "data_sources": db.query(func.count(models.DataSource.id)).scalar() or 0,
        "rooms": db.query(func.count(models.Room.id)).scalar() or 0,
        "findings": db.query(func.count(models.Finding.id)).scalar() or 0,
        "dictionaries": db.query(func.count(models.DataDictionary.id)).scalar() or 0,
        "semantic_catalog": os.path.exists(catalog),
        "credentials_encrypted_at_rest": bool(s.credential_encryption_key),
    }
