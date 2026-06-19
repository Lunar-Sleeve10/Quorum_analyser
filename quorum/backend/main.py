"""backend/main.py — FastAPI control plane (app factory).

Dev: tables are auto-created on SQLite and the bundled northwind sample is
registered if present. Prod: run `alembic upgrade head` (preDeploy on Render)
and point DATABASE_URL at Postgres.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.db.base import Base, engine, SessionLocal
from backend.db import models
from backend.api import (health, quota, system, investigations, data_sources,
                         rooms, schema_scope, dictionary, dashboard)

logger = logging.getLogger(__name__)

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"


def _seed_samples() -> None:
    """Register bundled sample databases (e.g. northwind.db) as data sources."""
    db = SessionLocal()
    try:
        for fname, label in (("northwind.db", "Northwind (sample)"),
                             ("chinook.sqlite", "Chinook (sample)"),
                             ("chinook.db", "Chinook (sample)")):
            path = SAMPLES_DIR / fname
            if not path.exists():
                continue
            exists = db.query(models.DataSource).filter_by(display_name=label).first()
            if exists:
                exists.kind = "sqlite"
                exists.is_sample = True
                exists.status = "connected"
                exists.connection_meta = {
                    "path": str(path.resolve())
                     }
                continue
            db.add(models.DataSource(
                kind="sqlite", display_name=label, is_sample=True, status="connected",
                connection_meta={"path": str(path.resolve())}))
        db.commit()
    finally:
        db.close()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Quorum API", version="2.0.0-phase1")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[s.frontend_origin] if s.frontend_origin != "*" else ["*"],
        allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
    )
    for r in (health.router, quota.router, system.router,
              investigations.router, data_sources.router, rooms.router,
              schema_scope.router, dictionary.router, dashboard.router):
        app.include_router(r)

    @app.on_event("startup")
    def _startup() -> None:
        Base.metadata.create_all(bind=engine)   # dev convenience; Alembic in prod
        # Sample .db files only exist locally — skip seeding when DATABASE_URL
        # points to Postgres (deployed on Render / production).
        if s.database_url.startswith("sqlite"):
            _seed_samples()
        else:
            logger.info("Skipping sample seeding (non-SQLite database: %s)",
                        s.database_url.split(":", 1)[0])
        logger.info("Quorum API ready (db=%s)", s.database_url.split(':', 1)[0])

    @app.get("/")
    def root() -> dict:
        return {"service": "quorum-api", "version": "2.0.0-phase1",
                "docs": "/docs", "health": "/healthz"}

    return app


app = create_app()
