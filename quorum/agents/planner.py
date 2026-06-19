"""
agents/planner.py — Planner (strategic planning agent).

The Planner does the thinking: it classifies intent, grounds the question in the
schema/semantic layer, and emits an ExecutionPlan (DAG) for the Supervisor to
run. It reuses the certified grounding logic (clarity gate + table/column
verification) and adds the descriptive-vs-diagnostic decision.

Intent classification costs ZERO extra LLM calls: the diagnostic gate is the
deterministic causal/comparative classifier in core.investigation, applied to
the same grounding pass. So planning stays inside one LLM call (the grounding),
or zero on a memory cache hit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from agents.orchestrator import ClarificationNeeded, QueryOrchestratorAgent
from pipeline.models import SchemaGroundedTask, UserQuery, make_envelope
from config import BandConfig, settings
from core import investigation
from core.investigation import Investigation
from core.plan import ExecutionPlan, descriptive_plan, diagnostic_plan

logger = logging.getLogger(__name__)


@dataclass
class PlanResult:
    plan: ExecutionPlan
    task: Optional[SchemaGroundedTask] = None       # set for descriptive
    investigation: Optional[Investigation] = None    # set for diagnostic


class PlannerAgent:
    role = "planner"

    def __init__(self, *, llm_router=None, telemetry=None) -> None:
        self._orchestrator = QueryOrchestratorAgent(llm_router=llm_router, telemetry=telemetry)

    @property
    def telemetry(self):
        return self._orchestrator.telemetry

    @telemetry.setter
    def telemetry(self, value) -> None:
        self._orchestrator.telemetry = value

    def plan(self, *, session_id: str, question: str, adapter, db_path: str,
             db_type: str, clarification_count: int = 0,
             plan_feedback: str = "") -> PlanResult:
        # Diagnostic gate first — deterministic, no LLM. If it resolves a
        # comparison, we take the investigation branch without grounding SQL.
        inv = None
        if investigation.is_diagnostic(question):
            try:
                inv = investigation.discover(
                    adapter, question, catalog_path=settings.metric_catalog_path,
                    router=self._orchestrator.router)
            except Exception as exc:
                logger.warning("diagnostic discovery failed: %s", exc)
                inv = None
        if inv is not None:
            factors = inv.factor_keys[:BandConfig.MAX_FACTORS]
            plan = diagnostic_plan(question, question, factors)
            plan.note(f"Comparison resolved: {inv.a_label} vs {inv.b_label} "
                      f"on '{inv.dimension}' (metric={inv.metric}).")
            return PlanResult(plan=plan, investigation=inv)

        # Descriptive branch — ground via the orchestrator (1 LLM call).
        # When the Supervisor supplies reviewer feedback (plan_feedback), fold it
        # into the question so the Planner — which remains the OWNER of the plan —
        # can broaden its grounding. Empty feedback ⇒ identical to before.
        grounded_question = question if not plan_feedback else (
            f"{question}\n\n[Reviewer feedback to address: {plan_feedback}]"
        )
        user_query = UserQuery(
            envelope=make_envelope(
                session_id=session_id, from_role="user",
                channel=BandConfig.CHANNEL_CONTROL, topic=BandConfig.TOPIC_CONTROL,
                to_role="orchestrator"),
            question=grounded_question, db_path=db_path, db_type=db_type,
            clarification_count=clarification_count,
        )
        task = self._orchestrator.run(user_query)   # may raise ClarificationNeeded
        plan = descriptive_plan(question, task.normalized_question, task.query_pattern)
        plan.note(f"{len(task.selections)} table(s) grounded; pattern={task.query_pattern}.")
        return PlanResult(plan=plan, task=task)