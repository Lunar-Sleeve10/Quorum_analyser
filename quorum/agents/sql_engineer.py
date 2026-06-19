"""
agents/sql_engineer.py — SQL Engineer agent.

Second agent in the flow. Consumes a SchemaGroundedTask from the Orchestrator
and produces an SQLResult for the Reviewer. On the revision path it consumes a
RevisionRequest (at most once per session) and produces a corrected SQLResult.

Reuses the original pipeline logic:
- refiner_node        -> _refine (re-fetch + verify columns against the live DB)
- sql_generator_node  -> _build_generation_prompt + single LLM call
- execute_query_node  -> _execute
- SQLValidator        -> deterministic safety gate before any execution

Budget: exactly one LLM call per invocation. The first pass and the (optional)
single revision are separate invocations, each making one call, which keeps the
whole flow inside the 3-4 call budget. Validation and execution are fully
deterministic and never cost a call.

Schema grounding (tables, verified columns, normalized question) is read from
SessionContext written by the Orchestrator; the live adapter is taken from the
session context and never travels through a Band message.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from agents.base import BaseAgent
from pipeline.models import (
    RevisionRequest,
    SchemaGroundedTask,
    SQLResult,
    make_envelope,
)
from pipeline.session_context import SessionContext, context_store
from config import BandConfig, LLMProvider, settings
from core.database import DatabaseAdapter
from core.llm_router import LLMResponse, LLMRouter
from core.parsers import LLMResponseParser
from core.semantic_layer import get_semantic_layer, render_for_prompt
from core.validators import SQLValidator

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _GenerationInputs:
    """Resolved, DB-verified inputs for one generation pass."""
    adapter: DatabaseAdapter
    normalized_question: str
    table_columns: dict[str, list[str]]
    subtasks: list[str] = field(default_factory=list)
    complexity: str = "medium"
    query_plan: str = ""
    max_rows: int = 1000


class SQLEngineerAgent(BaseAgent[SchemaGroundedTask, SQLResult]):
    role = "sql_engineer"

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
            provider=provider or settings.sql_engineer_provider,
            model=model or settings.sql_engineer_model(),
            llm_router=llm_router,
            telemetry=telemetry,
            agent_id=agent_id,
        )

    # ------------------------------------------------------------------
    # Query-construction planning (conditional on complexity)
    # ------------------------------------------------------------------
    _PLAN_COMPLEXITY = {"medium", "complex"}

    def _should_plan(self, inputs: "_GenerationInputs") -> bool:
        return inputs.complexity in self._PLAN_COMPLEXITY and len(inputs.table_columns) >= 2

    def _plan_prompt(self, inputs: "_GenerationInputs", feedback: str = "") -> str:
        columns_block = "\n".join(f"{t}: {', '.join(c)}" for t, c in inputs.table_columns.items())
        fb = f"\nA reviewer raised this issue — fix it in the plan: {feedback}\n" if feedback else ""
        return f"""You are a SQL query planner. Produce a SHORT construction plan
(NO SQL) for how to build the query efficiently and correctly.

