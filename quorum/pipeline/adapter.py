"""
pipeline/adapter.py — Band SDK adapter wrapping the Quorum agents.

Each role runs as a separate connected Band agent (one process per role, see
pipeline/run_agent.py). Collaboration happens IN the Band room via @mention
handoffs:

  Human → @Supervisor
            ├─ descriptive →  @SQL Analyst → @Cost Sentinel → @Governance Guardian
            │                       ↑ (bounded debate) ──────────┘
            │                 @Governance Guardian → @Decision Reporter → Human
            └─ diagnostic  →  fan-out @Investigator×N  → (join) @Adjudicator → Human

Band requires every message to carry a structured mention. Handoffs are posted
through the verified REST message API (core.band_client.ask, which builds the
mention object), using THIS agent's own credentials — the same path the console
uses to post the question. That sidesteps the runtime tools.send_message mention
format. If no REST credentials are available, it falls back to tools.send_message.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Optional
import inspect

from agents.adjudicator import AdjudicatorAgent
from agents.orchestrator import ClarificationNeeded
from agents.cost_sentinel import CostSentinelAgent
from agents.governance_guardian import GovernanceGuardianAgent
from agents.plan_guardian import PlanGovernanceGuardianAgent
from agents.investigator import FactorInvestigatorAgent
from agents.planner import PlannerAgent
from agents.reporting import VisualizationReportingAgent
from agents.sql_engineer import SQLEngineerAgent
from pipeline import payload
from pipeline.models import (
    BoardDecision, ComparisonSpec, FinalReport, Grounding, InvestigationTask,
    InvestigatorFinding, RevisionRequest, SchemaGroundedTask, SQLResult,
    UserQuery, ValidatedResult, make_envelope,
)
from pipeline.session_context import context_store
from config import BandConfig, DatabaseType, IssueType, settings
from core import investigation
from core.investigation import inv_from_dict, inv_to_dict
from core.cache import SchemaCache
from core.database import make_adapter
from models.state import DatabaseConfig
from pathlib import Path

logger = logging.getLogger(__name__)


DISPLAY_NAMES: dict[str, str] = {
    "supervisor": "Supervisor",
    "sql_analyst": "SQL Analyst",
    "cost_sentinel": "Cost Sentinel",
    "guardian": "Governance Guardian",
    "decision_reporter": "Decision Reporter",
    "investigator": "Investigator",
    "adjudicator": "Adjudicator",
    "dashboard": "Dashboard",
    "user": "User",
}
VALID_ROLES = set(DISPLAY_NAMES) - {"user", "dashboard"}


def _slug(role: str) -> str:
    """Participant handle tail Band assigns from the display name:
    'SQL Analyst' -> 'sql-analyst', 'Governance Guardian' -> 'governance-guardian'."""
    return DISPLAY_NAMES.get(role, role).lower().replace(" ", "-")


try:  # pragma: no cover - optional dependency
    from band.core.simple_adapter import SimpleAdapter
    from band.core.protocols import AgentToolsProtocol
    from band.core.types import PlatformMessage
    _SDK = True
except Exception:  # pragma: no cover
    SimpleAdapter = object        # type: ignore
    AgentToolsProtocol = Any      # type: ignore
    PlatformMessage = Any         # type: ignore
    _SDK = False


class QuorumBandAdapter(SimpleAdapter):  # type: ignore[misc]
    """One instance per role. Wraps the matching agent and performs the
    @mention handoff to the next role via the verified REST message API."""

    _dumped_api = False

    def __init__(self, *, role: str, api_key: str = "", base_url: str = "",
                 display_names: Optional[dict[str, str]] = None) -> None:
        if role not in VALID_ROLES:
            raise ValueError(f"Unknown role {role!r}; must be one of {VALID_ROLES}")
        if _SDK:
            super().__init__(history_converter=None)  # type: ignore[call-arg]
        self.role = role
        self.display_names = display_names or DISPLAY_NAMES
        self._participants_msg = ""
        self._history: list = []
        self._agent = self._build_agent(role)
        # REST poster, using THIS agent's credentials — same verified path as the
        # console's question-posting (mentions built by band_client).
        self._poster = None
        if api_key:
            try:
                from core.band_client import BandDashboardClient
                self._poster = BandDashboardClient(api_key, base_url or settings.band_rest_url)
            except Exception as exc:
                logger.warning("REST poster unavailable (%s); will try tools.send_message", exc)

    def _build_agent(self, role: str):
        if role == "supervisor":
            return PlannerAgent()
        if role == "sql_analyst":
            return SQLEngineerAgent()
        if role == "cost_sentinel":
            return CostSentinelAgent()
        if role == "guardian":
            return GovernanceGuardianAgent()
        if role == "decision_reporter":
            return VisualizationReportingAgent()
        if role == "investigator":
            return None
        if role == "adjudicator":
            return AdjudicatorAgent()
        raise ValueError(role)

    # ------------------------------------------------------------------
    async def on_started(self, agent_name: str, agent_description: str) -> None:
        if _SDK:
            await super().on_started(agent_name, agent_description)  # type: ignore[misc]
        logger.info("Band agent online: role=%s", self.role)

    async def on_cleanup(self, room_id: str) -> None:
        if self.role == "supervisor" and context_store.exists(room_id):
            context_store.remove(room_id)

    def _ensure_context(self, room_id: str):
        if context_store.exists(room_id):
            return context_store.get(room_id)

        # Obtain the database configuration from the Room row that was written
        # by execution._run_band() before the first ask().  This replaces the
        # old load_active_db() / quorum_active_db.json hand-off that only
        # worked when a Streamlit process was co-located on the same machine.
        cfg = self._db_config_from_room(room_id)
        if cfg is None:
            # Fallback: the Room row may live in a different database (e.g.
            # Render Postgres) than the one the agent process can reach (local
            # SQLite).  Build a DatabaseConfig from the environment settings
            # (DB_PATH / DB_TYPE) so the agent can still proceed.
            logger.warning(
                "Room lookup returned no db_config for room=%s; "
                "falling back to environment settings (DB_PATH / DB_TYPE).",
                room_id,
            )
            cfg = self._db_config_from_env()
        if cfg is None:
            raise RuntimeError(
                f"Band agent (role={self.role}, room={room_id}): no database "
                "configuration found — neither from the room's shared_context "
                "nor from environment settings (DB_PATH / DB_TYPE).  Ensure "
                "the backend and agents share the same DATABASE_URL, or set "
                "DB_PATH in the agent environment."
            )
        logger.info(
            "DB CONFIG room=%s type=%s conn=%s",
            room_id,
            cfg.db_type,
            cfg.connection_string,
        )

        adapter = make_adapter(cfg)
        SchemaCache.get_schema(cfg.connection_string, adapter)
        return context_store.create(room_id, adapter=adapter, db_config=cfg)

    @staticmethod
    def _db_config_from_env() -> "DatabaseConfig | None":
        """Fallback: build a DatabaseConfig from environment settings
        (``settings.db_path``, ``settings.db_type``).

        Used when the Room row written by ``execution._run_band()`` is not
        visible to this process — typically because the API and agents use
        different databases (e.g. Render Postgres vs local SQLite during
        hybrid development).
        """
        try:
            db_path = getattr(settings, "db_path", "") or ""
            if not db_path:
                return None
            db_type_str = str(getattr(settings, "db_type", "sqlite")).lower()
            # db_type may be a DatabaseType enum or a plain string.
            try:
                dbt = DatabaseType(db_type_str)
            except (ValueError, KeyError):
                dbt = DatabaseType.SQLITE
            raw_timeout = getattr(settings, "db_timeout", 30.0)
            timeout_val = float(raw_timeout) if raw_timeout is not None else 30.0
            return DatabaseConfig(
                db_type=dbt,
                connection_string=db_path,
                max_rows=int(getattr(settings, "db_max_rows", 10_000)),
                timeout=timeout_val,
                read_only=bool(getattr(settings, "db_read_only", True)),
            )
        except Exception:
            logger.exception("Failed to build DatabaseConfig from env settings")
            return None

    @staticmethod
    def _db_config_from_room(room_id: str) -> "DatabaseConfig | None":
        """Look up the Room row whose band_room_id matches *room_id* and
        reconstruct a DatabaseConfig from the ``db_config`` dict embedded by
        execution._run_band() in shared_context.

        Supports sqlite, postgres, mysql, and bigquery — whatever kind the
        DataSource row on the backend records.
        """
        try:
            from backend.db.base import SessionLocal
            from backend.db import models as _m
            db = SessionLocal()
            try:
                room = (
                    db.query(_m.Room)
                    .filter_by(band_room_id=room_id)
                    .order_by(_m.Room.id.desc())
                    .first()
                )
                if room is None:
                    return None
                ctx = room.shared_context or {}
                raw = ctx.get("db_config") or {}
                if not raw or not raw.get("connection_string"):
                    return None
                db_type_str = (raw.get("db_type") or "sqlite").lower()
                # timeout must be a real number — sqlite3.connect() rejects None.
                # The dict written by execution._db_config_for() already
                # normalises this to a float, but guard here too for robustness.
                raw_timeout = raw.get("timeout")
                timeout_val = float(raw_timeout) if raw_timeout is not None else 30.0
                return DatabaseConfig(
                    db_type=DatabaseType(db_type_str),
                    connection_string=raw["connection_string"],
                    max_rows=int(raw.get("max_rows") or 10_000),
                    timeout=timeout_val,
                    read_only=bool(raw.get("read_only", True)),
                )
            finally:
                db.close()
        except Exception:
            logger.exception(
                "Failed to read db_config from Room.shared_context for room=%s", room_id
            )
            return None

    # ------------------------------------------------------------------
    async def on_message(self, msg, tools, history, participants_msg,
                         contacts_msg=None, *, is_session_bootstrap: bool, room_id: str) -> None:
        self._participants_msg = participants_msg or ""
        # Keep the room history for handlers that derive distributed state from
        # it (the Adjudicator counts InvestigatorFinding messages here — the
        # Band room is the single source of truth across separate processes).
        self._history = history or []
        decoded = payload.decode(getattr(msg, "content", "") or "")
        ctx = self._ensure_context(room_id)
        try:
            handler = getattr(self, f"_on_{self.role}")
            await handler(decoded, tools, room_id, ctx)
        except ClarificationNeeded as cn:
            # Human-in-the-loop escalation: a vague question must become a
            # visible clarification in the room, not a generic crash. The human
            # is represented by the Dashboard participant (there is no 'user'
            # participant in the room — posting to 'user' fails delivery and
            # leaves the message permanently retrying during resync).
            msg_text = getattr(getattr(cn, "request", None), "clarification_message", "") \
                or "Could you clarify your question (specific metric, region, and timeframe)?"
            await self._post(tools, room_id,
                             f"I need a bit more detail to proceed. {msg_text}",
                             target_role="dashboard")
        except Exception as exc:
            logger.exception("adapter error role=%s", self.role)
            await self._post(tools, room_id, f"{self.display_names[self.role]} error: {exc}",
                             target_role="dashboard")

    # ------------------------------------------------------------------
    # Supervisor
    # ------------------------------------------------------------------
    async def _on_supervisor(self, decoded, tools, room_id, ctx) -> None:
        # --- Supervisor-owned SQL plan-compliance DECISION ------------------
        # A non-compliant SQLResult is routed here by the Cost Sentinel. The
        # Supervisor (the loop owner) decides whether to ask the SQL Analyst to
        # revise (bounded by sql_revision_count) or to proceed to governance.
        if isinstance(decoded.message, SQLResult):
            await self._decide_compliance(decoded.message, tools, room_id, ctx)
            return

        if decoded.kind != "RawText" or not decoded.raw or not decoded.raw.text:
            return
        question = decoded.raw.text
        # Use the database config resolved from the Room's shared_context
        # (set by execution._run_band) so the Supervisor and all downstream
        # agents operate on the same datasource that the investigation
        # references — not on settings.db_path / settings.db_type.
        db_cfg = ctx.db_config
        db_conn = db_cfg.connection_string if db_cfg else ""
        db_type_val = (
            db_cfg.db_type.value
            if db_cfg and hasattr(db_cfg.db_type, "value")
            else (str(db_cfg.db_type) if db_cfg else "sqlite")
        )
        planned = self._agent.plan(session_id=room_id, question=question,
                                   adapter=ctx.adapter, db_path=db_conn,
                                   db_type=db_type_val)

        # --- Supervisor-owned PLAN-REVIEW gate (pre-execution, in-process) ---
        # The Plan Guardian critiques; the Supervisor decides whether to ask the
        # Planner to re-plan. Running it inside the supervisor process keeps the
        # loop owner singular and avoids any agent->agent loop in the room.
        plan_guardian = PlanGovernanceGuardianAgent(llm_router=getattr(self._agent, "router", None))
        review = plan_guardian.review(
            session_id=room_id, question=question, intent=planned.plan.intent,
            query_pattern=planned.plan.query_pattern, task=planned.task,
            factors=planned.plan.factors,
            allow_llm=(ctx.plan_revision_count < 1))
        while review.verdict == "revise" and ctx.plan_revision_count < 1:
            ctx.plan_revision_count += 1
            crit = "; ".join(review.issues + review.missing_dimensions
                             + review.missing_factors + review.missing_metrics)
            await self._post(tools, room_id,
                             f"Plan Guardian flagged plan gaps; Supervisor re-planning. {crit}",
                             target_role="dashboard")
            planned = self._agent.plan(session_id=room_id, question=question,
                                       adapter=ctx.adapter, db_path=db_conn,
                                       db_type=db_type_val, plan_feedback=crit)
            review = plan_guardian.review(
                session_id=room_id, question=question, intent=planned.plan.intent,
                query_pattern=planned.plan.query_pattern, task=planned.task,
                factors=planned.plan.factors, allow_llm=False)
        # ---------------------------------------------------------------------

        plan = planned.plan
        plan_text = _plan_text(plan)

        if planned.investigation is not None:
            inv = planned.investigation
            # Band-native DYNAMIC RECRUITMENT: the Supervisor pulls the
            # investigation board into the room on demand, sized to THIS
            # question's factors, and announces it so the move is visible.
            await self._post(tools, room_id,
                             f"Diagnostic intent detected. Recruiting the investigation "
                             f"board for {len(inv.factor_keys)} factor(s): "
                             f"{', '.join(inv.factor_keys)}.",
                             target_role="dashboard")
            self._recruit(room_id, ["investigator", "adjudicator"])
            ctx.put_artifact(f"inv:{room_id}:expected", len(inv.factor_keys))
            ctx.put_artifact(f"inv:{room_id}:question", question)
            import uuid
            inv_id = uuid.uuid4().hex[:8]
            inv_dict = inv_to_dict(inv)
            for i, fk in enumerate(inv.factor_keys):
                task = InvestigationTask(
                    envelope=make_envelope(session_id=room_id, from_role="supervisor",
                                           channel=BandConfig.CHANNEL_TASKS,
                                           topic=BandConfig.TOPIC_INVESTIGATION,
                                           to_role="investigator"),
                    investigation_id=inv_id, question=question,
                    comparison=ComparisonSpec(dimension=inv.dimension, a_label=inv.a_label,
                                              b_label=inv.b_label, a_where=inv.a_where,
                                              b_where=inv.b_where, joins=""),
                    factors=[fk], inv=inv_dict)
                lead = (plan_text + "\n\n" if i == 0 else "") + f"Investigate factor '{fk}'."
                await self._handoff(tools, room_id, task, "investigator", lead)
            return

        task = planned.task
        detail = (plan_text + "\n\n"
                  f"Grounded {len(task.selections)} table(s). Generate and run the SQL.")
        await self._handoff(tools, room_id, task, "sql_analyst", detail)

    # ------------------------------------------------------------------
    async def _decide_compliance(self, sql_result, tools, room_id, ctx) -> None:
        """Supervisor decides the SQL plan-compliance retry (Band path)."""
        g = sql_result.grounding
        dims = list(g.planned_dimensions) if g else []
        subtasks = list(g.subtasks) if g else []
        review = CostSentinelAgent().review_compliance_dims(dims, subtasks, sql_result)
        if (not review.compliant) and ctx.sql_revision_count < 1:
            ctx.sql_revision_count += 1
            rev = RevisionRequest(
                envelope=make_envelope(session_id=room_id, from_role="supervisor",
                                       channel=BandConfig.CHANNEL_TASKS,
                                       topic=BandConfig.TOPIC_REVISION, to_role="sql_analyst",
                                       revision_count=ctx.sql_revision_count),
                issue_type=IssueType.OTHER, revision_hint=review.revision_hint,
                previous_sql=sql_result.sql_query, must_succeed=True)
            await self._handoff(tools, room_id, rev, "sql_analyst",
                                f"Plan-compliance: {'; '.join(review.issues)} — please revise.")
            return
        # Compliant (or budget exhausted) -> resume normal flow into governance.
        note = ("Plan-compliant; proceeding to governance review."
                if review.compliant
                else "Compliance budget exhausted; proceeding with caveat.")
        await self._handoff(tools, room_id, sql_result, "guardian", note)

    # ------------------------------------------------------------------
    async def _on_sql_analyst(self, decoded, tools, room_id, ctx) -> None:
        m = decoded.message
        if isinstance(m, SchemaGroundedTask):
            result = self._agent.run(m)
            dims = [c for sel in m.selections for c in (sel.columns or [])]
            # Persist plan grounding in THIS process so a later revision (which
            # arrives as a RevisionRequest without the task) can re-attach it.
            ctx.put_artifact(f"grounding:{room_id}", {
                "dims": dims, "subtasks": list(m.subtasks),
                "nq": m.normalized_question, "pattern": m.query_pattern,
                "complexity": str(getattr(m.complexity, "value", m.complexity)),
            })
            result.grounding = Grounding(
                normalized_question=m.normalized_question,
                query_pattern=m.query_pattern,
                complexity=str(getattr(m.complexity, "value", m.complexity)),
                revision_count=m.envelope.revision_count,
                planned_dimensions=dims, subtasks=list(m.subtasks))
        elif isinstance(m, RevisionRequest):
            result = self._agent.run_revision(m)
            # Re-attach the carried plan grounding so the compliance gate can run
            # again on the revised SQL.
            saved = ctx.get_artifact(f"grounding:{room_id}") or {}
            result.grounding = Grounding(
                normalized_question=saved.get("nq", ""),
                query_pattern=saved.get("pattern", ""),
                complexity=saved.get("complexity", ""),
                revision_count=m.envelope.revision_count,
                planned_dimensions=list(saved.get("dims", [])),
                subtasks=list(saved.get("subtasks", [])))
        else:
            return
        await self._handoff(tools, room_id, result, "cost_sentinel",
                            f"Execution {result.execution_status}, {result.result_row_count} row(s).")

    async def _on_cost_sentinel(self, decoded, tools, room_id, ctx) -> None:
        if not isinstance(decoded.message, SQLResult):
            return
        enriched = self._agent.run(decoded.message)   # cost estimate (unchanged)
        est = enriched.cost_estimate
        detail = (f"Cost reviewed: risk={est.risk_level}, within_budget={est.within_budget}."
                  if est else "Cost estimate unavailable.")
        # Route to the SUPERVISOR, which owns the plan-compliance retry decision.
        # (The Cost Sentinel critiques; the Supervisor decides — no cost->analyst
        # direct loop.)
        await self._handoff(tools, room_id, enriched, "supervisor", detail)

    async def _on_guardian(self, decoded, tools, room_id, ctx) -> None:
        if not isinstance(decoded.message, SQLResult):
            return
        outcome = self._agent.review(decoded.message)
        if isinstance(outcome, RevisionRequest):
            await self._handoff(tools, room_id, outcome, "sql_analyst",
                                f"Challenge: {outcome.issue_type.value} — please revise.")
        elif isinstance(outcome, ValidatedResult):
            outcome.grounding = decoded.message.grounding
            await self._handoff(tools, room_id, outcome, "decision_reporter",
                                f"Verdict pass ({outcome.review_method.value}).")

    async def _on_decision_reporter(self, decoded, tools, room_id, ctx) -> None:
        m = decoded.message
        if isinstance(m, ValidatedResult):
            if m.grounding is not None:
                ctx.normalized_question = m.grounding.normalized_question or ctx.normalized_question
                ctx.query_pattern = m.grounding.query_pattern or ctx.query_pattern
            report: FinalReport = self._agent.run(m)
            record = report.model_dump(mode="json")
            # Carry the AUTHORIZED result through the run-store so the UI never
            # re-executes SQL client-side (which would bypass the Cost Sentinel).
            # This SQL was already cleared by the Sentinel + Guardian upstream, so
            # materializing it here keeps execution inside the governed pipeline.
            rows, cols = self._materialize_authorized(ctx, report.sql_query)
            record["result_rows"] = rows
            record["result_columns"] = cols or record.get("result_columns", [])
            record["audit"] = self._audit_descriptive(report, m)
            record["model_map"] = self._model_map()
            self._save_run(record, room_id)
            await self._post(tools, room_id, _report_text(report), target_role="dashboard")
        elif isinstance(m, BoardDecision):
            import datetime as _dt
            self._save_run({
                "kind": "investigation", "normalized_question": m.question,
                "a_label": m.a_label, "b_label": m.b_label, "gap": m.gap,
                "headline": m.headline, "primary_factor": m.primary_factor,
                "ruled_out": m.ruled_out, "residual_share": m.residual_share,
                "confidence": m.confidence, "recommendation": m.recommendation,
                "conflict_note": "", "findings": m.ranked_factors,
                "model_map": self._model_map(),
                "audit": {
                    "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                    "intent": "diagnostic", "question": m.question,
                    "gap": m.gap, "primary_factor": m.primary_factor,
                    "ranked_factors": m.ranked_factors, "ruled_out": m.ruled_out,
                    "residual_share": m.residual_share, "confidence": m.confidence,
                    "recommendation": m.recommendation,
                },
            }, room_id)
            await self._post(tools, room_id, _board_text(m), target_role="dashboard")

    # ------------------------------------------------------------------
    async def _on_investigator(self, decoded, tools, room_id, ctx) -> None:
        if not isinstance(decoded.message, InvestigationTask):
            return
        task = decoded.message
        factor = task.factors[0]
        if task.inv:
            inv = inv_from_dict(task.inv)
        else:
            inv = investigation.discover(ctx.adapter, task.question,
                                         catalog_path=settings.metric_catalog_path)
        if inv is None:
            return
        finding = FactorInvestigatorAgent(factor).run(ctx.adapter, inv)
        msg = InvestigatorFinding(
            envelope=make_envelope(session_id=room_id, from_role="investigator",
                                   channel=BandConfig.CHANNEL_TASKS,
                                   topic=BandConfig.TOPIC_INVESTIGATION, to_role="adjudicator"),
            investigation_id=task.investigation_id, inv=task.inv,
            question=task.question, total_factors=len(inv.factor_keys), factor=factor,
            factor_label=finding["label"], a_value=finding["a_value"],
            b_value=finding["b_value"], direction="", contribution=0.0,
            explained_share=0.0, verdict="", confidence="",
            evidence=f"{finding['label']}: {finding['a_value']:.2f} vs {finding['b_value']:.2f}")
        await self._handoff(tools, room_id, msg, "adjudicator", f"Finding for '{factor}'.")

    async def _on_adjudicator(self, decoded, tools, room_id, ctx) -> None:
        if not isinstance(decoded.message, InvestigatorFinding):
            return
        f = decoded.message
        inv_id = f.investigation_id

        # Accumulate this finding (process-local, scoped per investigation).
        key = f"inv:{room_id}:{inv_id}:findings"
        store = ctx.get_artifact(key) or {}
        store[f.factor] = {"factor": f.factor, "label": f.factor_label,
                           "a_value": f.a_value, "b_value": f.b_value}
        ctx.put_artifact(key, store)

        # --- JOIN BARRIER (distributed-safe) ---
        # The Band room history is the single source of truth across separate
        # agent processes. Merge findings seen in the room with the local
        # accumulator, and take the join size from the message contract
        # (total_factors) that every investigator stamps onto its finding.
        merged = dict(store)
        merged.update(self._findings_in_history(inv_id))
        expected = f.total_factors or 0
        if not expected and f.inv:
            expected = len(inv_from_dict(f.inv).factor_keys)
        if not expected:
            expected = len(merged)

        if len(merged) < expected:
            logger.info("Adjudicator: join barrier holding (%d/%d findings, inv=%s)",
                        len(merged), expected, inv_id)
            return

        # Idempotency: only the arrival that completes the set adjudicates once.
        done_key = f"inv:{room_id}:{inv_id}:adjudicated"
        if ctx.get_artifact(done_key):
            return
        ctx.put_artifact(done_key, True)
        logger.info("Adjudicator: join complete (%d/%d findings, inv=%s) — adjudicating",
                    len(merged), expected, inv_id)

        question = f.question or (ctx.get_artifact(f"inv:{room_id}:question") or "")
        if f.inv:
            inv = inv_from_dict(f.inv)
        else:
            inv = investigation.discover(ctx.adapter, question,
                                         catalog_path=settings.metric_catalog_path)
        if inv is None:
            return
        record = self._agent.adjudicate(ctx.adapter, inv, merged, narrate=False)
        decision = BoardDecision(
            envelope=make_envelope(session_id=room_id, from_role="adjudicator",
                                   channel=BandConfig.CHANNEL_TASKS,
                                   topic=BandConfig.TOPIC_COMPLETION, to_role="decision_reporter"),
            investigation_id=f.investigation_id, question=question,
            a_label=record["a_label"], b_label=record["b_label"], gap=record["gap"],
            headline=record["headline"], primary_factor=record.get("primary_factor"),
            ranked_factors=record["findings"], ruled_out=record["ruled_out"],
            residual_share=record["residual_share"], confidence=record["confidence"],
            recommendation=record["recommendation"])
        await self._handoff(tools, room_id, decision, "decision_reporter", "Board verdict ready.")

    def _agent_id_for(self, role: str) -> Optional[str]:
        """Look up a role's Band agent UUID from agent_config.yaml (project root)."""
        try:
            import yaml
            p = Path(__file__).resolve().parent.parent / "agent_config.yaml"
            if not p.exists():
                return None
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            aid = str((data.get(role) or {}).get("agent_id", "")).strip()
            return aid if aid and not aid.startswith("<") else None
        except Exception:
            return None

    def _recruit(self, room_id: str, roles: list[str]) -> list[str]:
        """Bring specialist agents into the room on demand (Band-native dynamic
        recruitment via band participant tools). Returns the display names
        actually added. No-ops gracefully when the REST poster or agent ids are
        unavailable — the specialists may already be room participants."""
        recruited: list[str] = []
        if self._poster is None:
            return recruited
        for role in roles:
            aid = self._agent_id_for(role)
            if not aid:
                continue
            try:
                if self._poster.add_agent(room_id, aid):
                    recruited.append(self.display_names.get(role, role))
                    logger.info("[supervisor] recruited @%s into room %s", _slug(role), room_id)
            except Exception as exc:
                logger.warning("recruit %s failed: %s", role, exc)
        return recruited

    def _findings_in_history(self, investigation_id: str) -> dict:
        """Scan the Band room history for InvestigatorFinding payloads belonging
        to this investigation and return {factor: finding}. This is the
        cross-process source of truth for the join barrier — independent of any
        single process's local memory."""
        found: dict = {}
        for item in self._history or []:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content")
            if not content:
                continue
            try:
                dec = payload.decode(content)
            except Exception:
                continue
            msg = getattr(dec, "message", None)
            if isinstance(msg, InvestigatorFinding) and msg.investigation_id == investigation_id:
                found[msg.factor] = {"factor": msg.factor, "label": msg.factor_label,
                                     "a_value": msg.a_value, "b_value": msg.b_value}
        return found

    # ------------------------------------------------------------------
    # Send: REST first (verified mentions), tools.send_message fallback
    # ------------------------------------------------------------------
    async def _handoff(self, tools, room_id, message, next_role: str, detail: str) -> None:
        content = payload.encode(message, prefix=detail)
        await self._post(tools, room_id, content, target_role=next_role)

    async def _post(self, tools, room_id: str, content: str, *, target_role: str) -> None:
        slug = _slug(target_role)
        # 1) verified REST path using this agent's own credentials
        if self._poster is not None:
            try:
                self._poster.ask(room_id, content, target_role_slug=slug)
                logger.info("[%s] -> @%s (REST)", self.role, slug)
                return
            except Exception as exc:
                logger.warning("[%s] REST post to %s failed: %s; trying tools.send_message",
                               self.role, slug, exc)
        # 2) runtime tools.send_message fallback
        handle = await self._resolve_handle(tools, target_role)
        body = (f"@{handle} " if handle else f"@{slug} ") + content
        if _SDK and tools is not None:
            if await self._mention_send(tools, body, handle):
                return
        logger.info("[%s -> %s] %s", self.role, target_role, body[:160])

    async def _known_handles(self, tools) -> set[str]:
        handles: set[str] = set()
        for h in re.findall(r"[\w.\-]+/[\w\-]+", self._participants_msg or ""):
            handles.add(h)


        for attr in ("participants", "get_participants", "list_participants"):
            v = getattr(tools, attr, None)
            if v is None:
                continue
            try:
                items = v() if callable(v) else v
                if inspect.isawaitable(items):
                    items = await items

            except Exception:
                  continue
        for it in (items or []):
            h = (
                getattr(it, "handle", None)
                or (it.get("handle") if isinstance(it, dict) else None)
            )
            if h:
                handles.add(h)
        return handles

    async def _resolve_handle(self, tools, role: str) -> Optional[str]:
        slug = _slug(role)
        for h in await self._known_handles(tools):
            if h.split("/")[-1].strip().lower() == slug:
                return h
        return None

    async def _mention_send(self, tools, body: str, handle: Optional[str]) -> bool:
        mentions = [handle] if handle else []
        attempts = (
            lambda: tools.send_message(body, mentions=mentions),
            lambda: tools.send_message(content=body, mentions=mentions),
            lambda: tools.send_message(body, mentions=[{"handle": handle}] if handle else []),
            lambda: tools.send_message(body, mention_handles=mentions),
        )
        last_err: Optional[Exception] = None
        for call in attempts:
            try:
                await call()
                return True
            except TypeError:
                continue
            except Exception as exc:
                last_err = exc
                continue
        if not QuorumBandAdapter._dumped_api:
            QuorumBandAdapter._dumped_api = True
            try:
                sig = str(inspect.signature(tools.send_message))
            except Exception:
                sig = "<unavailable>"
            logger.error("send_message signature: %s | tools attrs: %s | last error: %s",
                         sig, [a for a in dir(tools) if not a.startswith('_')], last_err)
        return False

    @staticmethod
    def _model_map() -> dict:
        """Which provider/model each role used — part of the audit trail and a
        visible demonstration of cross-model routing."""
        roles = ["supervisor", "sql_analyst", "cost_sentinel", "guardian",
                 "decision_reporter", "adjudicator"]
        out: dict = {}
        for r in roles:
            if r == "cost_sentinel":
                out[r] = {"provider": "deterministic (no LLM)", "model": "\u2014"}
                continue
            try:
                prov = settings.provider_for(r)
                out[r] = {"provider": getattr(prov, "value", str(prov)),
                          "model": settings.model_for(r)}
            except Exception:
                out[r] = {"provider": "unknown", "model": ""}
        return out

    @staticmethod
    def _audit_descriptive(report, validated) -> dict:
        import datetime as _dt
        est = getattr(validated.sql_result, "cost_estimate", None)
        cost: dict = {}
        if est is not None:
            cost = {"engine": est.engine, "risk_level": est.risk_level,
                    "within_budget": est.within_budget,
                    "estimated_rows_scanned": est.estimated_rows_scanned,
                    "estimated_bytes_scanned": est.estimated_bytes_scanned,
                    "estimated_cost_usd": est.estimated_cost_usd,
                    "method": est.method}
        return {
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "intent": "descriptive",
            "question": report.normalized_question,
            "sql_query": report.sql_query,
            "cost_estimate": cost,
            "governance": {
                "verdict": "pass",
                "review_method": getattr(validated.review_method, "value",
                                         str(validated.review_method)),
                "revision_occurred": report.revision_occurred,
            },
            "decision": {
                "finding": report.finding, "implication": report.implication,
                "recommended_action": report.recommended_action,
                "risk_level": report.risk_level,
                "approval_required": report.approval_required,
            },
            "metric_definitions_used": list(report.metric_definitions_used),
            "llm_call_count": report.llm_call_count,
            "latency_seconds": report.total_latency_seconds,
        }

    @staticmethod
    def _materialize_authorized(ctx, sql: str):
        """Execute the already-cleared SQL on the governed adapter and return
        (rows, columns). Returns ([], []) on any issue — the UI then shows no
        data rather than running SQL itself. Execution stays inside the trusted
        pipeline (the Cost Sentinel + Guardian already approved this query)."""
        if not sql or ctx is None or getattr(ctx, "adapter", None) is None:
            return [], []
        try:
            rows, cols = ctx.adapter.execute_query(sql, settings.db_max_rows)
            return [list(r) for r in rows], list(cols or [])
        except Exception:
            logger.debug("authorized materialize skipped", exc_info=True)
            return [], []

    @staticmethod
    def _save_run(record: dict, room_id: str) -> None:
        # 1) Filesystem run-store — works when the API and agents share a disk
        #    (local / co-located runs).
        try:
            from core.run_store import save_run
            save_run(record, room_id=room_id)
        except Exception:
            logger.debug("run-store save skipped", exc_info=True)
        # 2) Shared store — stash the report on the Room row (Postgres) so the
        #    API service, a SEPARATE process/host that cannot read this worker's
        #    filesystem, can render the final result. Keyed by band_room_id.
        try:
            from backend.db.base import SessionLocal
            from backend.db import models as _m
            db = SessionLocal()
            try:
                room = (db.query(_m.Room)
                        .filter_by(band_room_id=room_id)
                        .order_by(_m.Room.created_at.desc()).first())
                if room is not None:
                    ctx = dict(room.shared_context or {})
                    ctx["run_report"] = record
                    room.shared_context = ctx   # reassign so SQLAlchemy tracks the JSON change
                    db.add(room)
                    db.commit()
            finally:
                db.close()
        except Exception:
            logger.debug("run-store DB save skipped", exc_info=True)


def _plan_text(plan) -> str:
    lines = [f"Execution plan — intent={plan.intent}, pattern={plan.query_pattern}:"]
    for s in plan.steps:
        dep = f" (after {', '.join(s.depends_on)})" if s.depends_on else ""
        grp = f" [{s.parallel_group}]" if s.parallel_group else ""
        lines.append(f"  - {s.agent}: {s.action}{dep}{grp}")
    return "\n".join(lines)


def _report_text(r: FinalReport) -> str:
    chart = r.chart_type.value if r.chart_type else "table"
    out = [f"Decision report — {r.result_row_count} rows; chart={chart}; "
           f"{r.llm_call_count} LLM calls; risk={r.risk_level}."]
    if r.finding:
        out.append(f"Finding: {r.finding}")
    if r.implication:
        out.append(f"Implication: {r.implication}")
    if r.recommended_action:
        out.append(f"Recommended action: {r.recommended_action}")
    if r.approval_required:
        out.insert(0, "APPROVAL REQUIRED — high cost/risk; needs human sign-off.")
    return "\n".join(out)


def _board_text(d: BoardDecision) -> str:
    return (f"Board verdict ({d.confidence} confidence): {d.headline}\n{d.recommendation}")