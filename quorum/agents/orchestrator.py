"""
agents/orchestrator.py — Query Orchestrator agent.

First agent in the flow. Consumes a UserQuery and produces a
SchemaGroundedTask for the SQL Engineer. It collapses what were three separate
LLM calls in the original pipeline (intent classification, normalization,
table/column selection) into a SINGLE merged LLM call, then performs
deterministic verification of the LLM's table/column choices against the live
database schema. Verification never costs an LLM call, preserving the
"maximum 1 LLM call per query" budget.

Human-in-the-loop: when the question is unclear (or the clarification budget is
exhausted), the agent raises ClarificationNeeded carrying a ClarificationRequest
for the session runner to route back to the UI on the control channel. This
keeps the typed _run contract (UserQuery -> SchemaGroundedTask) clean while
still supporting the interrupt.

Shared context: the verified normalized question, query pattern, complexity,
relevant tables/columns, and a compact schema digest are written to
SessionContext so downstream agents reference them by context_ref instead of
re-serializing schema into Band messages.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from agents.base import BaseAgent
from pipeline.models import (
    ClarificationRequest,
    SchemaGroundedTask,
    TableColumnSelection,
    UserQuery,
    make_envelope,
)
from pipeline.session_context import ColumnInfo, SessionContext, TableDigest, context_store
from config import BandConfig, ExecutionMode, LLMProvider, settings
from core.cache import SchemaCache
from core.database import DatabaseAdapter
from core.llm_router import LLMResponse, LLMRouter
from core.parsers import LLMResponseParser

logger = logging.getLogger(__name__)

_VALID_COMPLEXITY = {"simple", "medium", "complex"}
_MAX_TABLES = 5
_FALLBACK_TABLE_LIMIT = 3
_MIN_KEYWORD_LEN = 3


class ClarificationNeeded(Exception):
    """
    Raised by the Orchestrator when the question is unclear.

    Carries a fully-formed ClarificationRequest message that the session runner
    sends back to the UI on the control channel. This is a control-flow signal,
    not an error condition.
    """

    def __init__(self, request: ClarificationRequest) -> None:
        self.request = request
        super().__init__(request.clarification_message)


class QueryOrchestratorAgent(BaseAgent[UserQuery, SchemaGroundedTask]):
    role = "orchestrator"

    def __init__(
        self,
        *,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        llm_router: Optional[LLMRouter] = None,
        telemetry: Optional[Any] = None,
        agent_id: Optional[str] = None,
        max_clarifications: int = BandConfig.MAX_CLARIFICATIONS,
        data_dictionary: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            provider=provider or settings.orchestrator_provider,
            model=model or settings.orchestrator_model,
            llm_router=llm_router,
            telemetry=telemetry,
            agent_id=agent_id,
        )
        self.max_clarifications = max_clarifications
        self.data_dictionary = data_dictionary

    # ------------------------------------------------------------------
    # Public business logic (sync + async). Both make exactly one LLM call.
    # ------------------------------------------------------------------

    def _run(self, message: UserQuery) -> SchemaGroundedTask:
        ctx, adapter, full_schema, available_tables = self._prepare(message)
        prompt = self._build_merged_prompt(
            question=message.question,
            available_tables=available_tables,
            full_schema=full_schema,
        )
        response = self.call_llm(session_id=message.envelope.session_id, prompt=prompt)
        return self._finalize(message, ctx, adapter, available_tables, response)

    async def _arun(self, message: UserQuery) -> SchemaGroundedTask:
        ctx, adapter, full_schema, available_tables = self._prepare(message)
        prompt = self._build_merged_prompt(
            question=message.question,
            available_tables=available_tables,
            full_schema=full_schema,
        )
        response = await self.acall_llm(
            session_id=message.envelope.session_id, prompt=prompt
        )
        return self._finalize(message, ctx, adapter, available_tables, response)

    # ------------------------------------------------------------------
    # Preparation: resolve context, adapter, schema, clarification budget
    # ------------------------------------------------------------------

    def _prepare(
        self, message: UserQuery
    ) -> tuple[SessionContext, DatabaseAdapter, str, list[str]]:
        session_id = message.envelope.session_id
        ctx = context_store.get(session_id)

        if ctx.adapter is None:
            raise RuntimeError(
                f"SessionContext for {session_id} has no database adapter"
            )
        adapter = ctx.adapter

        # Enforce clarification budget before spending an LLM call.
        if message.clarification_count >= self.max_clarifications:
            self._raise_clarification(
                message,
                ctx,
                clarification_message=(
                    f"Maximum clarifications reached "
                    f"({self.max_clarifications}). Please rephrase your question "
                    "with a clear metric and dimension."
                ),
                count=message.clarification_count,
            )

        full_schema = SchemaCache.get_schema(message.db_path, adapter)
        available_tables = adapter.get_tables()
        return ctx, adapter, full_schema, available_tables

    # ------------------------------------------------------------------
    # Finalize: parse merged response, clarity gate, verify, write context
    # ------------------------------------------------------------------

    def _finalize(
        self,
        message: UserQuery,
        ctx: SessionContext,
        adapter: DatabaseAdapter,
        available_tables: list[str],
        response: LLMResponse,
    ) -> SchemaGroundedTask:
        parsed = LLMResponseParser.extract_json(response.content)
        if parsed is None:
            self._raise_clarification(
                message,
                ctx,
                clarification_message=(
                    "Could not interpret the question. Please rephrase with a "
                    "specific metric and dimension."
                ),
                count=message.clarification_count,
            )
        assert parsed is not None  # narrowed by _raise_clarification (NoReturn)

        is_clear = bool(parsed.get("is_clear", False))
        if not is_clear:
            msg = (
                parsed.get("clarification_message")
                or "Please specify the metric and dimension to analyze."
            )
            self._raise_clarification(
                message, ctx, clarification_message=msg,
                count=message.clarification_count,
            )

        normalized_question = (
            parsed.get("normalized_question") or message.question
        ).strip()
        query_pattern = str(parsed.get("query_pattern", "unknown")).strip() or "unknown"
        complexity = self._normalize_complexity(parsed.get("complexity"))
        subtasks = self._normalize_subtasks(parsed.get("subtasks"), normalized_question)

        llm_tables = parsed.get("relevant_tables") or []
        llm_columns = parsed.get("relevant_columns") or {}

        tables, columns = self._verify_selection(
            adapter=adapter,
            available_tables=available_tables,
            llm_tables=llm_tables if isinstance(llm_tables, list) else [],
            llm_columns=llm_columns if isinstance(llm_columns, dict) else {},
        )

        if not tables:
            tables, columns = self._semantic_fallback(
                adapter=adapter,
                available_tables=available_tables,
                question=normalized_question,
            )

        if not tables:
            self._raise_clarification(
                message,
                ctx,
                clarification_message=(
                    "Could not match the question to any table in the database. "
                    "Please mention the entity or table you want to analyze."
                ),
                count=message.clarification_count,
            )

        schema_digest = self._build_schema_digest(adapter, tables)

        # Write shared context — single source of truth for downstream agents.
        ctx.normalized_question = normalized_question
        ctx.query_pattern = query_pattern
        ctx.complexity = complexity
        ctx.relevant_tables = tables
        ctx.relevant_columns = columns
        ctx.schema_digest = schema_digest

        logger.info(
            "Orchestrator resolved: tables=%s pattern=%s complexity=%s",
            tables, query_pattern, complexity,
        )

        return self._build_task(message, tables, columns, normalized_question,
                                complexity, query_pattern, subtasks)

    # ------------------------------------------------------------------
    # Merged prompt construction
    # ------------------------------------------------------------------

    def _build_merged_prompt(
        self,
        *,
        question: str,
        available_tables: list[str],
        full_schema: str,
    ) -> str:
        table_list = "\n".join(f"- {t}" for t in available_tables)
        dd_block = ""
        if self.data_dictionary:
            dd_block = (
                "\n\nData Dictionary:\n"
                + json.dumps(self.data_dictionary, indent=2)
            )

        return f"""You are a database analyst. In ONE response, classify the
