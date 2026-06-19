"""backend/db/base.py — SQLAlchemy engine, session, and declarative base."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from backend.config import get_settings

_settings = get_settings()

# check_same_thread only matters for SQLite; harmless to pass conditionally.
_connect_args = {"check_same_thread": False} if _settings.normalized_database_url().startswith("sqlite") else {}
engine = create_engine(_settings.normalized_database_url(), connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
