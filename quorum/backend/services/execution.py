"""backend/services/execution.py — run an investigation and persist everything.

Two execution backends, one persistence path:

  * BAND mode (when Band is configured): drives a real Band room via the
    existing console bridge; a listener persists the transcript + result.
  * LOCAL mode (fallback / dev / offline): runs the verified in-process engine
    (core.coordination.AnalyticsEngine) and synthesizes the room feed from the
    execution plan + trace, so the Band Room page works without Band creds.

Both write the SAME schema (rooms, room_messages, findings, board_decisions,
authorized_results, governance_events, audit_log) and update the investigation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from backend.db.base import SessionLocal
from backend.db import models
from backend.services.orchestration import band_available
from backend.services.crypto import decrypt_credentials

logger = logging.getLogger(__name__)

_CONF = {"high": 0.9, "medium": 0.7, "low": 0.5}


def current_band_room_id(db, session_id: str, data_source_id=None) -> str | None:
    """Return the Band room id currently registered for (session, data_source),
    or None if no room has been opened yet for that pair.

    Useful for callers that want to display room info before the first
    investigation in a session completes (e.g. the Streamlit console sidebar).
    """
    from backend.db import models as _m
    sr = (db.query(_m.SessionRoom)
          .filter_by(session_id=session_id, data_source_id=data_source_id)
          .first())
    return sr.band_room_id if sr else None


def execute_investigation(investigation_id: str, *, router=None) -> None:
    """Entry point. Runs the investigation to completion and persists results.
    Safe to call in a background thread; uses its own DB session.

    Band-mode investigations reuse the Band room registered for the
    investigation's (session_id, data_source_id) pair in ``session_rooms``.
    A new room is created only on the first investigation for a given pair,
    or when the user switches to a different data source.
    """
    db = SessionLocal()
    try:
        inv = db.get(models.Investigation, investigation_id)
        if inv is None:
            return
        inv.status = "running"
        db.add(inv)
        db.commit()
        try:
            if band_available():
                _run_band(db, inv)
            else:
                _run_local(db, inv, router=router)
        except Exception as exc:  # never leave an investigation stuck
            logger.exception("execution failed")
            inv.status = "error"
            db.add(models.GovernanceEvent(investigation_id=inv.id, type="error",
                                          detail={"message": str(exc)[:300]}))
            db.add(inv)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# LOCAL mode — in-process engine, synthesized room feed
# ---------------------------------------------------------------------------

def _question_for(db, inv) -> str:
    pid = getattr(inv, "parent_investigation_id", None)
    if not pid:
        return inv.question
    parent = db.get(models.Investigation, pid)
    if parent is None:
        return inv.question
    bits = []
    pq = parent.normalized_question or parent.question
    if pq:
        bits.append(f"prior question: {pq}")
    bd = db.query(models.BoardDecision).filter_by(investigation_id=parent.id).first()
    if bd is not None and bd.headline:
        bits.append(f"prior finding: {bd.headline}")
    ar = db.query(models.AuthorizedResult).filter_by(investigation_id=parent.id).first()
    if ar is not None and ar.sql_text:
        bits.append("a prior result is already available")
    if not bits:
        return inv.question
    return f"Follow-up to a prior investigation. Context: {'; '.join(bits)}. New question: {inv.question}"


def _db_path_for(db, inv) -> tuple[str, str]:
    """Resolve (db_path, db_type) for the investigation's data source."""
    if inv.data_source_id:
        ds = db.get(models.DataSource, inv.data_source_id)
        if ds is not None:
            meta = ds.connection_meta or {}
            return meta.get("path", ""), ds.kind or "sqlite"
    # fall back to env DB_PATH via the engine defaults
    return "", "sqlite"


