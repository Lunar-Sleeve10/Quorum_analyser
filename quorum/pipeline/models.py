"""
band/models.py — Pydantic v2 message contracts for inter-agent Band messages.

These are the FROZEN message schemas from the approved Band Collaboration
Design. Every inter-agent message carries a MessageEnvelope plus a payload.
Schema text never travels in these messages — only context_ref (the session
id) which agents use to look up SessionContext locally.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from config import ChartType, IssueType, ReviewMethod

# Role identifiers used across the system
Role = Literal[
    "user",
    "orchestrator",
    "planner",
    "supervisor",
    "sql_engineer",
    "sql_analyst",
    "cost_sentinel",
    "reviewer",
    "guardian",
    "reporting_agent",
    "decision_reporter",
    "investigator",
    "adjudicator",
]

Channel = Literal["tasks", "control", "telemetry"]
Topic = Literal["handoff", "review", "revision", "completion", "control", "plan", "investigation"]
Complexity = Literal["simple", "medium", "complex"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Common envelope — embedded in every message
# ---------------------------------------------------------------------------

class MessageEnvelope(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")

    message_id: str = Field(default_factory=_new_id)
    trace_id: str                       # == session_id, constant across flow
    audit_id: str = Field(default_factory=_new_id)
    session_id: str                     # room identifier
    timestamp: datetime = Field(default_factory=_utcnow)
    from_role: Role
    to_role: Optional[Role] = None      # None == broadcast
    channel: Channel
    topic: Topic
    context_ref: str                    # == session_id, key into SessionContext
    revision_count: int = 0             # 0 = first pass, 1 = after one revision


class BandMessage(BaseModel):
    """Base for all message payloads. Carries the envelope."""
    model_config = ConfigDict(extra="forbid")

    envelope: MessageEnvelope


# ---------------------------------------------------------------------------
# Control channel: entry + human-in-the-loop
# ---------------------------------------------------------------------------

class UserQuery(BandMessage):
    question: str
    db_path: str
    db_type: str = "sqlite"
    clarification_count: int = 0
    user_id: Optional[str] = None
    session_started_at: datetime = Field(default_factory=_utcnow)


class ClarificationRequest(BandMessage):
    clarification_message: str
    clarification_count: int


class ClarificationResponse(BandMessage):
    clarified_question: str


# ---------------------------------------------------------------------------
# Tasks channel: the actual agent collaboration
# ---------------------------------------------------------------------------

class TableColumnSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    columns: list[str] = Field(default_factory=list)


class Grounding(BaseModel):
    """
    Orchestrator-derived state that downstream agents need but would otherwise
    live only in the orchestrator's process. Carried inside messages so each
    Band agent (separate process) can hydrate its own SessionContext.
    """
    model_config = ConfigDict(extra="forbid")

    normalized_question: str = ""
    query_pattern: str = ""
    complexity: str = ""
    revision_count: int = 0


class CostEstimate(BaseModel):
    """Pre-execution cost/safety estimate produced by the Cost Sentinel.
    On SQLite this is a scan-plan proxy; on a warehouse (BigQuery) it is a real
    bytes-scanned / dollar estimate from a dry run."""
    model_config = ConfigDict(extra="forbid")

    engine: str = "sqlite"                      # sqlite | bigquery | ...
    estimated_rows_scanned: Optional[int] = None
    estimated_bytes_scanned: Optional[int] = None
    estimated_cost_usd: Optional[float] = None
    full_scan_tables: list[str] = Field(default_factory=list)
    uses_index: bool = True
    risk_level: Literal["low", "medium", "high"] = "low"
    within_budget: bool = True
    notes: list[str] = Field(default_factory=list)
    method: str = "explain_query_plan"          # how it was estimated


class SchemaGroundedTask(BandMessage):
    normalized_question: str
    complexity: Complexity
    query_pattern: str                  # "ranking" | "share" | "comparison" | ...
    selections: list[TableColumnSelection]
    subtasks: list[str] = Field(default_factory=list)
    schema_digest_ref: str              # key into shared schema cache, not schema


class SQLResult(BandMessage):
    sql_query: str
    execution_status: Literal["success", "error"]
    error_message: Optional[str] = None
    result_columns: list[str] = Field(default_factory=list)
    result_row_count: int = 0
    result_sample: list[dict[str, Any]] = Field(default_factory=list)  # capped
    model_used: str
    generation_attempt: int = 1
    grounding: Optional[Grounding] = None   # carried for cross-process hydration
    cost_estimate: Optional[CostEstimate] = None  # set by Cost Sentinel


class ReviewRequest(BandMessage):
    """Thin semantic wrapper. SQLResult IS the review request in practice."""
    sql_result: SQLResult
    original_question: str
    query_pattern: str
    review_focus: list[str] = Field(
        default_factory=lambda: ["row_count", "null_ratio", "pattern_match"]
    )


class RevisionRequest(BandMessage):
    issue_type: IssueType
    revision_hint: str                  # actionable, specific instruction
    previous_sql: str
    must_succeed: bool = True           # true when revision_count will become 1


class ValidatedResult(BandMessage):
    sql_result: SQLResult
    verdict: Literal["pass"]            # only emitted on pass
    data_quality_notes: list[str] = Field(default_factory=list)
    review_method: ReviewMethod
    revision_applied: bool = False
    grounding: Optional[Grounding] = None   # carried for cross-process hydration


class FinalReport(BandMessage):
    normalized_question: str
    sql_query: str
    result_columns: list[str]
    result_row_count: int
    chart_type: Optional[ChartType] = None
    chart_spec_ref: Optional[str] = None   # reference, not inlined figure JSON
    narrative_summary: str
    total_latency_seconds: float
    llm_call_count: int
    revision_occurred: bool = False
    # --- Decision intelligence (Decision Advisor) ---
    # Elevates the output from "here is a number" to "here is a finding, what it
    # means, what to do, and whether sign-off is required."
    finding: str = ""                         # the headline fact
    implication: str = ""                      # what it means for the business
    recommended_action: str = ""               # the suggested next step
    approval_required: bool = False            # does this need human sign-off?
    risk_level: Literal["low", "medium", "high"] = "low"
    # --- Governance metadata ---
    metric_definitions_used: list[str] = Field(default_factory=list)
    cost_estimate: Optional["CostEstimate"] = None
    audit_ref: Optional[str] = None


# ---------------------------------------------------------------------------
# Telemetry channel
# ---------------------------------------------------------------------------

class AgentEvent(BandMessage):
    event_type: Literal[
        "task_started", "task_completed", "llm_call", "tool_call", "error"
    ]
    role: Role
    detail: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Presence / discovery (system:registry room)
# ---------------------------------------------------------------------------

class Presence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role
    agent_id: str
    status: Literal["online", "offline", "busy"] = "online"
    model_backend: str
    announced_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Control-flow terminal signals
# ---------------------------------------------------------------------------

class FlowComplete(BandMessage):
    final_report_ref: str


class FlowError(BandMessage):
    error_message: str
    failed_role: Role
    recoverable: bool = False


# ---------------------------------------------------------------------------
# Envelope factory — reduces boilerplate when agents construct messages
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Investigation Mode: fork/join review board (causal "why" questions)
# ---------------------------------------------------------------------------

class ComparisonSpec(BaseModel):
    """What two slices the investigation compares (A vs B)."""
    model_config = ConfigDict(extra="forbid")

    dimension: str                       # e.g. "genre", "country"
    a_label: str
    b_label: str
    a_where: str                         # SQL predicate for slice A
    b_where: str
    joins: str = ""                      # extra joins (e.g. Track/Genre)


class InvestigationTask(BandMessage):
    """Chief of Staff -> investigators: the question + the slices to compare.
    Each investigator owns ONE factor (assigned, not chosen)."""
    investigation_id: str
    question: str
    comparison: ComparisonSpec
    factors: list[str] = Field(default_factory=list)   # which factors are in play
    inv: dict[str, Any] = Field(default_factory=dict)  # serialized Investigation


class InvestigatorFinding(BandMessage):
    """One investigator -> the board: an independent, factor-scoped verdict."""
    investigation_id: str
    question: str = ""                   # carried so the adjudicator (separate
    total_factors: int = 0               # process) can rebuild + know the join size
    inv: dict[str, Any] = Field(default_factory=dict)  # serialized Investigation
    factor: str                          # the factor this investigator owns
    factor_label: str
    a_value: float
    b_value: float
    direction: str                       # higher | lower | equal
    contribution: float                  # dollars of gap explained
    explained_share: float
    verdict: str                         # primary | contributing | ruled_out
    confidence: str
    evidence: str = ""                   # short human-readable evidence line


class BoardDecision(BandMessage):
    """Decision Advisor -> human: the adjudicated review-board verdict."""
    investigation_id: str
    question: str
    a_label: str
    b_label: str
    gap: float
    headline: str
    primary_factor: Optional[str] = None
    ranked_factors: list[dict[str, Any]] = Field(default_factory=list)
    ruled_out: list[str] = Field(default_factory=list)
    residual_share: float = 0.0
    confidence: str = "medium"
    conflict_note: str = ""
    concentration_note: str = ""
    recommendation: str = ""


def make_envelope(
    *,
    session_id: str,
    from_role: Role,
    channel: Channel,
    topic: Topic,
    to_role: Optional[Role] = None,
    revision_count: int = 0,
) -> MessageEnvelope:
    """Construct an envelope with trace_id and context_ref bound to session_id."""
    return MessageEnvelope(
        trace_id=session_id,
        session_id=session_id,
        context_ref=session_id,
        from_role=from_role,
        to_role=to_role,
        channel=channel,
        topic=topic,
        revision_count=revision_count,
    )


# Resolve forward reference of CostEstimate inside FinalReport
FinalReport.model_rebuild()
