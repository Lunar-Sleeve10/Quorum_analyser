"""backend/api/schema_scope.py — discover schema + create bounded scope."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models
from backend.services import scope as scope_svc

router = APIRouter(tags=["scope"])


class ScopeBody(BaseModel):
    data_source_id: str
    tables: list[str]
    columns: dict[str, list[str]]


@router.get("/data-sources/{data_source_id}/schema")
@router.get("/data-sources/{data_source_id}/schema")
def discover_schema(data_source_id: str, db: DbSession = Depends(get_db)) -> dict:
    ds = db.get(models.DataSource, data_source_id)
    if ds is None:
        raise HTTPException(404, "Data source not found.")

    try:
        return scope_svc.discover(ds)

    except Exception as exc:
        import traceback
        print("\n" + "=" * 80)
        print("SCHEMA DISCOVERY FAILED")
        traceback.print_exc()
        print("=" * 80 + "\n")
        raise HTTPException(400, f"Could not read schema: {exc}")


@router.get("/data-sources/{data_source_id}/schema/suggest")
def suggest_scope(data_source_id: str, db: DbSession = Depends(get_db)) -> dict:
    ds = db.get(models.DataSource, data_source_id)
    if ds is None:
        raise HTTPException(404, "Data source not found.")
    return scope_svc.suggest(scope_svc.discover(ds))


@router.post("/schema-scopes")
def create_scope(body: ScopeBody, db: DbSession = Depends(get_db)) -> dict:
    if db.get(models.DataSource, body.data_source_id) is None:
        raise HTTPException(404, "Data source not found.")
    try:
        sc = scope_svc.create_scope(db, body.data_source_id, body.tables, body.columns)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"id": sc.id, "data_source_id": sc.data_source_id,
            "tables": sc.tables, "columns": sc.columns}


@router.get("/schema-scopes/{scope_id}")
def get_scope(scope_id: str, db: DbSession = Depends(get_db)) -> dict:
    sc = db.get(models.SchemaScope, scope_id)
    if sc is None:
        raise HTTPException(404, "Scope not found.")
    return {"id": sc.id, "data_source_id": sc.data_source_id,
            "tables": sc.tables, "columns": sc.columns}