question, normalize it, assess complexity, and select the schema needed to
answer it.

Question: "{question}"

AVAILABLE TABLES:
{table_list}

FULL SCHEMA (table definitions with column types):
{full_schema}{dd_block}

Clarity rule:
- CLEAR = has a metric (sum/avg/count/share/rank) AND a dimension (by X / per X).
- UNCLEAR = vague, greeting, or missing metric or dimension.
Examples CLEAR: "top 10 customers by revenue", "market share by category",
"compare Q1 vs Q2", "total sales by region".
Examples UNCLEAR: "show data", "sales", "hello".

Selection rule:
1. Extract key entities (nouns) from the question.
2. Match entities to table NAMES first, then to COLUMN names.
3. Select 1-{_MAX_TABLES} tables. Use ONLY names from AVAILABLE TABLES.
4. For each selected table, list ONLY the columns needed (exact case). Use
   exact column names from the schema; do not invent columns.

Complexity:
- simple: single lookup/filter/count.
- medium: aggregation/grouping/join.
- complex: multiple operations or window functions.

Pattern: one of ranking | share | comparison | aggregation | distribution |
trend | filter | unclear.

Return ONLY this JSON, nothing else:
{{
  "is_clear": true,
  "clarification_message": "",
  "query_pattern": "ranking",
  "normalized_question": "clear rephrasing of the question",
  "complexity": "medium",
  "subtasks": ["logical step 1", "logical step 2"],
  "relevant_tables": ["table1", "table2"],
  "relevant_columns": {{"table1": ["col1", "col2"], "table2": ["col3"]}}
}}

