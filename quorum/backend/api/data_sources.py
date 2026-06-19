"""backend/api/data_sources.py — list connected sources + built-in samples."""
from __future__ import annotations
from fastapi import HTTPException
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models
from backend.deps import get_or_create_session

router = APIRouter(prefix="/data-sources", tags=["data"])


@router.get("")
def list_sources( session: models.Session = Depends(get_or_create_session),db: DbSession = Depends(get_db),) -> list[dict]:
    out = []
    sources = (
        db.query(models.DataSource)
        .filter(
            (models.DataSource.is_sample == True)
            |
            (models.DataSource.session_id == session.id)
        )
        .order_by(models.DataSource.created_at.desc())
        .all()
    )
    for ds in sources:
        out.append({"id": ds.id, "kind": ds.kind, "display_name": ds.display_name,
                    "is_sample": ds.is_sample, "status": ds.status,
                    "has_credentials": ds.encrypted_credentials is not None})
    return out


# --- Phase 4: connect external (encrypted) + file upload -------------------
import tempfile
from pathlib import Path

from fastapi import File, HTTPException, UploadFile

from backend.services.crypto import encrypt_credentials


from pydantic import BaseModel, Field, field_validator

class PostgresMeta(BaseModel):
    host: str
    port: int = 5432
    dbname: str

    @field_validator("host", "dbname")
    @classmethod
    def clean(cls, v: str) -> str:
        return v.strip()


class PostgresCreds(BaseModel):
    user: str
    password: str

class ConnectExternal(BaseModel):
    kind: str
    display_name: str
    connection_meta: dict = {}
    credentials: dict = {}


@router.post("/connect")
@router.post("/connect")
def connect_external(
    body: ConnectExternal,
    session: models.Session = Depends(get_or_create_session),
    db: DbSession = Depends(get_db),
) -> dict:
    print("META:", body.connection_meta)
    print("CREDS:", body.credentials)
    if body.kind not in ("postgres", "mysql", "bigquery"):
        raise HTTPException(400, "kind must be postgres, mysql, or bigquery")
    enc = encrypt_credentials(body.credentials) if body.credentials else None
    print("ENCRYPTED:", enc)
    ds = models.DataSource(
    session_id=session.id,
    kind=body.kind,
    display_name=body.display_name,
    connection_meta=body.connection_meta,
    encrypted_credentials=enc,
    status="connected"
)
    db.add(ds); db.commit(); db.refresh(ds)
    return {"id": ds.id, "kind": ds.kind, "display_name": ds.display_name,
            "credentials_encrypted": enc is not None}


_UPLOAD_DIR = Path(tempfile.gettempdir()) / "quorum_uploads"


@router.post("/upload")
async def upload_data_source(
    file: UploadFile = File(...),
    session: models.Session = Depends(get_or_create_session),
    db: DbSession = Depends(get_db),
) -> dict:
    """Upload a SQLite (.db/.sqlite) directly, or a CSV/Excel which is loaded
    into a temp SQLite so it is queryable by the agents."""
    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    name = (file.filename or "upload").lower()
    if name.endswith((".db", ".sqlite", ".sqlite3")):
        path = _UPLOAD_DIR / Path(name).name
        path.write_bytes(content)
    elif name.endswith((".csv", ".xlsx", ".xls")):
        import io, sqlite3, pandas as pd
        df = (pd.read_csv(io.BytesIO(content)) if name.endswith(".csv")
              else pd.read_excel(io.BytesIO(content)))
        path = _UPLOAD_DIR / (Path(name).stem + ".db")
        con = sqlite3.connect(path)
        df.to_sql("data", con, if_exists="replace", index=False)
        con.close()
    else:
        raise HTTPException(400, "Unsupported file type (use .db/.sqlite/.csv/.xlsx).")
    ds = models.DataSource(
    session_id=session.id,
    kind="sqlite",
    display_name=Path(file.filename).stem,
    connection_meta={"path": str(path.resolve())},
    status="connected")
    db.add(ds); db.commit(); db.refresh(ds)
    return {"id": ds.id, "display_name": ds.display_name, "kind": "sqlite"}


@router.delete("/{data_source_id}")
def delete_source(
    data_source_id: str,
    db: DbSession = Depends(get_db)
):
    ds = db.get(models.DataSource, data_source_id)

    if ds is None:
        raise HTTPException(404, "Data source not found.")

    if ds.is_sample:
        raise HTTPException(400, "Sample databases cannot be deleted.")

    db.delete(ds)
    db.commit()

    return {"ok": True}