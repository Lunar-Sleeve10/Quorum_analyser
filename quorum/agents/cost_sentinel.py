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
