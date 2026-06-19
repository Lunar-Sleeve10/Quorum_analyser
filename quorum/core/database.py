"""
core/database.py — Database adapters (engine-agnostic interface).

One interface, three backends: SQLite, Postgres, BigQuery. Every adapter is
deterministic, read-only by default, and has no LLM or Band knowledge. The rest
of the system (planner grounding, SQL execution, cost governance, diagnostics)
talks only to this interface, so switching engines is a config change.

Postgres uses psycopg (optional dep); BigQuery uses google-cloud-bigquery
(optional dep). Both import lazily so a SQLite-only install stays dependency
light.
"""

from __future__ import annotations

import logging
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from threading import Lock
from typing import Any

from models.state import DatabaseConfig

logger = logging.getLogger(__name__)

# Reject identifiers containing NUL bytes (the one thing that can't be made
# safe by quoting) or that are empty. Everything else — spaces, dashes,
# unicode, reserved words — is fine once properly quoted.
def _safe_ident(name: str) -> str:
    if not name or "\x00" in name:
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def _quote_ident(name: str) -> str:
    """Double-quote a SQL identifier per SQL-92, escaping embedded quotes.

    Used instead of a bareword whitelist so legitimate names with spaces
    or punctuation (e.g. 'Order Details', 'Customer Demographics') work,
    while still preventing the string from breaking out of the quoted
    identifier context.
    """
    _safe_ident(name)
    return '"' + name.replace('"', '""') + '"'


class DatabaseAdapter(ABC):
    """Uniform read interface every engine implements."""

    engine: str = "generic"

    @abstractmethod
    def get_tables(self) -> list[str]: ...

    @abstractmethod
    def get_columns(self, table_name: str) -> list[str]: ...

    @abstractmethod
    def execute_query(self, query: str, limit: int) -> tuple[list[Any], list[str]]: ...

    @abstractmethod
    def get_schema_info(self, tables: list[str]) -> str:
        """Return 'table(col TYPE, col TYPE)' lines for the given tables."""

    def get_full_schema(self) -> str:
        return self.get_schema_info(self.get_tables())

    def close(self) -> None:  # pragma: no cover - default no-op
        pass


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

class SQLiteAdapter(DatabaseAdapter):
    engine = "sqlite"

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self.conn: sqlite3.Connection | None = None
        self._lock = Lock()
        mode = "ro" if config.read_only else "rwc"
        db_path = Path(config.connection_string)
        logger.info(
            "Opening SQLite db=%s exists=%s parent_exists=%s mode=%s cwd=%s",
            db_path, db_path.exists(), db_path.parent.exists(), mode, Path.cwd(),
        )
        # In read-only ("ro") mode SQLite never creates the file, so a missing
        # file fails with the opaque "unable to open database file". Surface a
        # diagnosable error instead. (On ephemeral hosts like Render, an
        # uploaded .db does not survive restarts/redeploys.)
        if config.read_only and not db_path.exists():
            raise FileNotFoundError(
                f"SQLite database not found: {db_path} (cwd={Path.cwd()}). "
                f"The file must exist before opening in read-only mode; on "
                f"ephemeral hosts ensure it is present at this path or use a "
                f"persistent store / managed DB."
            )
        # rwc can create the DB file but NOT missing parent directories.
        if not config.read_only:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            f"file:{config.connection_string}?mode={mode}",
            uri=True, timeout=config.timeout, check_same_thread=False,
        )
        logger.info("Connected to SQLite: %s", config.connection_string)

    def get_tables(self) -> list[str]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            return [r[0] for r in cur.fetchall()]

    def get_columns(self, table_name: str) -> list[str]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(f"PRAGMA table_info({_quote_ident(table_name)});")
            return [r[1] for r in cur.fetchall()]

    def execute_query(self, query: str, limit: int) -> tuple[list[Any], list[str]]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(query)
            rows = cur.fetchmany(limit)
            cols = [d[0] for d in cur.description] if cur.description else []
            return rows, cols

    def get_schema_info(self, tables: list[str]) -> str:
        parts: list[str] = []
        with self._lock:
            cur = self.conn.cursor()
            for t in tables:
                cur.execute(f"PRAGMA table_info({_quote_ident(t)});")
                cols = [f"{c[1]} {c[2]}" for c in cur.fetchall()]
                parts.append(f"{t}({', '.join(cols)})")
        return "\n".join(parts)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None


# ---------------------------------------------------------------------------
# Postgres (optional: psycopg)
# ---------------------------------------------------------------------------

