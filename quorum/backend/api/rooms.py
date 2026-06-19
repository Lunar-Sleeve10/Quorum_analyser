"""backend/api/rooms.py — Band Room state, message history, and SSE live feed."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db, SessionLocal
from backend.db import models

router = APIRouter(prefix="/rooms", tags=["rooms"])

_TERMINAL = {"completed", "error", "escalated"}


def _room_for(db: DbSession, investigation_id: str) -> models.Room | None:
    return (db.query(models.Room).filter_by(investigation_id=investigation_id)
            .order_by(models.Room.created_at.desc()).first())


def _session_room_for(db: DbSession, inv: models.Investigation) -> models.SessionRoom | None:
    """Return the session-scoped Band room registration for this investigation,
    if one exists.  The session room is the authoritative source of the Band
    room id; the per-investigation Room row copies it for audit purposes."""
    return (db.query(models.SessionRoom)
            .filter_by(session_id=inv.session_id, data_source_id=inv.data_source_id)
            .first())


def _msg(m: models.RoomMessage) -> dict:
    return {"id": m.id, "ts": m.ts.isoformat() if m.ts else None,
            "sender": m.sender_role, "target": m.target_role, "kind": m.kind,
            "summary": m.safe_summary, "status": m.status}


@router.get("/{investigation_id}")
def get_room(investigation_id: str, db: DbSession = Depends(get_db)) -> dict:
    inv = db.get(models.Investigation, investigation_id)
    if inv is None:
        raise HTTPException(404, "Investigation not found.")

    room = _room_for(db, investigation_id)
    session_room = _session_room_for(db, inv)

    msgs = ([] if room is None else
            db.query(models.RoomMessage).filter_by(room_id=room.id)
            .order_by(models.RoomMessage.ts.asc()).all())

    return {
        "investigation_id": investigation_id,
        "topology": inv.topology, "status": inv.status,
        "confidence": inv.confidence,
        # band_room_id: shared across all investigations in the same session +
        # data-source.  Present even before the first investigation completes if
        # a prior investigation already opened the room for this session.
        "band_room_id": (session_room.band_room_id if session_room
                         else (room.band_room_id if room else None)),
        "band_room_shared": session_room is not None,
        "active_agents": room.active_agents if room else [],
        "shared_context": room.shared_context if room else {},
        "messages": [_msg(m) for m in msgs],
    }


@router.get("/{investigation_id}/stream")
def stream_room(investigation_id: str) -> StreamingResponse:
    """Server-sent events: emits new room messages as they are persisted, then a
    terminal 'status' event when the investigation finishes. Single-process,
    DB-poll based — no Redis required."""
    def gen():
        sent: set[str] = set()
        for _ in range(600):  # ~10 min hard cap
            db = SessionLocal()
            try:
                inv = db.get(models.Investigation, investigation_id)
                if inv is None:
                    yield f"event: error\ndata: {json.dumps({'error':'not found'})}\n\n"
                    return
                room = _room_for(db, investigation_id)
                if room is not None:
                    new = (db.query(models.RoomMessage).filter_by(room_id=room.id)
                           .order_by(models.RoomMessage.ts.asc()).all())
                    for m in new:
                        if m.id in sent:
                            continue
                        sent.add(m.id)
                        yield f"event: message\ndata: {json.dumps(_msg(m))}\n\n"
                if inv.status in _TERMINAL:
                    yield (f"event: status\ndata: "
                           f"{json.dumps({'status': inv.status, 'confidence': inv.confidence})}\n\n")
                    return
            finally:
                db.close()
            time.sleep(1)
        yield f"event: status\ndata: {json.dumps({'status':'timeout'})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")