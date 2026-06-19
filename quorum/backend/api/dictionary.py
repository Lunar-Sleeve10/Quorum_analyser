"""backend/api/dictionary.py — data dictionary upload / skeleton generation."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models
from backend.services import dictionary as dict_svc
from backend.services import scope as scope_svc

router = APIRouter(prefix="/data-sources/{data_source_id}/dictionary", tags=["dictionary"])


def _ds(db, data_source_id):
    ds = db.get(models.DataSource, data_source_id)
    if ds is None:
        raise HTTPException(404, "Data source not found.")
    return ds


@router.get("")
def get_dictionary(data_source_id: str, db: DbSession = Depends(get_db)) -> dict:
    _ds(db, data_source_id)
    d = (db.query(models.DataDictionary).filter_by(data_source_id=data_source_id)
         .order_by(models.DataDictionary.created_at.desc()).first())
    return {"source_kind": d.source_kind, "entries": d.entries} if d else {"source_kind": None, "entries": []}


@router.post("/skeleton")
def generate_skeleton(data_source_id: str, db: DbSession = Depends(get_db)) -> dict:
    ds = _ds(db, data_source_id)
    entries = dict_svc.skeleton(scope_svc.discover(ds))
    row = models.DataDictionary(data_source_id=data_source_id, source_kind="skeleton", entries=entries)
    db.add(row); db.commit()
    return {"source_kind": "skeleton", "count": len(entries), "entries": entries}


@router.post("")
async def upload_dictionary(data_source_id: str, file: UploadFile = File(...),
                            db: DbSession = Depends(get_db)) -> dict:
    _ds(db, data_source_id)
    content = await file.read()
    try:
        entries = dict_svc.parse_upload(file.filename, content)
    except Exception as exc:
        raise HTTPException(400, f"Could not parse dictionary: {exc}")
    row = models.DataDictionary(data_source_id=data_source_id, source_kind="uploaded", entries=entries)
    db.add(row); db.commit()
    return {"source_kind": "uploaded", "count": len(entries)}