class PostgresAdapter(DatabaseAdapter):
    engine = "postgres"

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._lock = Lock()
        try:
            import psycopg  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Postgres support needs 'psycopg' (pip install psycopg[binary])."
            ) from exc
        self._psycopg = psycopg
        self.conn = psycopg.connect(config.connection_string, autocommit=True)
        if config.read_only:
            try:
                self.conn.execute("SET default_transaction_read_only = on;")
            except Exception:
                pass
        logger.info("Connected to Postgres")

    def get_tables(self) -> list[str]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' ORDER BY table_name;"
            )
            return [r[0] for r in cur.fetchall()]

    def get_columns(self, table_name: str) -> list[str]:
        with self._lock:
            cur = self.conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name=%s ORDER BY ordinal_position;",
                (table_name,),
            )
            return [r[0] for r in cur.fetchall()]

    def execute_query(self, query: str, limit: int) -> tuple[list[Any], list[str]]:
        with self._lock:
            cur = self.conn.execute(query)
            rows = cur.fetchmany(limit)
            cols = [d.name for d in cur.description] if cur.description else []
            return rows, cols

    def get_schema_info(self, tables: list[str]) -> str:
        parts: list[str] = []
        with self._lock:
            for t in tables:
                cur = self.conn.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name=%s ORDER BY ordinal_position;",
                    (t,),
                )
                cols = [f"{r[0]} {r[1]}" for r in cur.fetchall()]
                parts.append(f"{t}({', '.join(cols)})")
        return "\n".join(parts)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# BigQuery (optional: google-cloud-bigquery)
# ---------------------------------------------------------------------------

class BigQueryAdapter(DatabaseAdapter):
    engine = "bigquery"

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._lock = Lock()
        try:
            from google.cloud import bigquery  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "BigQuery support needs 'google-cloud-bigquery'."
            ) from exc
        # connection_string carries "project.dataset"
        project, _, dataset = config.connection_string.partition(".")
        self.project = project
        self.dataset = dataset
        self.client = bigquery.Client(project=project or None)
        logger.info("Connected to BigQuery: %s.%s", project, dataset)

    def _fq(self, table: str) -> str:
        return f"`{self.project}.{self.dataset}.{table}`"

    def get_tables(self) -> list[str]:
        with self._lock:
            return [t.table_id for t in self.client.list_tables(f"{self.project}.{self.dataset}")]

    def get_columns(self, table_name: str) -> list[str]:
        with self._lock:
            tbl = self.client.get_table(f"{self.project}.{self.dataset}.{table_name}")
            return [f.name for f in tbl.schema]

    def execute_query(self, query: str, limit: int) -> tuple[list[Any], list[str]]:
        with self._lock:
            job = self.client.query(query)
            it = job.result(max_results=limit)
            cols = [f.name for f in it.schema]
            rows = [tuple(r.values()) for r in it]
            return rows, cols

    def get_schema_info(self, tables: list[str]) -> str:
        parts: list[str] = []
        with self._lock:
            for t in tables:
                tbl = self.client.get_table(f"{self.project}.{self.dataset}.{t}")
                cols = [f"{f.name} {f.field_type}" for f in tbl.schema]
                parts.append(f"{t}({', '.join(cols)})")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# MySQL (optional: pymysql)
# ---------------------------------------------------------------------------

class MySQLAdapter(DatabaseAdapter):
    engine = "mysql"

    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config
        self._lock = Lock()
        try:
            import pymysql  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("MySQL support needs 'pymysql' (pip install pymysql).") from exc
        from urllib.parse import urlparse
        u = urlparse(config.connection_string)
        self.database = (u.path or "").lstrip("/")
        self.conn = pymysql.connect(
            host=u.hostname or "localhost", port=u.port or 3306,
            user=u.username or "root", password=u.password or "",
            database=self.database, connect_timeout=config.timeout,
            cursorclass=pymysql.cursors.Cursor, autocommit=True,
        )
        logger.info("Connected to MySQL: %s", self.database)

    def get_tables(self) -> list[str]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema=%s ORDER BY table_name;", (self.database,))
            return [r[0] for r in cur.fetchall()]

    def get_columns(self, table_name: str) -> list[str]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position;",
                        (self.database, table_name))
            return [r[0] for r in cur.fetchall()]

    def execute_query(self, query: str, limit: int) -> tuple[list[Any], list[str]]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(query)
            rows = cur.fetchmany(limit)
            cols = [d[0] for d in cur.description] if cur.description else []
            return list(rows), cols

    def get_schema_info(self, tables: list[str]) -> str:
        parts: list[str] = []
        with self._lock:
            cur = self.conn.cursor()
            for t in tables:
                cur.execute("SELECT column_name, data_type FROM information_schema.columns "
                            "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position;",
                            (self.database, t))
                cols = [f"{r[0]} {r[1]}" for r in cur.fetchall()]
                parts.append(f"{t}({', '.join(cols)})")
        return "\n".join(parts)

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_adapter(config: DatabaseConfig) -> DatabaseAdapter:
    from config import DatabaseType

    if config.db_type == DatabaseType.SQLITE:
        return SQLiteAdapter(config)
    if config.db_type == DatabaseType.POSTGRES:
        return PostgresAdapter(config)
    if config.db_type == DatabaseType.MYSQL:
        return MySQLAdapter(config)
    if config.db_type == DatabaseType.BIGQUERY:
        return BigQueryAdapter(config)
    raise ValueError(f"Unsupported db_type: {config.db_type}")