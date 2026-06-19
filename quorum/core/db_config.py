"""
core/db_config.py — Database selection + EPHEMERAL credential handling.

Isolates *which* database and *how to connect* from the UI and the business
logic. The front-end calls this module; it never sees engine specifics.

SECURITY POSTURE (Regulated & High-Stakes):
    * Credentials are NEVER written to disk. They live only in this process's
      memory for the duration of the session (the Streamlit console process).
    * SQLite uploads are stored in a volatile temp directory; the file *path*
      (not a secret) is the only thing handed to the agent processes.
    * For remote engines (Postgres/MySQL/BigQuery), the password-bearing
      connection string is never persisted. Cross-process Band agents obtain
      remote credentials from environment variables (.env) instead — explicit,
      ephemeral injection rather than plaintext on disk.

SQLite needs no credentials — just a database file path.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from config import DatabaseType, settings
from models.state import DatabaseConfig

logger = logging.getLogger(__name__)

# User-facing labels -> engine keys
DB_TYPES: dict[str, str] = {
    "SQLite": "sqlite",
    "PostgreSQL": "postgres",
    "MySQL": "mysql",
    "BigQuery": "bigquery",
}

REQUIRED_FIELDS: dict[str, list[str]] = {
    "postgres": ["host", "user", "password", "dbname"],
    "mysql": ["host", "user", "password", "dbname"],
    "bigquery": ["project", "dataset"],
}

DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306}

# Volatile upload location — system temp, cleared by the OS; never the repo.
UPLOAD_DIR = Path(tempfile.gettempdir()) / "quorum_uploads"
_MISSING_MSG = "Credentials not uploaded. Enter the connection details for this session (kept in memory, never written to disk)."

# In-memory, per-session credential store. Cleared when the process exits.
_SESSION_CREDS: dict[str, dict] = {}


@dataclass
class ConnectionResult:
    config: Optional[DatabaseConfig]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.config is not None and self.error is None


# ---------------------------------------------------------------------------
# Credentials — IN MEMORY ONLY (never persisted)
# ---------------------------------------------------------------------------

def load_credentials(engine: str) -> Optional[dict]:
    data = _SESSION_CREDS.get(engine)
    return dict(data) if data else None


def save_credentials(engine: str, data: dict) -> None:
    """Keep credentials in session memory only — deliberately NOT written to
    disk. This is the core ephemeral-credential guarantee."""
    _SESSION_CREDS[engine] = dict(data)
    logger.info("Stored %s credentials in session memory (not persisted).", engine)


def clear_credentials(engine: Optional[str] = None) -> None:
    if engine is None:
        _SESSION_CREDS.clear()
    else:
        _SESSION_CREDS.pop(engine, None)


def credentials_present(engine: str) -> bool:
    creds = load_credentials(engine)
    if not creds:
        return False
    return all(creds.get(f) not in (None, "") for f in REQUIRED_FIELDS.get(engine, []))


# ---------------------------------------------------------------------------
# SQLite upload — volatile temp dir (the path is not a secret)
# ---------------------------------------------------------------------------

def save_sqlite_upload(filename: str, content: bytes) -> str:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe = os.path.basename(filename) or "uploaded.db"
    dest = UPLOAD_DIR / safe
    dest.write_bytes(content)
    logger.info("Saved uploaded SQLite database to volatile dir %s", dest)
    return str(dest.resolve())


# ---------------------------------------------------------------------------
# Build a DatabaseConfig (the single abstraction the engine consumes)
# ---------------------------------------------------------------------------

def build_connection(engine: str, *, sqlite_path: Optional[str] = None) -> ConnectionResult:
    engine = engine.lower()
    try:
        db_type = DatabaseType(engine)
    except ValueError:
        return ConnectionResult(None, f"Unsupported database type: {engine}")

    if engine == "sqlite":
        path = sqlite_path or settings.db_path
        if not path or not Path(path).exists():
            return ConnectionResult(None, "Please upload a SQLite database file (.db / .sqlite).")
        return ConnectionResult(_cfg(db_type, str(Path(path).resolve())))

    creds = load_credentials(engine)
    if not credentials_present(engine):
        return ConnectionResult(None, _MISSING_MSG)

    if engine in ("postgres", "mysql"):
        host = creds["host"]
        port = creds.get("port") or DEFAULT_PORTS[engine]
        user = quote(str(creds["user"]), safe="")
        pwd = quote(str(creds["password"]), safe="")
        dbname = creds["dbname"]
        scheme = "postgresql" if engine == "postgres" else "mysql"
        conn = f"{scheme}://{user}:{pwd}@{host}:{port}/{dbname}"
        return ConnectionResult(_cfg(db_type, conn))

    if engine == "bigquery":
        # A service-account path may be provided for THIS session via env; we do
        # not copy/persist the key file ourselves.
        cred_path = creds.get("credentials_path")
        if cred_path and Path(cred_path).exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path
        conn = f"{creds['project']}.{creds['dataset']}"
        return ConnectionResult(_cfg(db_type, conn))

    return ConnectionResult(None, f"Unsupported database type: {engine}")


def _cfg(db_type: DatabaseType, connection_string: str) -> DatabaseConfig:
    return DatabaseConfig(
        db_type=db_type, connection_string=connection_string,
        max_rows=settings.db_max_rows, timeout=settings.db_timeout,
        read_only=settings.db_read_only,
    )


def validate(config: DatabaseConfig) -> ConnectionResult:
    """Open the database once to confirm the connection works."""
    from core.database import make_adapter
    try:
        adapter = make_adapter(config)
        adapter.get_tables()
        adapter.close()
        return ConnectionResult(config)
    except Exception as exc:
        logger.warning("DB validation failed: %s", exc)
        return ConnectionResult(None, f"Could not connect: {exc}")


# ---------------------------------------------------------------------------
# Active database hand-off — lets the running Band agents use the DB the user
# selected in the console (same machine). For SQLite we persist only the file
# PATH (not a secret). For remote engines we deliberately DO NOT write the
# password-bearing connection string to disk; those agents read credentials
# from the environment (.env) instead. Falls back to .env when absent.
# ---------------------------------------------------------------------------

ACTIVE_DB_FILE = Path(tempfile.gettempdir()) / "quorum_active_db.json"


def write_active_db(config: DatabaseConfig) -> None:
    if config.db_type == DatabaseType.SQLITE:
        ACTIVE_DB_FILE.write_text(json.dumps({
            "db_type": config.db_type.value,
            "connection_string": config.connection_string,  # a file path, not a secret
        }), encoding="utf-8")
        logger.info("Active database (SQLite path) handed off via %s", ACTIVE_DB_FILE)
        return
    # Remote engine: never persist the secret. Remove any stale hand-off and
    # require the agents to source credentials from the environment.
    try:
        ACTIVE_DB_FILE.unlink(missing_ok=True)  # type: ignore[call-arg]
    except Exception:
        pass
    logger.info("Remote engine selected (%s): credentials kept in session; agents must "
                "use environment-injected credentials (not written to disk).",
                config.db_type.value)


def load_active_db() -> Optional[DatabaseConfig]:
    if not ACTIVE_DB_FILE.exists():
        return None
    try:
        d = json.loads(ACTIVE_DB_FILE.read_text(encoding="utf-8"))
        return _cfg(DatabaseType(d["db_type"]), d["connection_string"])
    except Exception as exc:
        logger.warning("Could not read active-db hand-off: %s", exc)
        return None
