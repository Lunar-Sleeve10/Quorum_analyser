"""backend/api/investigations.py — create/list/get investigations + follow-ups.

Phase 1: persists the investigation and its chosen topology, enforces session
quotas, and supports attached follow-ups. The live Band run + room-listener
persistence land in a later phase; the records and topology are real now.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from backend.db.base import get_db
from backend.db import models
from backend.deps import get_or_create_session
from backend.services import quota
from backend.services.orchestration import classify_topology

router = APIRouter(prefix="/investigations", tags=["investigations"])


class CreateInvestigation(BaseModel):
    question: str
    data_source_id: str | None = None
    scope_id: str | None = None


class FollowupBody(BaseModel):
    question: str


def _serialize(inv: models.Investigation) -> dict:
    return {
        "id": inv.id, "question": inv.question,
        "normalized_question": inv.normalized_question,
        "topology": inv.topology, "status": inv.status,
        "confidence": inv.confidence, "risk_level": inv.risk_level,
        "approval_required": inv.approval_required,
        "estimated_cost_usd": inv.estimated_cost_usd,
        "data_source_id": inv.data_source_id, "scope_id": inv.scope_id,
        "parent_investigation_id": inv.parent_investigation_id,
        "followups_used": inv.followups_used,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
    }


@router.post("")
def create_investigation(
    body: CreateInvestigation,
    background: BackgroundTasks,
    session: models.Session = Depends(get_or_create_session),
    db: DbSession = Depends(get_db),
) -> dict:
    if not body.question.strip():
        raise HTTPException(400, "Question is required.")
    if not quota.can_start_investigation(session):
        raise HTTPException(429, "Investigation quota exhausted for this session.")

    inv = models.Investigation(
        session_id=session.id, data_source_id=body.data_source_id,
        scope_id=body.scope_id, question=body.question.strip(),
        topology=classify_topology(body.question), status="planning")
    db.add(inv)
    db.commit()
    db.refresh(inv)
    quota.consume_investigation(db, session)
    db.add(models.AuditLog(investigation_id=inv.id, event="investigation_created",
                           actor_role="user", payload={"topology": inv.topology}))
    db.commit()

    # kick off execution in the background (Band mode if configured, else local)
    from backend.services.execution import execute_investigation
    background.add_task(execute_investigation, inv.id)

    out = _serialize(inv)
    out["session_token"] = session.token
    out["queries_remaining"] = quota.remaining(db, session)["queries_remaining"]
    return out


@router.get("")
def list_investigations(
    session: models.Session = Depends(get_or_create_session),
    db: DbSession = Depends(get_db),
) -> list[dict]:
    rows = (db.query(models.Investigation)
            .filter_by(session_id=session.id)
            .order_by(models.Investigation.created_at.desc()).all())
    return [_serialize(r) for r in rows]


@router.get("/{investigation_id}")
def get_investigation(investigation_id: str, db: DbSession = Depends(get_db)) -> dict:
    inv = db.get(models.Investigation, investigation_id)
    if inv is None:
        raise HTTPException(404, "Investigation not found.")
    findings = db.query(models.Finding).filter_by(investigation_id=inv.id).all()
    decision = db.query(models.BoardDecision).filter_by(investigation_id=inv.id).first()
    result = db.query(models.AuthorizedResult).filter_by(investigation_id=inv.id).first()
    out = _serialize(inv)
    out["findings"] = [{"factor": f.factor, "label": f.label, "verdict": f.verdict,
                        "evidence": f.evidence} for f in findings]
    out["board_decision"] = (None if decision is None else
                             {"headline": decision.headline,
                              "primary_factor": decision.primary_factor,
                              "recommendation": decision.recommendation,
                              "confidence": decision.confidence})
    out["authorized_result"] = (None if result is None else
                                {"columns": result.columns, "rows": result.rows,
                                 "row_count": result.row_count, "chart_type": result.chart_type})
    children = (db.query(models.Investigation)
                .filter_by(parent_investigation_id=inv.id)
                .order_by(models.Investigation.created_at.asc()).all())
    out["followups"] = [{"id": c.id, "question": c.question, "status": c.status,
                         "topology": c.topology, "confidence": c.confidence}
                        for c in children]
    gov = (db.query(models.GovernanceEvent).filter_by(investigation_id=inv.id)
           .order_by(models.GovernanceEvent.ts.asc()).all())
    cost_ev = next((g for g in gov if g.type == "cost_gate"), None)
    out["cost"] = cost_ev.detail if cost_ev else None
    out["governance"] = [{"type": g.type, "detail": g.detail,
                          "ts": g.ts.isoformat() if g.ts else None} for g in gov]
    out["sql"] = result.sql_text if result is not None else None
    return out


@router.post("/{investigation_id}/followup")
def add_followup(
    investigation_id: str, body: FollowupBody, background: BackgroundTasks,
    db: DbSession = Depends(get_db),
) -> dict:
    parent = db.get(models.Investigation, investigation_id)
    if parent is None:
        raise HTTPException(404, "Investigation not found.")
    if not body.question.strip():
        raise HTTPException(400, "Question is required.")
    if not quota.can_followup(parent):
        raise HTTPException(429, "Follow-up quota exhausted for this investigation.")

    child = models.Investigation(
        session_id=parent.session_id, data_source_id=parent.data_source_id,
        scope_id=parent.scope_id, parent_investigation_id=parent.id,
        question=body.question.strip(), topology=classify_topology(body.question),
        status="planning")
    db.add(child)
    db.commit()
    db.refresh(child)

    db.add(models.Followup(investigation_id=parent.id, question=child.question,
                           answer={"child_investigation_id": child.id}))
    quota.consume_followup(db, parent)
    db.add(models.AuditLog(investigation_id=child.id, event="followup_created",
                           actor_role="user", payload={"parent_investigation_id": parent.id}))
    db.commit()

    from backend.services.execution import execute_investigation
    background.add_task(execute_investigation, child.id)

    out = _serialize(child)
    out["followups_used"] = parent.followups_used
    return out
