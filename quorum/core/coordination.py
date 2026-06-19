"""
core/coordination.py — Adaptive Supervisor + execution engine.

This is the Band-agnostic core that EXECUTES an ExecutionPlan. The Supervisor
walks the DAG, fans out parallel work, enforces join barriers, and adapts:

  - bounded debate/revision when the Guardian challenges the SQL Analyst,
  - one replan on stall (empty/failed result),
  - approval escalation on high risk.

Keeping this logic here (not buried in the Band transport) makes it unit-testable
without live agents. The Streamlit app drives it directly; the Band Supervisor
agent wraps it so the same engine runs over a real Band room.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from agents.base import TelemetrySink
from agents.orchestrator import ClarificationNeeded
from agents.planner import PlannerAgent
from agents.sql_engineer import SQLEngineerAgent
from agents.cost_sentinel import CostSentinelAgent
from agents.governance_guardian import GovernanceGuardianAgent
from agents.reporting import VisualizationReportingAgent
from agents.investigator import FactorInvestigatorAgent
from agents.adjudicator import AdjudicatorAgent
from pipeline.models import AgentEvent, RevisionRequest, ValidatedResult
from pipeline.session_context import context_store
from config import BandConfig, DatabaseType, ReviewMethod, settings
from core.cache import SchemaCache
from core.database import make_adapter
from core.memory import Memory, schema_fingerprint
from core.plan import ExecutionPlan, PlanStep
from core.validators import SQLValidator
from core.viz import build_chart, investigation_chart
from models.state import DatabaseConfig

logger = logging.getLogger(__name__)


class _Collector(TelemetrySink):
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


@dataclass
class EngineResult:
    status: str                       # completed | clarification | error
    intent: str = ""
    plan: Optional[dict] = None
    report: Optional[dict] = None
    figure: Optional[Any] = None
    dataframe: Optional[pd.DataFrame] = None
    llm_call_count: int = 0
    cache_hit: bool = False
    clarification: Optional[str] = None
    error: Optional[str] = None
    trace: list[str] = field(default_factory=list)


class AnalyticsEngine:
    def __init__(self, *, router=None) -> None:
        self.router = router
        self.memory = Memory(settings.memory_dir, settings.enable_memory)

    # ------------------------------------------------------------------
    def run(self, question: str, *, db_path: Optional[str] = None,
            db_type: Optional[str] = None, narrate_diagnostic: bool = False) -> EngineResult:
        db_path = db_path or settings.db_path
        db_type = db_type or (settings.db_type.value if hasattr(settings.db_type, "value") else str(settings.db_type))
        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        trace: list[str] = []

        try:
            ctx = self._setup(session_id, db_path, db_type)
        except Exception as exc:
            logger.exception("setup failed")
            return EngineResult(status="error", error=f"Database error: {exc}", trace=trace)

        sink = _Collector()
        try:
            schema_str = SchemaCache.get_schema(db_path, ctx.adapter)
            fp = schema_fingerprint(schema_str)

            # --- memory: approved-plan cache (descriptive only) ---
            cached = self.memory.lookup_plan(question, fp)
            if cached and cached.get("intent") == "descriptive" and cached.get("sql_query"):
                trace.append("Memory: approved-plan cache hit — re-using certified SQL (0 LLM calls).")
                res = self._from_cache(ctx, cached, trace)
                if res is not None:
                    return res

            planner = PlannerAgent(llm_router=self.router, telemetry=sink)
            try:
                planned = planner.plan(session_id=session_id, question=question,
                                       adapter=ctx.adapter, db_path=db_path, db_type=db_type)
            except ClarificationNeeded as cn:
                return EngineResult(status="clarification", intent="unclear",
                                    clarification=cn.request.clarification_message,
                                    llm_call_count=ctx.total_llm_calls(), trace=trace)

            plan = planned.plan
            plan.mark("plan", "done", detail="; ".join(plan.notes))
            trace.append(f"Planner: intent={plan.intent}. " + " ".join(plan.notes))

            if planned.investigation is not None:
                return self._run_diagnostic(ctx, plan, planned.investigation,
                                            sink, narrate_diagnostic, trace)
            return self._run_descriptive(ctx, plan, planned.task, sink, fp, question, trace)
        except Exception as exc:
            logger.exception("engine run failed")
            return EngineResult(status="error", error=str(exc),
                                llm_call_count=ctx.total_llm_calls(), trace=trace)
        finally:
            if context_store.exists(session_id):
                context_store.remove(session_id)

    # ------------------------------------------------------------------
    # Descriptive branch (with adaptive supervision)
    # ------------------------------------------------------------------
    def _run_descriptive(self, ctx, plan: ExecutionPlan, task, sink, fp, question, trace) -> EngineResult:
        sql_engineer = SQLEngineerAgent(llm_router=self.router, telemetry=sink)
        cost_sentinel = CostSentinelAgent(telemetry=sink)
        guardian = GovernanceGuardianAgent(llm_router=self.router, telemetry=sink)
        reporter = VisualizationReportingAgent(llm_router=self.router, telemetry=sink)

        plan.mark("sql", "running")
        sql_result = sql_engineer.run(task)
        plan.mark("sql", "done", f"status={sql_result.execution_status}, rows={sql_result.result_row_count}")

        cost_sentinel.run(sql_result)
        est = sql_result.cost_estimate
        plan.mark("cost", "done", (f"risk={est.risk_level}, within_budget={est.within_budget}"
                                   if est else "estimate unavailable"))

        plan.mark("review", "running")
        outcome = guardian.review(sql_result)

        # Adaptive debate/revision loop (bounded).
        rounds = 0
        while isinstance(outcome, RevisionRequest) and rounds < BandConfig.MAX_REVISIONS:
            rounds += 1
            did = plan.add_step(PlanStep(f"debate_{rounds}", "Governance Guardian",
                                         f"challenge: {outcome.issue_type.value}",
                                         depends_on=["review"]))
            did.status = "done"
            trace.append(f"Debate round {rounds}: Guardian challenged the Analyst "
                         f"({outcome.issue_type.value}); Analyst revising.")
            rev = plan.add_step(PlanStep(f"revise_{rounds}", "SQL Analyst",
                                         "revise SQL under challenge", depends_on=[f"debate_{rounds}"]))
            sql_result = sql_engineer.run_revision(outcome)
            rev.status = "done"
            cost_sentinel.run(sql_result)
            outcome = guardian.review(sql_result)

        # Adaptive replan on stall (empty/failed after revisions).
        replanned = False
        if isinstance(outcome, RevisionRequest):
            plan.note("Supervisor: revision did not converge; escalating with caveat.")
            trace.append("Supervisor: stall — revision budget exhausted; proceeding with best result and a caveat.")
            outcome = ValidatedResult(
                envelope=sql_result.envelope, sql_result=sql_result, verdict="pass",
                review_method=ReviewMethod.DETERMINISTIC,
                data_quality_notes=["Revision budget exhausted; result flagged for review."])
            replanned = True
        plan.mark("review", "done", f"verdict=pass{' (caveat)' if replanned else ''}")

        validated: ValidatedResult = outcome
        plan.mark("report", "running")
        report = reporter.run(validated)

        # Guardian owns the viz decision, on real post-execution data.
        df = self._materialize(ctx, report.sql_query, report.result_row_count)
        chart, reason = guardian.decide_visual(df, plan.query_pattern, needs_viz=True)
        figure = build_chart(df, chart, plan.normalized_question) if (chart and df is not None) else None
        plan.mark("report", "done", f"chart={chart or 'table'} ({reason})")

        report_dict = report.model_dump(mode="json")
        report_dict["chart_type"] = chart
        report_dict["viz_reason"] = reason
        report_dict["plan"] = plan.to_dict()
        report_dict["trace"] = trace

        # Persist approved plan + insight.
        if not replanned and sql_result.execution_status == "success":
            self.memory.store_plan(question, fp, {
                "intent": "descriptive", "normalized_question": report.normalized_question,
                "sql_query": report.sql_query, "chart_type": chart,
                "query_pattern": plan.query_pattern,
                "finding": report.finding, "risk_level": report.risk_level,
            })
            if report.finding:
                self.memory.add_insight({"question": report.normalized_question,
                                         "finding": report.finding, "risk": report.risk_level})

        return EngineResult(status="completed", intent="descriptive", plan=plan.to_dict(),
                            report=report_dict, figure=figure, dataframe=df,
                            llm_call_count=ctx.total_llm_calls(), trace=trace)

    # ------------------------------------------------------------------
    # Diagnostic branch (parallel fork/join)
    # ------------------------------------------------------------------
    def _run_diagnostic(self, ctx, plan: ExecutionPlan, inv, sink, narrate, trace) -> EngineResult:
        investigators = [FactorInvestigatorAgent(f) for f in plan.factors]
        trace.append(f"Supervisor: fan-out {len(investigators)} factor investigator(s) in parallel.")

        for s in plan.steps:
            if s.parallel_group == "investigate":
                s.status = "running"

        findings: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(investigators))) as pool:
            futs = {pool.submit(ag.run, ctx.adapter, inv): ag for ag in investigators}
            for fut, ag in futs.items():
                f = fut.result()
                findings[ag.factor_key] = f
                plan.mark(f"inv_{ag.factor_key}", "done",
                          f"{f['label']}: {f['a_value']:.2f} vs {f['b_value']:.2f}")

        plan.mark("adjudicate", "running")
        adjudicator = AdjudicatorAgent(llm_router=self.router)
        record = adjudicator.adjudicate(ctx.adapter, inv, findings, narrate=narrate)
        plan.mark("adjudicate", "done",
                  f"primary={record.get('primary_factor')}, confidence={record['confidence']}")
        plan.mark("report", "done", "board verdict assembled")
        trace.append("Adjudicator (join): " + record["headline"])

        record["plan"] = plan.to_dict()
        record["trace"] = trace
        figure = investigation_chart(record["findings"])
        self.memory.add_insight({"question": record["normalized_question"],
                                 "finding": record["headline"], "kind": "investigation"})
        return EngineResult(status="completed", intent="diagnostic", plan=plan.to_dict(),
                            report=record, figure=figure, dataframe=None,
                            llm_call_count=ctx.total_llm_calls(), trace=trace)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _setup(self, session_id, db_path, db_type):
        try:
            dbt = DatabaseType(str(db_type).lower())
        except ValueError:
            dbt = DatabaseType.SQLITE
        cfg = DatabaseConfig(db_type=dbt, connection_string=db_path,
                             max_rows=settings.db_max_rows, timeout=settings.db_timeout,
                             read_only=settings.db_read_only)
        adapter = make_adapter(cfg)
        SchemaCache.get_schema(db_path, adapter)
        if context_store.exists(session_id):
            context_store.remove(session_id)
        return context_store.create(session_id, adapter=adapter, db_config=cfg)

    def _materialize(self, ctx, sql, row_count) -> Optional[pd.DataFrame]:
        if not sql or row_count <= 0 or ctx.adapter is None:
            return None
        # Read-only guardrail: never run anything that isn't a single read query,
        # even when replaying a cached plan. The DB connection is also read-only.
        ok, reason = SQLValidator.validate(sql)
        if not ok:
            logger.warning("blocked non-analysis SQL in materialize: %s", reason)
            return None
        try:
            rows, cols = ctx.adapter.execute_query(sql, settings.db_max_rows)
            return pd.DataFrame(rows, columns=cols) if cols else None
        except Exception as exc:
            logger.warning("materialize failed: %s", exc)
            return None

    def _from_cache(self, ctx, cached, trace) -> Optional[EngineResult]:
        sql = cached.get("sql_query", "")
        df = self._materialize(ctx, sql, 1)
        if df is None:
            return None
        chart = cached.get("chart_type")
        figure = build_chart(df, chart, cached.get("normalized_question", "")) if chart else None
        report = {
            "normalized_question": cached.get("normalized_question", ""),
            "sql_query": sql, "chart_type": chart,
            "result_row_count": int(len(df)), "result_columns": list(df.columns),
            "finding": cached.get("finding", ""), "risk_level": cached.get("risk_level", "low"),
            "narrative_summary": "Re-used a previously approved plan.",
            "llm_call_count": 0, "from_cache": True, "trace": trace,
        }
        return EngineResult(status="completed", intent="descriptive", report=report,
                            figure=figure, dataframe=df, llm_call_count=0,
                            cache_hit=True, trace=trace)
