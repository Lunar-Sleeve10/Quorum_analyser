"""
agents/plan_guardian.py — Plan Governance Guardian (PRE-execution plan reviewer).

IMPORTANT NAMING NOTE
---------------------
The spec calls this component the "Governance Guardian". That display name is
ALREADY taken by ``agents/governance_guardian.py``, which is a POST-execution
result reviewer + visualization decider (role="guardian"). To avoid breaking
that certified component, this new PRE-execution plan reviewer is introduced
under a distinct role ("plan_guardian") / display name ("Plan Guardian").

Responsibility (per spec)
-------------------------
Critique the Planner's output BEFORE execution begins. It verifies whether the
plan:
  * correctly understood the user's question,
  * includes the required metrics,
  * includes the required dimensions,
  * includes the required factors,
  * is complete and appropriate for the business question.

It returns STRUCTURED FEEDBACK only. It MUST NOT rewrite the plan — the Planner
remains the owner of planning. The Supervisor decides whether to ask the Planner
to re-plan; this agent never loops back to the Planner directly.

Budget
------
Deterministic-first (zero LLM cost). A single, optional LLM completeness
critique runs ONLY when the deterministic pass is inconclusive AND the Supervisor
still has plan-revision budget, mirroring the Reviewer's pattern.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from pipeline.models import (
    PlanReview,
    SchemaGroundedTask,
    make_envelope,
)
from pipeline.session_context import context_store
from config import BandConfig, LLMProvider, settings
from core.llm_router import LLMError, LLMRouter
from core.parsers import LLMResponseParser

logger = logging.getLogger(__name__)

# Question shapes that, if present, imply specific plan obligations.
_COMPARATIVE_HINTS = ("vs", "versus", "compared", "compare", "between")
_CAUSAL_HINTS = ("why", "decline", "declined", "drop", "dropped", "cause",
                 "reason", "driver", "increase", "decrease", "underperform")
_RANKING_HINTS = ("top", "bottom", "highest", "lowest", "rank", "best", "worst")
_BREAKDOWN_HINTS = ("by ", "per ", "across", "breakdown", "split", "segment")

# For causal "why did <metric> change" questions, a single A-vs-B comparison is
# usually insufficient; the plan should consider several explanatory factors.
_MIN_DIAGNOSTIC_FACTORS = 2


class PlanGovernanceGuardianAgent:
    """Pre-execution plan critic. Produces feedback; never edits the plan."""

    role = "plan_guardian"

    def __init__(self, *, llm_router: Optional[LLMRouter] = None,
                 telemetry: Optional[Any] = None) -> None:
        self.router = llm_router
        self.telemetry = telemetry
        # Mirror the SQL Engineer / Reviewer provider selection so cross-model
        # routing still applies; falls back to the reviewer's provider/model.
        self._provider: LLMProvider = settings.reviewer_provider
        self._model: str = settings.reviewer_model

    # ------------------------------------------------------------------
    # Public API — the Supervisor calls this. Returns a PlanReview (pass|revise).
    # The `plan` is the live ExecutionPlan; `task` is the SchemaGroundedTask for
    # the descriptive branch (None on the diagnostic branch). `factors` is the
    # resolved diagnostic factor list (empty for descriptive).
    # ------------------------------------------------------------------
    def review(
        self,
        *,
        session_id: str,
        question: str,
        intent: str,
        query_pattern: str,
        task: Optional[SchemaGroundedTask] = None,
        factors: Optional[list[str]] = None,
        allow_llm: bool = True,
    ) -> PlanReview:
        factors = factors or []
        det = self._deterministic_review(
            question=question, intent=intent, query_pattern=query_pattern,
            task=task, factors=factors,
        )

        verdict = det["verdict"]
        # Only spend an LLM call when deterministic checks did not already decide
        # a revision and the result is flagged as inconclusive.
        if verdict == "pass" and det.get("inconclusive") and allow_llm and self._llm_available():
            llm = self._llm_review(session_id, question, intent, query_pattern, task, factors)
            if llm is not None and llm["verdict"] == "revise":
                det = llm
                verdict = "revise"

        review = self._make_review(session_id, det)
        self._emit(session_id, detail={
            "role": self.role, "decision": verdict,
            "missing_dimensions": review.missing_dimensions,
            "missing_factors": review.missing_factors,
            "missing_metrics": review.missing_metrics,
        })
        return review

    # ------------------------------------------------------------------
    # Deterministic critique (no LLM). Heuristic but conservative: it raises
    # concerns, it never edits the plan.
    # ------------------------------------------------------------------
    def _deterministic_review(
        self, *, question: str, intent: str, query_pattern: str,
        task: Optional[SchemaGroundedTask], factors: list[str],
    ) -> dict:
        q = (question or "").lower()
        issues: list[str] = []
        missing_dimensions: list[str] = []
        missing_factors: list[str] = []
        missing_metrics: list[str] = []
        inconclusive = False

        selections = list(task.selections) if task is not None else []
        subtasks = list(task.subtasks) if task is not None else []
        selected_cols = {
            c.lower() for sel in selections for c in getattr(sel, "columns", []) or []
        }

        # 1) Did the plan understand the question at all? (descriptive branch
        #    must have grounded at least one table/column).
        if intent == "descriptive" and not selections:
            issues.append("Plan grounded no tables/columns; the question may not "
                          "have been understood.")

        # 2) Causal questions: a thin plan (no diagnostic decomposition / too few
        #    factors) likely misses explanatory dimensions. This is the spec's
        #    "Why did revenue decline in Q2?" case.
        is_causal = any(h in q for h in _CAUSAL_HINTS)
        if is_causal:
            if intent != "diagnostic":
                issues.append("Question is causal ('why/decline/driver') but the "
                              "plan is descriptive — it likely omits explanatory "
                              "breakdowns (e.g. region, product mix, segment, price).")
                missing_dimensions.extend(self._suggest_dimensions(q))
            elif len(factors) < _MIN_DIAGNOSTIC_FACTORS:
                issues.append(f"Diagnostic plan considers only {len(factors)} "
                              "factor(s); a 'why' question usually needs several "
                              "candidate drivers.")
                missing_factors.extend(self._suggest_dimensions(q))

        # 3) Ranking questions need an ordering dimension + a measure.
        if any(h in q for h in _RANKING_HINTS) and intent == "descriptive":
            if not selected_cols:
                inconclusive = True
            # cannot fully verify ORDER BY pre-SQL; defer to Cost Sentinel/Reviewer.

        # 4) Explicit breakdown ("revenue by region and product") — every named
        #    dimension should be represented in the grounded columns OR subtasks.
        named = self._named_dimensions(q)
        if named and task is not None:
            covered_blob = " ".join(subtasks).lower() + " " + " ".join(selected_cols)
            for dim in named:
                if dim not in covered_blob:
                    missing_dimensions.append(dim)
            if missing_dimensions:
                issues.append("Question names dimension(s) the plan does not "
                              f"clearly cover: {', '.join(sorted(set(missing_dimensions)))}.")

        # 5) Metric presence: if the question names a metric word, make sure the
        #    plan references it somewhere (column or subtask). Heuristic only.
        metric = self._named_metric(q)
        if metric and task is not None:
            blob = " ".join(subtasks).lower() + " " + " ".join(selected_cols)
            if metric not in blob:
                missing_metrics.append(metric)
                inconclusive = True  # let the LLM confirm before hard-rejecting.

        verdict = "revise" if issues else "pass"
        return {
            "verdict": verdict,
            "issues": issues,
            "missing_dimensions": sorted(set(missing_dimensions)),
            "missing_factors": sorted(set(missing_factors)),
            "missing_metrics": sorted(set(missing_metrics)),
            "inconclusive": inconclusive and verdict == "pass",
            "method": "deterministic",
        }

    # ------------------------------------------------------------------
    # Optional single LLM completeness critique
    # ------------------------------------------------------------------
    def _llm_available(self) -> bool:
        if self.router is None:
            return False
        if self._provider == LLMProvider.OLLAMA:
            return True
        return bool(settings.api_key_for(self._provider))

    def _build_prompt(self, question: str, intent: str, query_pattern: str,
                      task: Optional[SchemaGroundedTask], factors: list[str]) -> str:
        if task is not None:
            grounded = "; ".join(
                f"{s.table}({', '.join(s.columns)})" for s in task.selections
            )
            sub = "; ".join(task.subtasks)
        else:
            grounded = f"diagnostic factors: {', '.join(factors)}"
            sub = ""
        return f"""You are a governance reviewer checking whether an analytics PLAN
