"""
core/cache.py — Schema cache.

Class-level cache keyed by db_path so the
full schema is introspected once per database across all sessions.
"""

from __future__ import annotations

import logging
from threading import Lock

from core.database import DatabaseAdapter

logger = logging.getLogger(__name__)


class SchemaCache:
    _cache: dict[str, str] = {}
    _lock = Lock()

    @classmethod
    def get_schema(cls, db_path: str, adapter: DatabaseAdapter) -> str:
        with cls._lock:
            if db_path not in cls._cache:
                logger.info("Building schema cache for: %s", db_path)
                cls._cache[db_path] = adapter.get_full_schema()
                logger.info("Schema cached: %d chars", len(cls._cache[db_path]))
            return cls._cache[db_path]

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._cache.clear()