Question: {inputs.normalized_question}
Tables and columns:
{columns_block}
{fb}
Output 5-8 lines covering: JOINS (tables + join keys), AGGREGATION (grain +
measures), FILTERS, OUTPUT COLUMNS, ORDER/LIMIT. Be concrete and minimal."""

    def _plan_query(self, session_id: str, inputs: "_GenerationInputs", feedback: str = "") -> str:
        try:
            resp = self.call_llm(session_id=session_id, prompt=self._plan_prompt(inputs, feedback))
            plan = (resp.content or "").strip()
        except Exception as exc:
            logger.warning("query planning skipped: %s", exc)
            return ""
        try:
            context_store.get(session_id).put_artifact("query_plan", plan)
        except Exception:
            pass
        self._emit(session_id, event_type="tool_call",
                   detail={"role": self.role, "event": "query_planned",
                           "complexity": inputs.complexity})
        return plan

    async def _aplan_query(self, session_id: str, inputs: "_GenerationInputs", feedback: str = "") -> str:
        try:
            resp = await self.acall_llm(session_id=session_id, prompt=self._plan_prompt(inputs, feedback))
            plan = (resp.content or "").strip()
        except Exception as exc:
            logger.warning("query planning skipped: %s", exc)
            return ""
        try:
            context_store.get(session_id).put_artifact("query_plan", plan)
        except Exception:
            pass
        return plan

    # ------------------------------------------------------------------
    # Primary path: SchemaGroundedTask -> SQLResult (one LLM call)
    # ------------------------------------------------------------------

    def _run(self, message: SchemaGroundedTask) -> SQLResult:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)
        inputs = self._resolve_from_task(message, ctx)

        if not inputs.table_columns:
            return self._error_result(
                session_id,
                sql="",
                error="No tables available for SQL generation",
                attempt=1,
                revision_count=message.envelope.revision_count,
            )

        if self._should_plan(inputs):
            inputs.query_plan = self._plan_query(session_id, inputs)
        prompt = self._build_generation_prompt(inputs, revision=None)
        response = self.call_llm(session_id=session_id, prompt=prompt)
        sql = LLMResponseParser.extract_sql(response.content)
        return self._finalize_sql(
            session_id=session_id,
            sql=sql,
            inputs=inputs,
            model_used=response.model,
            attempt=1,
            revision_count=message.envelope.revision_count,
        )

    async def _arun(self, message: SchemaGroundedTask) -> SQLResult:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)
        inputs = self._resolve_from_task(message, ctx)

        if not inputs.table_columns:
            return self._error_result(
                session_id,
                sql="",
                error="No tables available for SQL generation",
                attempt=1,
                revision_count=message.envelope.revision_count,
            )

        if self._should_plan(inputs):
            inputs.query_plan = await self._aplan_query(session_id, inputs)
        prompt = self._build_generation_prompt(inputs, revision=None)
        response = await self.acall_llm(session_id=session_id, prompt=prompt)
        sql = LLMResponseParser.extract_sql(response.content)
        return self._finalize_sql(
            session_id=session_id,
            sql=sql,
            inputs=inputs,
            model_used=response.model,
            attempt=1,
            revision_count=message.envelope.revision_count,
        )

    # ------------------------------------------------------------------
    # Revision path: RevisionRequest -> SQLResult (one LLM call)
    #
    # Wrapped with the same start/complete/error telemetry as BaseAgent.run,
    # since the typed _run contract is bound to SchemaGroundedTask.
    # ------------------------------------------------------------------

    def run_revision(self, message: RevisionRequest) -> SQLResult:
        session_id = message.envelope.session_id
        self._emit(session_id, event_type="task_started",
                   detail={"role": self.role, "revision": True})
        start = time.perf_counter()
        try:
            result = self._revise(message)
        except Exception as exc:
            self._emit(session_id, event_type="error",
                       detail={"role": self.role, "error": str(exc)})
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._emit(session_id, event_type="task_completed",
                   detail={"role": self.role, "revision": True,
                           "latency_ms": round(elapsed_ms, 1)})
        return result

    async def arun_revision(self, message: RevisionRequest) -> SQLResult:
        session_id = message.envelope.session_id
        self._emit(session_id, event_type="task_started",
                   detail={"role": self.role, "revision": True})
        start = time.perf_counter()
        try:
            result = await self._arevise(message)
        except Exception as exc:
            self._emit(session_id, event_type="error",
                       detail={"role": self.role, "error": str(exc)})
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._emit(session_id, event_type="task_completed",
                   detail={"role": self.role, "revision": True,
                           "latency_ms": round(elapsed_ms, 1)})
        return result

    def _revise(self, message: RevisionRequest) -> SQLResult:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)
        inputs = self._resolve_from_context(ctx)

        if not inputs.table_columns:
            return self._error_result(
                session_id, sql=message.previous_sql,
                error="No tables available for SQL revision",
                attempt=2, revision_count=1,
            )

        if self._should_plan(inputs):
            inputs.query_plan = self._plan_query(session_id, inputs, feedback=message.revision_hint)
        prompt = self._build_generation_prompt(inputs, revision=message)
        response = self.call_llm(session_id=session_id, prompt=prompt)
        sql = LLMResponseParser.extract_sql(response.content)
        return self._finalize_sql(
            session_id=session_id, sql=sql, inputs=inputs,
            model_used=response.model, attempt=2, revision_count=1,
        )

    async def _arevise(self, message: RevisionRequest) -> SQLResult:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)
        inputs = self._resolve_from_context(ctx)

        if not inputs.table_columns:
            return self._error_result(
                session_id, sql=message.previous_sql,
                error="No tables available for SQL revision",
                attempt=2, revision_count=1,
            )

        if self._should_plan(inputs):
            inputs.query_plan = await self._aplan_query(session_id, inputs, feedback=message.revision_hint)
        prompt = self._build_generation_prompt(inputs, revision=message)
        response = await self.acall_llm(session_id=session_id, prompt=prompt)
        sql = LLMResponseParser.extract_sql(response.content)
        return self._finalize_sql(
            session_id=session_id, sql=sql, inputs=inputs,
            model_used=response.model, attempt=2, revision_count=1,
        )

    # ------------------------------------------------------------------
    # Input resolution (reads SessionContext, re-verifies columns vs DB)
    # ------------------------------------------------------------------

    def _resolve_from_task(
        self, message: SchemaGroundedTask, ctx: SessionContext
    ) -> _GenerationInputs:
        adapter = self._require_adapter(ctx)

        # Handoff selections are authoritative; fall back to context grounding.
        table_columns: dict[str, list[str]] = {
            sel.table: list(sel.columns) for sel in message.selections
        }
        if not table_columns:
            table_columns = {
                t: list(cols) for t, cols in ctx.relevant_columns.items()
            }

        verified = self._refine(adapter, table_columns)
        normalized_question = (
            message.normalized_question or ctx.normalized_question
        ).strip()
        subtasks = message.subtasks or [normalized_question]
        complexity = str(getattr(message.complexity, "value", message.complexity) or "medium")
        return _GenerationInputs(
            complexity=complexity,
            adapter=adapter,
            normalized_question=normalized_question,
            table_columns=verified,
            subtasks=subtasks,
            max_rows=self._max_rows(ctx),
        )

    def _resolve_from_context(self, ctx: SessionContext) -> _GenerationInputs:
        adapter = self._require_adapter(ctx)
        table_columns = {t: list(cols) for t, cols in ctx.relevant_columns.items()}
        verified = self._refine(adapter, table_columns)
        normalized_question = ctx.normalized_question.strip()
        return _GenerationInputs(
            adapter=adapter,
            complexity=str(ctx.complexity or "medium"),
            normalized_question=normalized_question,
            table_columns=verified,
            subtasks=[normalized_question] if normalized_question else [],
            max_rows=self._max_rows(ctx),
        )

    @staticmethod
    def _require_adapter(ctx: SessionContext) -> DatabaseAdapter:
        if ctx.adapter is None:
            raise RuntimeError(
                f"SessionContext for {ctx.session_id} has no database adapter"
            )
        return ctx.adapter

    @staticmethod
    def _max_rows(ctx: SessionContext) -> int:
        if ctx.db_config is not None:
            return ctx.db_config.max_rows
        return settings.db_max_rows

    # ------------------------------------------------------------------
    # refiner_node port: re-fetch DB columns, keep only valid ones
    # ------------------------------------------------------------------

    @staticmethod
    def _refine(
        adapter: DatabaseAdapter, table_columns: dict[str, list[str]]
    ) -> dict[str, list[str]]:
        verified: dict[str, list[str]] = {}
        for table, requested in table_columns.items():
            try:
                db_columns = adapter.get_columns(table)
            except Exception as exc:
                logger.warning("Could not fetch columns for %s: %s", table, exc)
                continue
            if not db_columns:
                continue
            actual_lower = {c.lower(): c for c in db_columns}
            kept: list[str] = []
            for col in requested:
                match = actual_lower.get(str(col).lower())
                if match is not None:
                    kept.append(match)
            verified[table] = kept if kept else db_columns
        return verified

    # ------------------------------------------------------------------
    # sql_generator_node port: minimal prompt (+ targeted revision block)
    # ------------------------------------------------------------------

    def _build_generation_prompt(
        self,
        inputs: _GenerationInputs,
        *,
        revision: Optional[RevisionRequest],
    ) -> str:
        columns_block = "\n".join(
            f"{table}: {', '.join(cols)}"
            for table, cols in inputs.table_columns.items()
        )
        subtasks_block = "\n".join(f"- {t}" for t in inputs.subtasks[:3])
        plan_block = (f"\nConstruction plan to follow (built by the query planner):\n{inputs.query_plan}\n"
                      if inputs.query_plan else "")

        # Ground in the certified semantic layer: retrieve only the relevant
        # slice for this question and hand the model the certified metric
        # definitions. This both keeps the prompt small (scales to large
        # schemas) and prevents the model from inventing its own formula.
        semantic_block = ""
        try:
            layer = get_semantic_layer(settings.metric_catalog_path)
            retrieved = layer.retrieve(
                inputs.normalized_question, k=settings.schema_retrieval_k
            )
            if not retrieved.is_empty():
                semantic_block = (
                    "\nCertified business definitions (PREFER these exact "
                    "formulas; do not invent your own):\n"
                    + render_for_prompt(retrieved)
                    + "\n"
                )
        except Exception as exc:  # never let grounding break generation
            logger.warning("Semantic layer grounding skipped: %s", exc)

        base = f"""Generate a single SQLite SELECT query.

