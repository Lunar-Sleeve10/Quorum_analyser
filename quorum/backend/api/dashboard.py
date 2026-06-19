"""backend/api/dashboard.py — aggregated KPIs for the Control Tower.

Aggregation lives here (not in the UI) so the Streamlit app stays a pure client.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models
from backend.deps import get_or_create_session
from backend.services import quota

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(session: models.Session = Depends(get_or_create_session),
            db: DbSession = Depends(get_db)) -> dict:
    invs = (db.query(models.Investigation).filter_by(session_id=session.id)
            .order_by(models.Investigation.created_at.desc()).all())
    confs = [i.confidence for i in invs if i.confidence is not None]
    gov = (db.query(func.count(models.GovernanceEvent.id))
           .join(models.Investigation,
                 models.GovernanceEvent.investigation_id == models.Investigation.id)
           .filter(models.Investigation.session_id == session.id).scalar() or 0)
    escalations = (db.query(func.count(models.GovernanceEvent.id))
                   .join(models.Investigation,
                         models.GovernanceEvent.investigation_id == models.Investigation.id)
                   .filter(models.Investigation.session_id == session.id,
                           models.GovernanceEvent.type == "approval_required").scalar() or 0)
    return {
        "session_token": session.token,
        "active_investigations": len([i for i in invs if i.status in ("planning", "running")]),
        "review_boards": len([i for i in invs if i.topology == "investigation_board"]),
        "completed": len([i for i in invs if i.status == "completed"]),
        "escalations": int(escalations),
        "governance_events": int(gov),
        "avg_confidence": round(sum(confs) / len(confs), 2) if confs else None,
        "queries_remaining": quota.remaining(db, session)["queries_remaining"],
        "recent": [{"id": i.id, "question": i.question[:70], "topology": i.topology,
                    "status": i.status, "confidence": i.confidence} for i in invs[:8]],
    }