is complete BEFORE any SQL runs. You do NOT rewrite the plan; you only critique.

Business question: {question}
Plan intent: {intent}; pattern: {query_pattern}
Plan grounding: {grounded}
Subtasks: {sub}

Decide if the plan is complete and appropriate for the question. If the question
implies breakdowns (region, product, segment, time, price) or multiple causal
factors that the plan omits, verdict is "revise" and list what is missing.
Otherwise verdict is "pass".

Return ONLY this JSON:
{{"verdict": "pass", "missing_dimensions": [], "missing_factors": [],
"missing_metrics": [], "critique": ""}}"""

    def _llm_review(self, session_id: str, question: str, intent: str,
                    query_pattern: str, task: Optional[SchemaGroundedTask],
                    factors: list[str]) -> Optional[dict]:
        try:
            resp = self.router.complete(
                provider=self._provider, model=self._model,
                prompt=self._build_prompt(question, intent, query_pattern, task, factors),
            )
        except LLMError as exc:
            logger.warning("Plan Guardian LLM call failed, defaulting to pass: %s", exc)
            return None
        try:
            ctx = context_store.get(session_id)
            ctx.record_llm_call(agent=self.role, model=getattr(resp, "model", self._model),
                                tokens_in=getattr(resp, "tokens_in", 0),
                                tokens_out=getattr(resp, "tokens_out", 0),
                                latency_ms=getattr(resp, "latency_ms", 0.0))
        except Exception:
            pass

        parsed = LLMResponseParser.extract_json(getattr(resp, "content", "") or "")
        if not parsed:
            return None
        verdict = str(parsed.get("verdict", "pass")).lower().strip()
        if verdict != "revise":
            return {"verdict": "pass", "issues": [], "missing_dimensions": [],
                    "missing_factors": [], "missing_metrics": [], "method": "llm_assisted"}
        critique = str(parsed.get("critique", "")).strip() or "Plan is incomplete."
        return {
            "verdict": "revise",
            "issues": [critique],
            "missing_dimensions": [str(x) for x in parsed.get("missing_dimensions", [])],
            "missing_factors": [str(x) for x in parsed.get("missing_factors", [])],
            "missing_metrics": [str(x) for x in parsed.get("missing_metrics", [])],
            "method": "llm_assisted",
        }

    # ------------------------------------------------------------------
    # Heuristic helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _suggest_dimensions(q: str) -> list[str]:
        """Standard explanatory dimensions to consider for a revenue/sales 'why'."""
        suggestions = []
        for dim in ("region", "product", "segment", "customer", "price", "channel", "time"):
            if dim not in q:
                suggestions.append(dim)
        return suggestions[:4]

    @staticmethod
    def _named_dimensions(q: str) -> list[str]:
        """Extract explicit 'by X' / 'per X' dimension tokens from the question."""
        dims: list[str] = []
        for m in re.finditer(r"\b(?:by|per)\s+([a-zA-Z_]+)", q):
            dims.append(m.group(1).strip())
        return dims

    @staticmethod
    def _named_metric(q: str) -> str:
        for metric in ("revenue", "sales", "profit", "margin", "churn", "count",
                       "orders", "cost", "spend", "conversion"):
            if metric in q:
                return metric
        return ""

    # ------------------------------------------------------------------
    # Output + telemetry
    # ------------------------------------------------------------------
    def _make_review(self, session_id: str, det: dict) -> PlanReview:
        return PlanReview(
            envelope=make_envelope(
                session_id=session_id,
                from_role=self.role,            # "plan_guardian"
                channel=BandConfig.CHANNEL_TASKS,
                topic=BandConfig.TOPIC_REVIEW,
                to_role="supervisor",           # feedback goes to the Supervisor
            ),
            verdict=det["verdict"],
            issues=det.get("issues", []),
            missing_metrics=det.get("missing_metrics", []),
            missing_dimensions=det.get("missing_dimensions", []),
            missing_factors=det.get("missing_factors", []),
            review_method=det.get("method", "deterministic"),
        )

    def _emit(self, session_id: str, *, detail: dict) -> None:
        if self.telemetry is None:
            return
        try:
            from pipeline.models import AgentEvent
            self.telemetry.emit(AgentEvent(
                envelope=make_envelope(
                    session_id=session_id, from_role=self.role,
                    channel=BandConfig.CHANNEL_TELEMETRY, topic=BandConfig.TOPIC_CONTROL,
                ),
                event_type="tool_call", role=self.role, detail=detail,
            ))
        except Exception:
            logger.debug("plan guardian telemetry skipped", exc_info=True)