Question: {inputs.normalized_question}
{semantic_block}
Available tables and columns (use exact names, case-sensitive):
{columns_block}

Steps:
{subtasks_block}
{plan_block}
Rules:
1. Use ONLY the tables and columns listed above.
2. When a certified metric definition is provided for the requested measure,
   use that exact SQL expression rather than constructing your own.
3. Valid SQLite syntax only; produce one statement.
4. GROUP BY when aggregating.
5. ORDER BY for rankings; LIMIT for top-N.
6. Prefer window functions where they simplify the query.

Return the SQL inside a ```sql``` code block."""

        if revision is None:
            return base

        return base + f"""

A previous attempt was rejected during review.
Previous SQL:
{revision.previous_sql}

Issue type: {revision.issue_type.value}
Required correction: {revision.revision_hint}

Produce a corrected query that resolves the issue while still answering the
question. Return the SQL inside a ```sql``` code block."""

    # ------------------------------------------------------------------
    # Deterministic validation + execution (execute_query_node port)
    # ------------------------------------------------------------------

    def _finalize_sql(
        self,
        *,
        session_id: str,
        sql: str,
        inputs: _GenerationInputs,
        model_used: str,
        attempt: int,
        revision_count: int,
    ) -> SQLResult:
        is_valid, validation_error = SQLValidator.validate(sql)
        self._emit(
            session_id,
            event_type="tool_call",
            detail={"role": self.role, "tool": "sql_validator",
                    "valid": is_valid, "error": validation_error},
        )
        if not is_valid:
            return self._error_result(
                session_id, sql=sql,
                error=f"Validation failed: {validation_error}",
                attempt=attempt, revision_count=revision_count,
                model_used=model_used,
            )

        try:
            rows, columns = inputs.adapter.execute_query(sql, inputs.max_rows)
        except Exception as exc:
            logger.error("Query execution failed: %s", exc)
            self._emit(
                session_id, event_type="tool_call",
                detail={"role": self.role, "tool": "execute_query",
                        "status": "error", "error": str(exc)},
            )
            return self._error_result(
                session_id, sql=sql, error=f"Execution error: {exc}",
                attempt=attempt, revision_count=revision_count,
                model_used=model_used,
            )

        sample = self._build_sample(rows, columns)
        self._emit(
            session_id, event_type="tool_call",
            detail={"role": self.role, "tool": "execute_query",
                    "status": "success", "rows": len(rows)},
        )
        return SQLResult(
            envelope=self._review_envelope(session_id, revision_count),
            sql_query=sql,
            execution_status="success",
            error_message=None,
            result_columns=list(columns),
            result_row_count=len(rows),
            result_sample=sample,
            model_used=model_used,
            generation_attempt=attempt,
        )

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def _review_envelope(self, session_id: str, revision_count: int):
        return make_envelope(
            session_id=session_id,
            from_role=self.role,
            channel=BandConfig.CHANNEL_TASKS,
            topic=BandConfig.TOPIC_REVIEW,
            to_role="reviewer",
            revision_count=revision_count,
        )

    def _error_result(
        self,
        session_id: str,
        *,
        sql: str,
        error: str,
        attempt: int,
        revision_count: int,
        model_used: str = "",
    ) -> SQLResult:
        return SQLResult(
            envelope=self._review_envelope(session_id, revision_count),
            sql_query=sql,
            execution_status="error",
            error_message=error,
            result_columns=[],
            result_row_count=0,
            result_sample=[],
            model_used=model_used or self.model,
            generation_attempt=attempt,
        )

    @staticmethod
    def _build_sample(
        rows: list[Any], columns: list[str]
    ) -> list[dict[str, Any]]:
        sample: list[dict[str, Any]] = []
        for row in rows[: BandConfig.RESULT_SAMPLE_ROWS]:
            record = {
                col: SQLEngineerAgent._jsonable(value)
                for col, value in zip(columns, row)
            }
            sample.append(record)
        return sample

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8", errors="replace")
            except Exception:
                return str(value)
        return str(value)
