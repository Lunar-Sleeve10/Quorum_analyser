"""
core/plan.py — ExecutionPlan: the DAG that makes orchestration non-linear and
auditable.

The Planner emits an ExecutionPlan; the Supervisor executes it. The plan is a
first-class artifact: it is posted into the Band room and rendered in the UI, so
an operator can see exactly how the agents divided and sequenced the work — and
how the plan was adapted mid-run (replans / debate rounds append steps).

A step declares the agent that owns it, what it does, what it depends on, and an
optional parallel_group. Independent steps in the same group run concurrently
(the diagnostic factor investigators); a step with multiple dependencies is a
join barrier (the adjudicator).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

StepStatus = str  # pending | running | done | failed | skipped


@dataclass
class PlanStep:
    id: str
    agent: str
    action: str
    depends_on: list[str] = field(default_factory=list)
    parallel_group: Optional[str] = None
    status: StepStatus = "pending"
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "agent": self.agent, "action": self.action,
            "depends_on": list(self.depends_on), "parallel_group": self.parallel_group,
            "status": self.status, "detail": self.detail,
        }


@dataclass
class ExecutionPlan:
    intent: str                     # descriptive | diagnostic | unclear
    question: str
    normalized_question: str = ""
    query_pattern: str = ""
    needs_viz: bool = True
    factors: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ---- mutation -----------------------------------------------------
    def add_step(self, step: PlanStep) -> PlanStep:
        self.steps.append(step)
        return step

    def get(self, step_id: str) -> Optional[PlanStep]:
        return next((s for s in self.steps if s.id == step_id), None)

    def mark(self, step_id: str, status: StepStatus, detail: str = "") -> None:
        s = self.get(step_id)
        if s:
            s.status = status
            if detail:
                s.detail = detail

    def note(self, text: str) -> None:
        self.notes.append(text)

    # ---- views --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "intent": self.intent, "question": self.question,
            "normalized_question": self.normalized_question,
            "query_pattern": self.query_pattern, "needs_viz": self.needs_viz,
            "factors": list(self.factors), "notes": list(self.notes),
            "steps": [s.to_dict() for s in self.steps],
        }

    def mermaid(self) -> str:
        """Render the DAG as a Mermaid flowchart (used by the UI)."""
        lines = ["flowchart TD"]
        for s in self.steps:
            label = f"{s.agent}\\n{s.action}"
            shape = f'{s.id}["{label}"]'
            lines.append(f"    {shape}")
        for s in self.steps:
            for dep in s.depends_on:
                lines.append(f"    {dep} --> {s.id}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Templated plan construction (hybrid: LLM supplies intent/grounding, the DAG
# itself is assembled from these vetted templates)
# ---------------------------------------------------------------------------

def descriptive_plan(question: str, normalized: str, pattern: str) -> ExecutionPlan:
    plan = ExecutionPlan(intent="descriptive", question=question,
                         normalized_question=normalized, query_pattern=pattern)
    plan.add_step(PlanStep("plan", "Planner", "classify intent + ground schema"))
    plan.add_step(PlanStep("plan_review", "Plan Guardian",
                           "review plan completeness (pre-execution)",
                           depends_on=["plan"]))
    plan.add_step(PlanStep("sql", "SQL Analyst", "generate + execute SQL",
                           depends_on=["plan_review"]))
    plan.add_step(PlanStep("cost", "Cost Sentinel", "pre-execution cost / safety",
                           depends_on=["sql"]))
    plan.add_step(PlanStep("compliance", "Cost Sentinel",
                           "verify SQL implements the approved plan",
                           depends_on=["sql", "cost"]))
    plan.add_step(PlanStep("review", "Governance Guardian",
                           "compliance + correctness + viz decision",
                           depends_on=["compliance"]))
    plan.add_step(PlanStep("report", "Decision Reporter",
                           "finding -> implication -> action", depends_on=["review"]))
    return plan


def diagnostic_plan(question: str, normalized: str, factors: list[str]) -> ExecutionPlan:
    plan = ExecutionPlan(intent="diagnostic", question=question,
                         normalized_question=normalized, query_pattern="diagnostic",
                         factors=list(factors))
    plan.add_step(PlanStep("plan", "Planner", "classify intent + resolve comparison"))
    inv_ids = []
    for f in factors:
        sid = f"inv_{f}"
        inv_ids.append(sid)
        plan.add_step(PlanStep(sid, "Investigator", f"measure factor: {f}",
                               depends_on=["plan"], parallel_group="investigate"))
    plan.add_step(PlanStep("adjudicate", "Adjudicator",
                           "join findings + attribute gap", depends_on=inv_ids))
    plan.add_step(PlanStep("report", "Decision Reporter", "board verdict + recommendation",
                           depends_on=["adjudicate"]))
    return plan