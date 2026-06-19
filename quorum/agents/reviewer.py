"""
agents/reviewer.py — Insights & Compliance Reviewer agent.

Third agent in the flow. Consumes the SQL Engineer's SQLResult and produces
either a RevisionRequest (send back to the SQL Engineer, at most once per
session) or a ValidatedResult (forward to the Reporting Agent).

Deterministic-first: a sequence of cheap pandas-free checks runs before any
LLM call -- execution status, empty result, ranking-without-ORDER-BY,
top-N-without-LIMIT, and null ratio. These catch the common real failures with
zero token cost. An LLM call is made ONLY when the deterministic checks pass but
the result is semantically ambiguous (and a revision is still available),
keeping the agent within a maximum of one LLM call.

Revision budget: the Reviewer owns SessionContext.revision_count and enforces a
hard cap of BandConfig.MAX_REVISIONS (1). Once the cap is reached, the Reviewer
passes the result regardless, attaching a caveat to data_quality_notes -- it can
never request a second revision.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from agents.base import BaseAgent
from pipeline.models import (
    BandMessage,
    RevisionRequest,
    SQLResult,
    ValidatedResult,
    make_envelope,
)
from pipeline.session_context import SessionContext, context_store
from config import BandConfig, IssueType, LLMProvider, ReviewMethod, settings
from core.llm_router import LLMError, LLMRouter
from core.parsers import LLMResponseParser

logger = logging.getLogger(__name__)

# The Reviewer genuinely produces one of two message types.
ReviewOutcome = ValidatedResult | RevisionRequest

_RANKING_KEYWORDS = ("top", "bottom", "highest", "lowest", "rank", "ranked")
_TOPN_PATTERN = re.compile(r"\b(?:top|bottom)\s+\d+", re.IGNORECASE)
_NULL_HEAVY_THRESHOLD = 0.5
_COST_CHALLENGE_ROWS = 50_000   # full-scan rows that trigger a cost challenge


@dataclass(slots=True)
class _Review:
    """Internal outcome of a review stage."""
    verdict: str                       # "pass" | "revise"
    issue_type: Optional[IssueType] = None
    revision_hint: str = ""
    notes: list[str] = field(default_factory=list)
    conclusive: bool = True            # False => pass but eligible for LLM check


class InsightsComplianceReviewerAgent(BaseAgent[SQLResult, BandMessage]):
    role = "reviewer"

    def __init__(
        self,
        *,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        llm_router: Optional[LLMRouter] = None,
        telemetry: Optional[Any] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            provider=provider or settings.reviewer_provider,
            model=model or settings.reviewer_model,
            llm_router=llm_router,
            telemetry=telemetry,
            agent_id=agent_id,
        )

    # ------------------------------------------------------------------
    # Sync / async entry points
    # ------------------------------------------------------------------

    def _run(self, message: SQLResult) -> ReviewOutcome:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)
        can_revise = self._can_revise(message, ctx)

        det = self._deterministic_review(message, ctx)

        if det.verdict == "revise":
            return self._resolve_revision(message, ctx, det, can_revise)

        # Cost challenge: a clean-but-expensive query is sent back to be
        # re-planned toward a cheaper one (visible debate beat).
        cost_rev = self._cost_challenge_review(message)
        if cost_rev is not None and can_revise:
            return self._make_revision(message, ctx, cost_rev)

        # Deterministic verdict is "pass".
        if det.conclusive or not can_revise or not self._llm_available():
            return self._make_validated(message, det.notes, ReviewMethod.DETERMINISTIC)

        # Pass-but-ambiguous and revision still available: one LLM call.
        llm = self._llm_review(message, ctx)
        return self._merge_llm_outcome(message, ctx, det, llm, can_revise)

    async def _arun(self, message: SQLResult) -> ReviewOutcome:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)
        can_revise = self._can_revise(message, ctx)

        det = self._deterministic_review(message, ctx)

        if det.verdict == "revise":
            return self._resolve_revision(message, ctx, det, can_revise)

        cost_rev = self._cost_challenge_review(message)
        if cost_rev is not None and can_revise:
            return self._make_revision(message, ctx, cost_rev)

        if det.conclusive or not can_revise or not self._llm_available():
            return self._make_validated(message, det.notes, ReviewMethod.DETERMINISTIC)

        llm = await self._allm_review(message, ctx)
        return self._merge_llm_outcome(message, ctx, det, llm, can_revise)

    # ------------------------------------------------------------------
    # Revision budget
    # ------------------------------------------------------------------

    @staticmethod
    def _can_revise(message: SQLResult, ctx: SessionContext) -> bool:
        return (
            ctx.revision_count < BandConfig.MAX_REVISIONS
            and message.envelope.revision_count < BandConfig.MAX_REVISIONS
        )

    def _resolve_revision(
        self,
        message: SQLResult,
        ctx: SessionContext,
        review: _Review,
        can_revise: bool,
    ) -> ReviewOutcome:
        if can_revise:
            return self._make_revision(message, ctx, review)
        # Budget exhausted: pass regardless with an honest caveat.
        notes = list(review.notes)
        notes.append(
            "Revision budget exhausted; emitting best-effort result "
            f"(unresolved issue: {review.issue_type.value if review.issue_type else 'unknown'})."
        )
        return self._make_validated(
            message, notes, ReviewMethod.DETERMINISTIC, force_revision_applied=True
        )

    def _merge_llm_outcome(
        self,
        message: SQLResult,
        ctx: SessionContext,
        det: _Review,
        llm: Optional[_Review],
        can_revise: bool,
    ) -> ReviewOutcome:
        if llm is None:
            # LLM unavailable or failed -> graceful degradation to pass.
            return self._make_validated(message, det.notes, ReviewMethod.DETERMINISTIC)
        if llm.verdict == "revise" and can_revise:
            return self._make_revision(message, ctx, llm)
        return self._make_validated(
            message, det.notes + llm.notes, ReviewMethod.LLM_ASSISTED
        )

    # ------------------------------------------------------------------
    # Deterministic checks (no LLM). First match decides a revision.
    # ------------------------------------------------------------------

    def _deterministic_review(
        self, message: SQLResult, ctx: SessionContext
    ) -> _Review:
        notes = self._quality_notes(message)
        sql_lower = message.sql_query.lower()
        pattern = (ctx.query_pattern or "").lower()
        question = (ctx.normalized_question or "").lower()

        # 1. Execution status
        if message.execution_status == "error":
            err = message.error_message or "unknown error"
            if "validation failed" in err.lower():
                hint = (
                    f"The generated query failed safety validation ({err}). "
                    "Produce a valid read-only SELECT that answers the question."
                )
            else:
                hint = (
                    f"The query failed to execute: {err}. Fix the SQL "
                    "(check table/column names, joins, and syntax)."
                )
            return _Review("revise", IssueType.OTHER, hint, notes)

        # 2. Empty result
        if message.result_row_count == 0:
            return _Review(
                "revise",
                IssueType.EMPTY_RESULT,
                "Query returned no rows. Re-check JOIN conditions and WHERE "
                "filters; ensure filter values match the data.",
                notes,
            )

        # 3. Ranking without ORDER BY
        is_ranking = pattern == "ranking" or any(
            k in question for k in _RANKING_KEYWORDS
        )
        if is_ranking and "order by" not in sql_lower:
            return _Review(
                "revise",
                IssueType.MISSING_ORDER,
                "The question implies a ranking but the query has no ORDER BY. "
                "Add ORDER BY on the ranked metric (DESC for top-N).",
                notes,
            )

        # 4. Top/Bottom N without LIMIT
        if _TOPN_PATTERN.search(question) and "limit" not in sql_lower:
            return _Review(
                "revise",
                IssueType.MISSING_LIMIT,
                "The question asks for a top/bottom N but the query has no "
                "LIMIT. Add a LIMIT matching the requested N.",
                notes,
            )

        # 5. Null ratio
        per_col, overall = self._null_stats(
            message.result_columns, message.result_sample
        )
        all_null_cols = [c for c, ratio in per_col.items() if ratio >= 1.0]
        if message.result_sample and all_null_cols:
            return _Review(
                "revise",
                IssueType.NULL_HEAVY,
                "Column(s) "
                + ", ".join(all_null_cols)
                + " are entirely null in the result. Verify column selection "
                "and JOIN keys.",
                notes,
            )
        if overall > _NULL_HEAVY_THRESHOLD:
            notes.append(f"High null ratio in result sample ({overall:.0%}).")

        # Passed all hard checks. Decide whether semantic ambiguity warrants LLM.
        ambiguous, reason = self._is_ambiguous(message, pattern, question)
        if ambiguous:
            notes.append(f"Ambiguity flagged for semantic review: {reason}.")
        return _Review("pass", None, "", notes, conclusive=not ambiguous)

    # ------------------------------------------------------------------
    # Ambiguity heuristic -> gates the optional LLM call
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ambiguous(
        message: SQLResult, pattern: str, question: str
    ) -> tuple[bool, str]:
        # A comparison should usually yield >= 2 groups.
        if pattern == "comparison" and message.result_row_count < 2:
            return True, "comparison question returned fewer than two rows"
        # A distribution/share over a single row is suspicious.
        if pattern in {"distribution", "share"} and message.result_row_count <= 1:
            return True, "distribution/share question returned a single row"
        # A "by X" breakdown collapsing to one column may be incomplete.
        if " by " in question and len(message.result_columns) < 2:
            return True, "breakdown question returned a single column"
        return False, ""

    # ------------------------------------------------------------------
    # Optional single LLM review (sync + async)
    # ------------------------------------------------------------------

    def _llm_available(self) -> bool:
        if self.provider == LLMProvider.OLLAMA:
            return True
        return bool(settings.api_key_for(self.provider))

    def _build_review_prompt(self, message: SQLResult, ctx: SessionContext) -> str:
        import json

        sample = json.dumps(message.result_sample[:5], default=str)[:800]
        return f"""Review whether this SQL result answers the question.

