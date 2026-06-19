"""
models/state.py — Internal state types and runtime configuration objects.

These are the private, in-process types used inside agents and the session
runner. They are deliberately kept separate from the Band message contracts
(band/models.py) so that agents convert at their boundary and never leak
internal state across Band.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypedDict

from config import DatabaseType, ExecutionMode, LLMProvider


# ---------------------------------------------------------------------------
# Runtime configuration dataclasses
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DatabaseConfig:
    db_type: DatabaseType
    connection_string: str
    max_rows: int = 1000
    timeout: int = 30
    read_only: bool = True


@dataclass(slots=True)
class SystemConfig:
    """Per-request runtime config assembled by the session runner."""
    orchestrator_provider: LLMProvider
    sql_engineer_provider: LLMProvider
    reviewer_provider: LLMProvider
    reporting_provider: LLMProvider
    orchestrator_model: str
    sql_engineer_model: str
    reviewer_model: str
    reporting_model: str
    temperature: float = 0.1
    max_tokens: int = 2048
    max_clarifications: int = 3
    max_rows: int = 1000
    data_dictionary: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Per-agent internal LangGraph state types
#
# Each agent owns a private TypedDict so no agent depends on fields owned by
# another. The DB adapter is held by SessionContext, never serialized into Band.
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict, total=False):
    """Internal state for the Query Orchestrator's LangGraph subgraph."""
    question: str
    session_id: str
    trace_id: str

    # LLM outputs (merged call)
    is_clear: bool
    clarification_message: str
    clarification_count: int
    normalized_question: str
    subtasks: list[str]
    complexity: str
    query_pattern: str
    execution_mode: str

    # Schema grounding
    full_schema_cache: str
    relevant_tables: list[str]
    relevant_columns: dict[str, list[str]]

    # Verification
    verification_passed: bool
    verification_attempts: int

    error: str
    metadata: dict[str, Any]


class SQLEngineerState(TypedDict, total=False):
    """Internal state for the SQL Engineer's LangGraph subgraph."""
    session_id: str
    trace_id: str
    normalized_question: str
    subtasks: list[str]
    relevant_tables: list[str]
    relevant_columns: dict[str, list[str]]

    refined_schema_str: str
    sql_query: str
    generation_attempt: int
    revision_hint: str            # populated on revision path

    execution_status: str         # "success" | "error"
    error_message: str
    result_columns: list[str]
    result_rows: list[tuple[Any, ...]]
    result_row_count: int

    model_used: str
    error: str
    metadata: dict[str, Any]


class ReportingState(TypedDict, total=False):
    """Internal state for the Reporting Agent."""
    session_id: str
    trace_id: str
    normalized_question: str
    result_columns: list[str]
    result_rows: list[dict[str, Any]]

    needs_visualization: bool
    chart_type: str
    visualization_params: dict[str, Any]
    chart_spec_ref: str
    narrative_summary: str

    error: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class TableColumnSelection:
    """Verified table + column selection produced by the Orchestrator."""
    table: str
    columns: list[str] = field(default_factory=list)
