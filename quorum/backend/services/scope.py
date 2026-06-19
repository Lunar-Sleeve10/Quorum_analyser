"""backend/services/scope.py — schema discovery + bounded investigation scope.

For user databases we never expose the whole schema. We discover tables/columns,
let the user pick at most N tables / M columns (limits from settings), and only
that slice flows to semantic retrieval, SQL generation, investigators, and the
Band room context.
"""
from __future__ import annotations

from backend.config import get_settings
from backend.db import models
from backend.services.crypto import decrypt_credentials


def _adapter_for(ds: models.DataSource):
    from core.database import make_adapter
    from models.state import DatabaseConfig
    from config import DatabaseType, settings
    from backend.services.crypto import decrypt_credentials

    meta = ds.connection_meta or {}

    # Existing formats (sqlite path / explicit connection string)
    conn = (
        meta.get("connection_string")
        or meta.get("path")
        or meta.get("uri")
        or ""
    )

    # Reconstruct Postgres connection string from stored metadata + encrypted creds
    if not conn and (ds.kind or "").lower() == "postgres":
        creds = decrypt_credentials(ds.encrypted_credentials) or {}

        user = (
            creds.get("username")
            or creds.get("user")
            or ""
        )

        password = creds.get("password", "")
        host = meta.get("host", "localhost")
        port = meta.get("port", 5432)
        dbname = meta.get("dbname", "")

        if user and dbname:
            conn = (
                f"postgresql://{user}:{password}"
                f"@{host}:{port}/{dbname}"
            )

    try:
        dbt = DatabaseType(ds.kind)
    except Exception:
        dbt = DatabaseType.SQLITE

    cfg = DatabaseConfig(
        db_type=dbt,
        connection_string=conn,
        max_rows=settings.db_max_rows,
        timeout=settings.db_timeout,
        read_only=True,
    )

    return make_adapter(cfg)


def discover(ds: models.DataSource) -> dict:
    """Return {tables: [{name, columns: [..]}]} for a data source."""
    adapter = _adapter_for(ds)
    try:
        out = []
        for t in adapter.get_tables():
            try:
                cols = adapter.get_columns(t)
            except Exception:
                cols = []
            out.append({"name": t, "columns": list(cols)})
        return {"tables": out}
    finally:
        try:
            adapter.close()
        except Exception:
            pass


def suggest(discovered: dict) -> dict:
    """Heuristic AI-assist: propose the first N tables / M columns within limits.
    The user keeps final control; this is only a starting point."""
    s = get_settings()
    tables = [t["name"] for t in discovered.get("tables", [])][: s.max_scope_tables]
    columns = {}
    for t in discovered.get("tables", []):
        if t["name"] in tables:
            columns[t["name"]] = list(t["columns"])[: s.max_scope_columns]
    return {"tables": tables, "columns": columns}


def validate_scope(tables: list, columns: dict) -> str | None:
    """Return an error message if the scope violates the limits, else None."""
    s = get_settings()
    if len(tables) > s.max_scope_tables:
        return f"At most {s.max_scope_tables} tables may be selected."
    for t in tables:
        cols = columns.get(t, [])
        if len(cols) > s.max_scope_columns:
            return f"At most {s.max_scope_columns} columns per table ({t})."
    return None


def create_scope(db, data_source_id: str, tables: list, columns: dict) -> models.SchemaScope:
    err = validate_scope(tables, columns)
    if err:
        raise ValueError(err)
    scope = models.SchemaScope(data_source_id=data_source_id, tables=tables, columns=columns)
    db.add(scope)
    db.commit()
    db.refresh(scope)
    return scope
