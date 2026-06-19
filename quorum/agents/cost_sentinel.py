"""
agents/cost_sentinel.py — Cost Sentinel agent.

A governance specialist that prices a query's cost/safety BEFORE it influences a
decision, and attaches the estimate so the Compliance Officer (and humans) can
act on it. This is the agent that can say "this query would scan 2 TB ≈ $12 —
that needs approval" before any money is spent.

It is deterministic (no LLM call — stays within the call budget). It consumes
an SQLResult and returns the same SQLResult enriched with a CostEstimate.

In the Band flow it sits between the Data Analyst and the Compliance Officer:
    Data Analyst -> Cost Sentinel -> Compliance Officer
If the Cost Sentinel process is not running, the flow still works (the Data
Analyst hands off directly to the Compliance Officer); the cost estimate is
simply absent. This keeps the system robust.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from agents.base import BaseAgent
from pipeline.models import SQLResult
from pipeline.session_context import context_store
from config import LLMProvider, settings
from core.cost import DEFAULT_BUDGET_USD, estimate_cost

logger = logging.getLogger(__name__)


class CostSentinelAgent(BaseAgent[SQLResult, SQLResult]):
    role = "cost_sentinel"

    def __init__(
        self,
        *,
        telemetry: Optional[Any] = None,
        agent_id: Optional[str] = None,
        budget_usd: float = DEFAULT_BUDGET_USD,
    ) -> None:
        # No LLM provider needed — fully deterministic. We still pass one to
        # satisfy BaseAgent, but never call it.
        super().__init__(
            provider=LLMProvider.OLLAMA,
            model="cost-sentinel-deterministic",
            telemetry=telemetry,
            agent_id=agent_id,
        )
        self._budget = budget_usd

    def _run(self, message: SQLResult) -> SQLResult:
        return self._estimate(message)

    async def _arun(self, message: SQLResult) -> SQLResult:
        return self._estimate(message)

    def _estimate(self, message: SQLResult) -> SQLResult:
        session_id = message.envelope.session_id
        engine = settings.db_type.value if hasattr(settings.db_type, "value") else str(settings.db_type)

        adapter = None
        try:
            ctx = context_store.get(session_id)
            adapter = ctx.adapter
        except Exception:
            adapter = None

        if adapter is None or not message.sql_query.strip():
            logger.info("Cost Sentinel: no adapter/SQL; skipping estimate")
            return message

        est = estimate_cost(
            adapter, message.sql_query, engine=engine, budget_usd=self._budget
        )
        message.cost_estimate = est

        self._emit(session_id, event_type="tool_call", detail={
            "event": "cost_estimated",
            "engine": est.engine,
            "risk_level": est.risk_level,
            "within_budget": est.within_budget,
            "estimated_cost_usd": est.estimated_cost_usd,
            "estimated_rows_scanned": est.estimated_rows_scanned,
            "full_scan_tables": est.full_scan_tables,
            "method": est.method,
        })
        logger.info(
            "Cost Sentinel: engine=%s risk=%s within_budget=%s method=%s",
            est.engine, est.risk_level, est.within_budget, est.method,
        )
        return message

    # ==================================================================
    # NEW — Plan-compliance review (spec: Cost Sentinel responsibility #1).
    # Verifies the generated SQL actually implements the APPROVED PLAN, and
    # repackages the existing cost findings. Returns STRUCTURED FEEDBACK ONLY;
    # the Sentinel never rewrites SQL. The Supervisor decides on any retry.
    # ==================================================================
    def review_compliance(self, task, sql_result: SQLResult):
        """Compare SQL against the approved SchemaGroundedTask + run cost gate.

        `task` is the SchemaGroundedTask the Planner approved. Returns an
        SQLComplianceReview (see pipeline/models.py).
        """
        planned_dims: list[str] = []
        for sel in getattr(task, "selections", []) or []:
            for col in getattr(sel, "columns", []) or []:
                planned_dims.append(str(col))
        subtasks = list(getattr(task, "subtasks", []) or [])
        return self.review_compliance_dims(planned_dims, subtasks, sql_result)

    def review_compliance_dims(self, planned_dimensions, subtasks, sql_result: SQLResult):
        """Dimensions-based compliance check (used by the distributed Band path,
        where the full SchemaGroundedTask object is not in scope but its planned
        dimensions/subtasks are carried on SQLResult.grounding)."""
        from pipeline.models import SQLComplianceReview, make_envelope
        from config import BandConfig

        sql = (sql_result.sql_query or "")
        sql_lower = sql.lower()
        planned_dims = [str(d) for d in (planned_dimensions or [])]
        subtask_blob = " ".join(subtasks or []).lower()

        # --- 1) Plan compliance: every planned dimension must appear in the SQL.
        missing_dimensions: list[str] = []
        for dim in planned_dims:
            d = dim.lower()
            if d and d not in sql_lower:
                if d in subtask_blob or len(planned_dims) <= 6:
                    missing_dimensions.append(dim)

        issues: list[str] = []
        if missing_dimensions:
            issues.append(
                "SQL does not implement planned dimension(s): "
                f"{', '.join(sorted(set(missing_dimensions)))}."
            )

        # --- 2) Cost review (reuse the already-computed estimate if present).
        est = getattr(sql_result, "cost_estimate", None)
        cost_notes: list[str] = []
        cost_flagged = False
        if "select *" in sql_lower:
            cost_flagged = True
            cost_notes.append("SELECT * pulls unnecessary columns.")
        if est is not None:
            if est.risk_level == "high":
                cost_flagged = True
                cost_notes.append(f"High cost risk (engine={est.engine}).")
            if est.within_budget is False:
                cost_flagged = True
                cost_notes.append("Estimated cost exceeds budget.")
            if est.full_scan_tables:
                cost_flagged = True
                cost_notes.append(
                    "Full scan of: " + ", ".join(est.full_scan_tables) + "."
                )

        compliant = not missing_dimensions
        hint = ""
        if not compliant:
            hint = (
                "Regenerate the SQL so it groups/aggregates by the planned "
                f"dimension(s): {', '.join(sorted(set(missing_dimensions)))}."
            )
        elif cost_flagged:
            hint = (
                "Query is plan-compliant but expensive: "
                + " ".join(cost_notes)
                + " Add a selective WHERE filter, drop SELECT *, or aggregate earlier."
            )

        review = SQLComplianceReview(
            envelope=make_envelope(
                session_id=sql_result.envelope.session_id,
                from_role=self.role,                 # "cost_sentinel"
                channel=BandConfig.CHANNEL_TASKS,
                topic=BandConfig.TOPIC_REVIEW,
                to_role="supervisor",
            ),
            compliant=compliant,
            missing_dimensions=sorted(set(missing_dimensions)),
            issues=issues,
            revision_hint=hint,
            cost_flagged=cost_flagged,
            cost_notes=cost_notes,
        )
        self._emit(sql_result.envelope.session_id, event_type="tool_call", detail={
            "role": self.role, "event": "compliance_reviewed",
            "compliant": compliant, "cost_flagged": cost_flagged,
            "missing_dimensions": review.missing_dimensions,
        })
        return review