Question: {ctx.normalized_question}
Detected pattern: {ctx.query_pattern}
SQL: {message.sql_query[:400]}
Result columns: {message.result_columns}
Row count: {message.result_row_count}
Sample rows: {sample}

Decide if the result correctly answers the question. If it clearly does,
verdict is "pass". If it is missing something the question asked for (wrong
aggregation, missing dimension, wrong filter), verdict is "revise" with a
short, specific fix.

Return ONLY this JSON:
{{"verdict": "pass", "issue_type": "wrong_aggregation", "revision_hint": ""}}
issue_type is one of: empty_result, wrong_aggregation, missing_limit,
missing_order, null_heavy, other."""

    def _parse_llm_review(self, content: str) -> Optional[_Review]:
        parsed = LLMResponseParser.extract_json(content)
        if not parsed:
            return None
        verdict = str(parsed.get("verdict", "pass")).lower().strip()
        if verdict != "revise":
            return _Review("pass", None, "", ["LLM semantic review: pass."],
                           conclusive=True)
        hint = str(parsed.get("revision_hint", "")).strip() or (
            "The result does not fully answer the question; revise the query."
        )
        issue = self._coerce_issue(parsed.get("issue_type"))
        return _Review("revise", issue, hint, ["LLM semantic review: revise."])

    def _llm_review(self, message: SQLResult, ctx: SessionContext) -> Optional[_Review]:
        try:
            resp = self.call_llm(
                session_id=message.envelope.session_id,
                prompt=self._build_review_prompt(message, ctx),
            )
        except LLMError as exc:
            logger.warning("Reviewer LLM call failed, defaulting to pass: %s", exc)
            return None
        return self._parse_llm_review(resp.content)

    async def _allm_review(
        self, message: SQLResult, ctx: SessionContext
    ) -> Optional[_Review]:
        try:
            resp = await self.acall_llm(
                session_id=message.envelope.session_id,
                prompt=self._build_review_prompt(message, ctx),
            )
        except LLMError as exc:
            logger.warning("Reviewer LLM call failed, defaulting to pass: %s", exc)
            return None
        return self._parse_llm_review(resp.content)

    @staticmethod
    def _coerce_issue(value: Any) -> IssueType:
        try:
            return IssueType(str(value))
        except (ValueError, TypeError):
            return IssueType.OTHER

    # ------------------------------------------------------------------
    # Quality notes + null statistics
    # ------------------------------------------------------------------

    def _quality_notes(self, message: SQLResult) -> list[str]:
        notes: list[str] = [f"{message.result_row_count} rows returned."]
        _, overall = self._null_stats(message.result_columns, message.result_sample)
        notes.append(f"Null ratio in sample: {overall:.0%}.")
        return notes

    @staticmethod
    def _null_stats(
        columns: list[str], sample: list[dict[str, Any]]
    ) -> tuple[dict[str, float], float]:
        if not sample or not columns:
            return {}, 0.0
        per_col: dict[str, float] = {}
        total_cells = 0
        null_cells = 0
        for col in columns:
            seen = 0
            nulls = 0
            for row in sample:
                if col in row:
                    seen += 1
                    total_cells += 1
                    if row[col] is None:
                        nulls += 1
                        null_cells += 1
            per_col[col] = (nulls / seen) if seen else 0.0
        overall = (null_cells / total_cells) if total_cells else 0.0
        return per_col, overall

    # ------------------------------------------------------------------
    # Output construction
    # ------------------------------------------------------------------

    def _cost_challenge_review(self, message: SQLResult) -> Optional[_Review]:
        """If the query is correct but expensive (full scan / high risk / over
        budget), return a revise-verdict that asks for a cheaper re-plan."""
        est = getattr(message, "cost_estimate", None)
        if est is None:
            return None
        rows = est.estimated_rows_scanned or 0
        expensive = (
            est.risk_level == "high"
            or (est.within_budget is False)
            or (est.full_scan_tables and rows >= _COST_CHALLENGE_ROWS)
        )
        if not expensive:
            return None
        scope = (f"scans ~{rows:,} rows" if rows else f"risk={est.risk_level}")
        scanned = ", ".join(est.full_scan_tables) if est.full_scan_tables else "the data"
        hint = (
            f"This query does a full scan of {scanned} and {scope}. Re-plan a "
            "cheaper query: add a selective WHERE filter, use an indexed/key "
            "column, or aggregate earlier to avoid the full scan."
        )
        return _Review(verdict="revise", issue_type=IssueType.OTHER, revision_hint=hint,
                       notes=[f"Cost challenge: {scope}."])

    def _make_revision(
        self, message: SQLResult, ctx: SessionContext, review: _Review
    ) -> RevisionRequest:
        ctx.revision_count += 1
        session_id = message.envelope.session_id
        self._emit(
            session_id,
            event_type="tool_call",
            detail={
                "role": self.role,
                "decision": "revise",
                "issue": review.issue_type.value if review.issue_type else "other",
                "revision_count": ctx.revision_count,
            },
        )
        return RevisionRequest(
            envelope=make_envelope(
                session_id=session_id,
                from_role=self.role,
                channel=BandConfig.CHANNEL_TASKS,
                topic=BandConfig.TOPIC_REVISION,
                to_role="sql_engineer",
                revision_count=ctx.revision_count,
            ),
            issue_type=review.issue_type or IssueType.OTHER,
            revision_hint=review.revision_hint,
            previous_sql=message.sql_query,
            must_succeed=True,
        )

    def _make_validated(
        self,
        message: SQLResult,
        notes: list[str],
        review_method: ReviewMethod,
        *,
        force_revision_applied: bool = False,
    ) -> ValidatedResult:
        session_id = message.envelope.session_id
        revision_applied = force_revision_applied or (
            message.envelope.revision_count >= 1
        )
        self._emit(
            session_id,
            event_type="tool_call",
            detail={
                "role": self.role,
                "decision": "pass",
                "method": review_method.value,
                "revision_applied": revision_applied,
            },
        )
        return ValidatedResult(
            envelope=make_envelope(
                session_id=session_id,
                from_role=self.role,
                channel=BandConfig.CHANNEL_TASKS,
                topic=BandConfig.TOPIC_HANDOFF,
                to_role="reporting_agent",
                revision_count=message.envelope.revision_count,
            ),
            sql_result=message,
            verdict="pass",
            data_quality_notes=notes,
            review_method=review_method,
            revision_applied=revision_applied,
        )