If UNCLEAR: set "is_clear" false, fill "clarification_message", and leave
"relevant_tables" empty."""

    # ------------------------------------------------------------------
    # Deterministic verification (no LLM)
    # ------------------------------------------------------------------

    def _verify_selection(
        self,
        *,
        adapter: DatabaseAdapter,
        available_tables: list[str],
        llm_tables: list[Any],
        llm_columns: dict[str, Any],
    ) -> tuple[list[str], dict[str, list[str]]]:
        available_set = set(available_tables)
        verified_tables: list[str] = []
        verified_columns: dict[str, list[str]] = {}

        for raw in llm_tables:
            table = str(raw)
            if table not in available_set:
                logger.warning("Discarding hallucinated table: %s", table)
                continue
            try:
                actual_cols = adapter.get_columns(table)
            except Exception as exc:
                logger.warning("Could not fetch columns for %s: %s", table, exc)
                continue

            requested = llm_columns.get(table, [])
            requested = requested if isinstance(requested, list) else []
            actual_lower = {c.lower(): c for c in actual_cols}

            kept: list[str] = []
            for col in requested:
                match = actual_lower.get(str(col).lower())
                if match is not None:
                    kept.append(match)

            verified_tables.append(table)
            verified_columns[table] = kept if kept else actual_cols
            if len(verified_tables) >= _MAX_TABLES:
                break

        return verified_tables, verified_columns

    # ------------------------------------------------------------------
    # Semantic keyword fallback (no LLM) — preserves robustness within budget
    # ------------------------------------------------------------------

    def _semantic_fallback(
        self,
        *,
        adapter: DatabaseAdapter,
        available_tables: list[str],
        question: str,
    ) -> tuple[list[str], dict[str, list[str]]]:
        keywords = set(re.findall(rf"\b[a-zA-Z]{{{_MIN_KEYWORD_LEN},}}\b", question.lower()))
        scores: dict[str, int] = {}

        for table in available_tables:
            score = 0
            table_lower = table.lower()
            for word in keywords:
                if word == table_lower or word in table_lower or table_lower in word:
                    score += 10
            try:
                for col in adapter.get_columns(table):
                    col_lower = col.lower()
                    for word in keywords:
                        if word == col_lower or word in col_lower or col_lower in word:
                            score += 2
            except Exception:
                continue
            if score > 0:
                scores[table] = score

        if scores:
            ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
            selected = [t for t, _ in ranked[:_FALLBACK_TABLE_LIMIT]]
            logger.info("Semantic fallback selected: %s", selected)
        else:
            selected = available_tables[:_FALLBACK_TABLE_LIMIT]
            logger.warning("No keyword matches; using first tables: %s", selected)

        columns: dict[str, list[str]] = {}
        for table in selected:
            try:
                columns[table] = adapter.get_columns(table)
            except Exception:
                columns[table] = []
        return selected, columns

    # ------------------------------------------------------------------
    # Compact schema digest for SessionContext
    # ------------------------------------------------------------------

    def _build_schema_digest(
        self, adapter: DatabaseAdapter, tables: list[str]
    ) -> dict[str, TableDigest]:
        digest: dict[str, TableDigest] = {}
        try:
            schema_info = adapter.get_schema_info(tables)
        except Exception as exc:
            logger.warning("get_schema_info failed: %s", exc)
            schema_info = ""

        parsed_types = self._parse_schema_info(schema_info)
        for table in tables:
            col_types = parsed_types.get(table)
            if col_types is None:
                # Fall back to names without types.
                try:
                    names = adapter.get_columns(table)
                except Exception:
                    names = []
                col_types = [(name, "") for name in names]
            digest[table] = TableDigest(
                name=table,
                columns=[ColumnInfo(name=n, type=t) for n, t in col_types],
            )
        return digest

    @staticmethod
    def _parse_schema_info(schema_info: str) -> dict[str, list[tuple[str, str]]]:
        """Parse 'table(col TYPE, col TYPE)' lines into per-table column tuples."""
        result: dict[str, list[tuple[str, str]]] = {}
        for line in schema_info.splitlines():
            line = line.strip()
            match = re.match(r"^(\w+)\((.*)\)$", line)
            if not match:
                continue
            table = match.group(1)
            inner = match.group(2)
            cols: list[tuple[str, str]] = []
            for part in inner.split(","):
                part = part.strip()
                if not part:
                    continue
                pieces = part.split(" ", 1)
                name = pieces[0].strip()
                col_type = pieces[1].strip() if len(pieces) > 1 else ""
                cols.append((name, col_type))
            result[table] = cols
        return result

    # ------------------------------------------------------------------
    # Output construction + clarification helper
    # ------------------------------------------------------------------

    def _build_task(
        self,
        message: UserQuery,
        tables: list[str],
        columns: dict[str, list[str]],
        normalized_question: str,
        complexity: str,
        query_pattern: str,
        subtasks: list[str],
    ) -> SchemaGroundedTask:
        session_id = message.envelope.session_id
        selections = [
            TableColumnSelection(table=t, columns=columns.get(t, []))
            for t in tables
        ]
        envelope = make_envelope(
            session_id=session_id,
            from_role=self.role,
            channel=BandConfig.CHANNEL_TASKS,
            topic=BandConfig.TOPIC_HANDOFF,
            to_role="sql_engineer",
        )
        return SchemaGroundedTask(
            envelope=envelope,
            normalized_question=normalized_question,
            complexity=complexity,  # type: ignore[arg-type]
            query_pattern=query_pattern,
            selections=selections,
            subtasks=subtasks,
            schema_digest_ref=f"{session_id}:schema",
        )

    def _raise_clarification(
        self,
        message: UserQuery,
        ctx: SessionContext,
        *,
        clarification_message: str,
        count: int,
    ) -> "None":
        session_id = message.envelope.session_id
        new_count = count + 1
        ctx.clarification_count = new_count
        self._emit(
            session_id,
            event_type="tool_call",
            detail={"role": self.role, "clarification": True, "count": new_count},
        )
        request = ClarificationRequest(
            envelope=make_envelope(
                session_id=session_id,
                from_role=self.role,
                channel=BandConfig.CHANNEL_CONTROL,
                topic=BandConfig.TOPIC_CONTROL,
                to_role="user",
            ),
            clarification_message=clarification_message,
            clarification_count=new_count,
        )
        raise ClarificationNeeded(request)

    # ------------------------------------------------------------------
    # Normalizers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_complexity(value: Any) -> str:
        text = str(value).lower().strip() if value is not None else ""
        return text if text in _VALID_COMPLEXITY else "medium"

    @staticmethod
    def _normalize_subtasks(value: Any, normalized_question: str) -> list[str]:
        if isinstance(value, list):
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if cleaned:
                return cleaned
        return [normalized_question]

    @staticmethod
    def execution_mode_for(complexity: str) -> str:
        mapping = {
            "simple": ExecutionMode.DIRECT_SQL.value,
            "medium": ExecutionMode.LIGHT_PLAN.value,
            "complex": ExecutionMode.FULL_PLAN.value,
        }
        return mapping.get(complexity, ExecutionMode.LIGHT_PLAN.value)