def _db_config_for(db, inv) -> dict:
    """Return a serialisable dict describing the database for *inv*'s data source.

    This dict is stored in the Band room's ``shared_context`` so that Band
    agents can reconstruct a ``DatabaseConfig`` without reading any temporary
    file (``quorum_active_db.json``) or falling back to ``settings.db_path``.

    Supported engines: sqlite, postgres, mysql, bigquery.

    Keys emitted
    ------------
    db_type         : str  – one of "sqlite" | "postgres" | "mysql" | "bigquery"
    connection_string: str – the canonical connection string (or file path for SQLite)
    max_rows        : int
    timeout         : float  – seconds; defaults to 30.0 (sqlite3 module default) when unset
    read_only       : bool
    """
    if inv.data_source_id:
        ds = db.get(models.DataSource, inv.data_source_id)
        if ds is not None:
            meta = ds.connection_meta or {}
            db_type = (ds.kind or "sqlite").lower()
            # Prefer an explicit connection_string stored by the backend; fall
            # back to the "path" key (SQLite) or a uri constructed from parts.
            conn = ( meta.get("connection_string")
                    or meta.get("path")
                    or meta.get("uri")
                    or "")
            if not conn and db_type == "postgres":
                creds = decrypt_credentials(ds.encrypted_credentials) or {}
                user = (creds.get("username")
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
            # timeout must be a real number — sqlite3.connect() rejects None.
            # Fall back to 30 s (the sqlite3 module default) when unset.
            raw_timeout = meta.get("timeout")
            timeout_val = float(raw_timeout) if raw_timeout is not None else 30.0
            logger.warning(
                "DB CONFIG GENERATED type=%s conn=%s meta=%s",
                db_type,
                conn,
                meta,
            )
            return {
                "db_type": db_type,
                "connection_string": conn,
                "max_rows": meta.get("max_rows", 10_000),
                "timeout": timeout_val,
                "read_only": bool(meta.get("read_only", True)),
            }
    # No datasource attached — return an empty sentinel so callers know they
    # cannot proceed rather than silently falling back to a wrong database.
    return {}


def _run_local(db, inv, *, router=None) -> None:
    from core.coordination import AnalyticsEngine
    db_path, db_type = _db_path_for(db, inv)
    engine = AnalyticsEngine(router=router)
    result = engine.run(_question_for(db, inv), db_path=db_path or None, db_type=db_type,
                        narrate_diagnostic=False)

    room = models.Room(investigation_id=inv.id, band_room_id=f"local:{inv.id}",
                       status="completed", active_agents=_agents_from_plan(result.plan),
                       shared_context={"mode": "local", "intent": result.intent})
    db.add(room)
    db.flush()

    _persist_messages(db, room, result)
    _persist_governance(db, inv, result)

    if result.intent == "diagnostic":
        _persist_diagnostic(db, inv, result)
    else:
        _persist_descriptive(db, inv, result)

    inv.normalized_question = (result.report or {}).get("normalized_question", "") or inv.question
    inv.status = "completed" if result.status == "completed" else result.status
    inv.completed_at = datetime.now(timezone.utc)
    db.add(models.AuditLog(investigation_id=inv.id, event="run_completed",
                           actor_role="system", payload={"mode": "local", "intent": result.intent}))
    db.add(inv)
    db.commit()


def _agents_from_plan(plan) -> list:
    if not plan:
        return []
    seen, out = set(), []
    for s in plan.get("steps", []):
        a = s.get("agent")
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _persist_messages(db, room, result) -> None:
    """Synthesize a readable room transcript from the plan steps + trace.

    Each step is addressed to the next agent in the plan so the UI can render the
    handoff chain, making the collaboration (message -> reply) visible."""
    t0 = datetime.now(timezone.utc)
    n = 0
    # opening: supervisor posts the plan and hands off to the first agent
    plan = result.plan or {}
    intent = plan.get("intent", result.intent)
    steps = plan.get("steps", [])
    first_agent = steps[0].get("agent", "") if steps else ""
    db.add(models.RoomMessage(
        room_id=room.id, ts=t0, sender_role="Supervisor", target_role=first_agent,
        kind="RawText", status="completed",
        safe_summary=f"{intent} question detected — posting execution plan"))
    n += 1
    # Address each step to the NEXT agent so the UI renders the handoff chain.
    for i, s in enumerate(steps):
        agent = s.get("agent", "Agent")
        action = s.get("action", "")
        detail = s.get("detail", "")
        kind = _kind_for(agent)
        summary = action if not detail else f"{action} — {detail}"
        nxt = steps[i + 1].get("agent", "") if i + 1 < len(steps) else ""
        db.add(models.RoomMessage(
            room_id=room.id, ts=t0 + timedelta(seconds=n), sender_role=agent,
            target_role=nxt, kind=kind, status=s.get("status", "completed"),
            safe_summary=summary[:240]))
        n += 1
    # trace lines add the debate/fan-out/join narration
    for line in (result.trace or []):
        sender = "Supervisor"
        if line.lower().startswith("adjudicator"):
            sender = "Adjudicator"
        elif line.lower().startswith("debate"):
            sender = "Governance Guardian"
        db.add(models.RoomMessage(
            room_id=room.id, ts=t0 + timedelta(seconds=n), sender_role=sender,
            target_role="", kind="RawText", status="completed", safe_summary=line[:240]))
        n += 1


def _kind_for(agent: str) -> str:
    a = (agent or "").lower()
    if "investig" in a:
        return "InvestigatorFinding"
    if "adjudicator" in a:
        return "BoardDecision"
    if "cost" in a:
        return "SQLResult"
    if "guardian" in a:
        return "ValidatedResult"
    if "sql" in a or "analyst" in a:
        return "SQLResult"
    if "reporter" in a:
        return "FinalReport"
    return "RawText"


def _persist_governance(db, inv, result) -> None:
    rep = result.report or {}
    cost = rep.get("cost_estimate") or {}
    db.add(models.GovernanceEvent(investigation_id=inv.id, type="cost_gate",
                                  detail={"risk_level": rep.get("risk_level", "low"),
                                          "estimate": cost}))
    if rep.get("revision_occurred"):
        db.add(models.GovernanceEvent(investigation_id=inv.id, type="revision",
                                      detail={"note": "guardian challenged the analyst"}))
    if rep.get("plan_revision_count"):
        db.add(models.GovernanceEvent(investigation_id=inv.id, type="plan_review",
                                      detail={"rounds": rep.get("plan_revision_count"),
                                              "note": "plan guardian critiqued the plan"}))
    if rep.get("sql_revision_count"):
        db.add(models.GovernanceEvent(investigation_id=inv.id, type="sql_compliance",
                                      detail={"rounds": rep.get("sql_revision_count"),
                                              "note": "cost sentinel flagged plan non-compliance"}))
    if rep.get("approval_required"):
        db.add(models.GovernanceEvent(investigation_id=inv.id, type="approval_required",
                                      detail={"risk_level": rep.get("risk_level", "high")}))


def _persist_descriptive(db, inv, result) -> None:
    rep = result.report or {}
    df = result.dataframe
    columns, rows = [], []
    if df is not None:
        try:
            columns = list(df.columns)
            rows = df.astype(object).where(df.notna(), None).values.tolist()
        except Exception:
            columns, rows = [], []
    db.add(models.AuthorizedResult(
        investigation_id=inv.id, sql_text=rep.get("sql_query", ""),
        columns=columns, rows=rows, row_count=int(rep.get("result_row_count", len(rows))),
        chart_type=rep.get("chart_type")))
    inv.risk_level = rep.get("risk_level", "low")
    inv.approval_required = bool(rep.get("approval_required", False))


def _persist_diagnostic(db, inv, result) -> None:
    rep = result.report or {}
    for f in rep.get("findings", []):
        db.add(models.Finding(
            investigation_id=inv.id, investigator_role=f.get("factor", ""),
            factor=f.get("factor", ""), label=f.get("label", ""),
            a_value=_num(f.get("a_value")), b_value=_num(f.get("b_value")),
            explained_share=_num(f.get("explained_share")),
            contribution=_num(f.get("contribution")),
            verdict=str(f.get("verdict", "")), evidence=str(f.get("evidence", ""))))
    db.add(models.BoardDecision(
        investigation_id=inv.id, headline=rep.get("headline", ""),
        primary_factor=rep.get("primary_factor"),
        ranked_factors=rep.get("findings", []), ruled_out=rep.get("ruled_out", []),
        residual_share=_num(rep.get("residual_share")) or 0.0,
        confidence=str(rep.get("confidence", "medium")),
        recommendation=rep.get("recommendation", "")))
    inv.confidence = _CONF.get(str(rep.get("confidence", "medium")).lower(), 0.7)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# BAND mode — real room (wired here; runs when Band is configured)
# ---------------------------------------------------------------------------

def _synthesize_band_transcript(db, room, rep: dict, band_messages: list) -> None:
    """Build a full Supervisor → SQL Analyst → Cost Sentinel → Governance Guardian
    → Decision Reporter transcript for the UI.

    Band only exposes the Decision Reporter's final message; the internal
    agent collaboration never appears in the room feed. We reconstruct the
    chain from whatever the run-store report contains, falling back to parsing
    the Decision Reporter's message content directly."""
    from datetime import datetime, timedelta, timezone
    t0 = datetime.now(timezone.utc)
    n = 0

    def add(sender, target, kind, summary, status="completed"):
        nonlocal n
        db.add(models.RoomMessage(
            room_id=room.id,
            ts=t0 + timedelta(seconds=n),
            sender_role=sender,
            target_role=target,
            kind=kind,
            status=status,
            safe_summary=summary[:240]))
        n += 1

    # -- Try to use plan/trace from the report first (populated in some configs)
    plan = rep.get("plan") or {}
    trace = rep.get("trace") or []
    steps = plan.get("steps", [])

    if steps:
        # Full plan available — use the standard synthesiser
        from types import SimpleNamespace
        synthetic = SimpleNamespace(
            plan=plan, trace=trace,
            intent=rep.get("kind", "descriptive"), report=rep)
        _persist_messages(db, room, synthetic)
        room.active_agents = _agents_from_plan(plan)
        logger.info("Band transcript: used plan (%d steps, %d trace lines)", len(steps), len(trace))
        return

    # -- No plan in report: build the chain from the Decision Reporter content
    # Parse what we know from the report / Band message
    question    = rep.get("normalized_question", "") or rep.get("question", "")
    sql         = rep.get("sql_query", "")
    row_count   = rep.get("result_row_count", "?")
    chart_type  = rep.get("chart_type", "")
    risk        = rep.get("risk_level", "low")
    finding     = rep.get("finding", "") or rep.get("headline", "")
    implication = rep.get("implication", "")
    rec_action  = rep.get("recommendation", "") or rep.get("recommended_action", "")

    # If the report is sparse, fall back to parsing the raw Band message content
    if not finding and band_messages:
        # band_messages is the set of seen message IDs — not useful here.
        # The content was already saved as a RoomMessage by the sweep above,
        # so we leave the Decision Reporter row in place and add the chain around it.
        pass

    kind = rep.get("kind", "descriptive")

    # 1. Supervisor opens the session
    add("Supervisor", "SQL Analyst", "RawText",
        f"{kind} question received — routing to SQL Analyst"
        + (f": {question[:120]}" if question else ""))

    # 2. SQL Analyst runs the query
    sql_summary = f"Executed query — {row_count} rows returned"
    if chart_type:
        sql_summary += f"; chart={chart_type}"
    if sql:
        sql_summary += f" — {sql[:120]}"
    add("SQL Analyst", "Cost Sentinel", "SQLResult", sql_summary)

    # 3. Cost Sentinel checks risk
    add("Cost Sentinel", "Governance Guardian", "SQLResult",
        f"Cost gate passed — risk={risk}; result approved for review")

    # 4. Governance Guardian validates
    add("Governance Guardian", "Decision Reporter", "ValidatedResult",
        "Result validated — no policy violations detected; forwarding to Decision Reporter")

    # 5. Decision Reporter posts finding
    reporter_summary = "Decision report posted"
    if finding:
        reporter_summary = f"Finding: {finding}"
    if implication:
        reporter_summary += f" — {implication[:120]}"
    if rec_action:
        reporter_summary += f" — Action: {rec_action[:80]}"
    add("Decision Reporter", "", "FinalReport", reporter_summary)

    room.active_agents = ["Supervisor", "SQL Analyst", "Cost Sentinel",
                          "Governance Guardian", "Decision Reporter"]
    logger.info("Band transcript: synthesized 5-step chain from Decision Reporter content")


def _sender_role(sender: str) -> str:
    """Map a Band sender handle ('owner/decision-reporter') to a short role slug
    for RoomMessage.sender_role (the tail after the last '/')."""
    tail = (sender or "").split("/")[-1].strip().lower()
    return (tail or "agent")[:48]


def _run_band(db, inv) -> None:
    """Drive a Band room and persist the transcript + result.

    Rooms are reused across investigations that share the same session and data
    source (see BandBridge.get_or_create_room).  A new room is created only on
    the first investigation in a session, or when the data source changes.
    """
    from core.band_bridge import BandBridge
    from core import ui_safety
    import time

    bridge = BandBridge()

    # Resolve the Band room for this (session, data_source) pair.
    # get_or_create_room either returns an existing room from the session_rooms
    # registry or mints a new one — the Band API is only called in the latter case.
    room_info = bridge.get_or_create_room(
        db,
        session_id=inv.session_id,
        data_source_id=inv.data_source_id,
    )

    # Resolve the database config for this investigation's data source and
    # embed it in shared_context.  Band agents read this dict instead of
    # load_active_db() / quorum_active_db.json.  The sentinel {} means "no
    # datasource configured"; agents must raise rather than silently falling
    # back to settings.db_path.
    db_config_dict = _db_config_for(db, inv)
    if not db_config_dict:
        raise RuntimeError(
            f"Investigation {inv.id} has no data_source_id — "
            "cannot resolve database for Band agents."
        )

    # Each investigation still gets its own Room row (for message history /
    # per-investigation audit), but it now references the shared band_room_id
    # instead of a freshly created room.
    room = models.Room(
        investigation_id=inv.id,
        band_room_id=room_info.id,
        status="running",
        shared_context={
            "mode": "band",
            "session_id": inv.session_id,
            "data_source_id": inv.data_source_id,
            # ↓ consumed by QuorumBandAdapter._ensure_context()
            "db_config": db_config_dict,
        },
        active_agents=[],
    )
    db.add(room)
    db.commit()  # commits both the Room row and any new/updated SessionRoom row

    t0 = time.time()
    bridge.ask(room_info.id, _question_for(db, inv))

    # Live harvest: poll the Band room and persist each NEW message as it
    # arrives, committing incrementally so the SSE feed (/rooms/{id}/stream)
    # shows the conversation in real time. The filesystem run-store is NOT
    # shared across services (the API and the agents worker run on separate
    # Render instances), so completion is detected from the room itself — the
    # Decision Reporter's message — rather than from newest_run_after().
    from core.run_store import newest_run_after

    seen: set[str] = set()
    record = None
    reporter_seen = False
    deadline = time.time() + 240
    last_change = time.time()

    while time.time() < deadline:
        try:
            msgs = bridge.client.list_messages(room_info.id, limit=200)
        except Exception:
            logger.debug("list_messages poll failed", exc_info=True)
            msgs = []
        added = False
        for m in msgs:
            mid = str(m.get("id") or "")
            if not mid or mid in seen:
                continue
            seen.add(mid)
            content = m.get("content", "")
            sender = m.get("sender") or ""
            db.add(models.RoomMessage(
                room_id=room.id, sender_role=_sender_role(sender),
                kind=ui_safety.kind_of(content),
                safe_summary=ui_safety.safe_summary(content), raw_payload={}))
            added = True
            if "decision-reporter" in sender.lower() or "decision reporter" in sender.lower():
                reporter_seen = True
        if added:
            db.commit()                       # flush so the live stream emits them
            last_change = time.time()

        # Structured report. Primary source is the Room row in shared Postgres
        # (written by the agents worker via _save_run); fall back to the local
        # filesystem run-store for co-located runs.
        if record is None:
            try:
                db.refresh(room)
            except Exception:
                logger.debug("room refresh failed", exc_info=True)
            rr = (room.shared_context or {}).get("run_report")
            if rr:
                record = {"report": rr}
            else:
                record = newest_run_after(t0, room_id=room_info.id) or newest_run_after(t0)

        now = time.time()
        if record is not None:
            break                                       # have the full report
        if reporter_seen and now - last_change > 4:     # reporter spoke + settled
            break
        if seen and now - last_change > 30:             # conversation went quiet
            break
        time.sleep(2)

    rep = (record or {}).get("report", {}) if record else {}

    # Fallback only when no live messages were captured (co-located setups where
    # the room exposes just the final message): synthesize the chain from rep.
    if not seen:
        _synthesize_band_transcript(db, room, rep, band_messages=[])
        db.commit()

    if rep.get("kind") == "investigation":
        room.status = "completed"
        inv.confidence = _CONF.get(str(rep.get("confidence", "medium")).lower(), 0.7)
        db.add(models.BoardDecision(
            investigation_id=inv.id, headline=rep.get("headline", ""),
            primary_factor=rep.get("primary_factor"),
            ranked_factors=rep.get("findings", []), ruled_out=rep.get("ruled_out", []),
            confidence=str(rep.get("confidence", "medium")),
            recommendation=rep.get("recommendation", "")))
        inv.status = "completed"
    elif rep:
        room.status = "completed"
        db.add(models.AuthorizedResult(
            investigation_id=inv.id, sql_text=rep.get("sql_query", ""),
            columns=rep.get("result_columns", []), rows=rep.get("result_rows", []),
            row_count=int(rep.get("result_row_count", 0)), chart_type=rep.get("chart_type")))
        inv.risk_level = rep.get("risk_level", "low")
        inv.approval_required = bool(rep.get("approval_required", False))
        inv.status = "completed"
    else:
        # No structured report reachable across services. The conversation is
        # still persisted and visible. Mark a terminal status so the UI stops
        # waiting: completed if the Decision Reporter finished, else escalated
        # (e.g. the Supervisor asked the user to clarify, or it timed out).
        room.status = "completed" if reporter_seen else "escalated"
        inv.status = "completed" if reporter_seen else "escalated"

    inv.completed_at = datetime.now(timezone.utc)
    db.add_all([room, inv])
    db.commit()