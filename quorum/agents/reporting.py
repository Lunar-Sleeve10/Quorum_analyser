"""
agents/reporting.py — Visualization & Reporting agent (fourth/final business agent).

Consumes the Reviewer's ValidatedResult and produces a broadcast FinalReport.

Chart selection is fully deterministic (no LLM). Rules, in precedence:
  1. time series                                -> line chart
  2. ranking                                    -> bar chart
  3. comparison                                 -> bar chart
  4. share / distribution with <= 8 categories  -> pie chart
  5. otherwise                                  -> table (no chart)

The only LLM call is a single optional executive summary (3-5 bullets); on any
failure or when no usable data exists, a deterministic summary is produced.

The rendered Plotly figure plus visualization metadata are stored as a
SessionContext artifact; FinalReport carries only chart_spec_ref, never an
inlined chart object. Full plotting data is re-fetched deterministically via the
SessionContext adapter (the SQLResult carries only a small capped sample).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from agents.base import BaseAgent
from pipeline.models import FinalReport, ValidatedResult, make_envelope
from pipeline.session_context import SessionContext, context_store
from config import BandConfig, ChartType, LLMProvider, settings
from core.database import DatabaseAdapter
from core.llm_router import LLMError, LLMRouter

logger = logging.getLogger(__name__)

_TIME_KEYWORDS = ("date", "time", "year", "month", "day", "quarter", "week")
_PIE_MAX_CATEGORIES = 8
_HBAR_MIN_CATEGORIES = 11
_MAX_SUMMARY_BULLETS = 5


@dataclass(slots=True)
class _ChartDecision:
    chart_type: Optional[ChartType]   # None => table / no chart
    rule: str = "table"
    x: Optional[str] = None
    y: Optional[str] = None
    label_col: Optional[str] = None
    value_col: Optional[str] = None


class VisualizationReportingAgent(BaseAgent[ValidatedResult, FinalReport]):
    role = "reporting_agent"

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
            provider=provider or settings.reporting_provider,
            model=model or settings.reporting_model,
            llm_router=llm_router,
            telemetry=telemetry,
            agent_id=agent_id,
        )

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def _run(self, message: ValidatedResult) -> FinalReport:
        ctx = context_store.get(message.envelope.session_id)
        df, decision, chart_ref = self._prepare_visual(message, ctx)
        summary, method = self._generate_summary(message, ctx, df, decision)
        return self._compose_report(message, ctx, decision, chart_ref, summary, method)

    async def _arun(self, message: ValidatedResult) -> FinalReport:
        ctx = context_store.get(message.envelope.session_id)
        df, decision, chart_ref = self._prepare_visual(message, ctx)
        summary, method = await self._agenerate_summary(message, ctx, df, decision)
        return self._compose_report(message, ctx, decision, chart_ref, summary, method)

    # ------------------------------------------------------------------
    # Deterministic visualization preparation (no LLM)
    # ------------------------------------------------------------------

    def _prepare_visual(
        self, message: ValidatedResult, ctx: SessionContext
    ) -> tuple[Optional[pd.DataFrame], _ChartDecision, Optional[str]]:
        session_id = message.envelope.session_id
        df = self._load_dataframe(message, ctx)

        if df is None or df.empty:
            decision = _ChartDecision(chart_type=None, rule="table")
            self._emit_event(session_id, "chart_selected",
                             {"chart_type": "table", "rule": decision.rule})
            return df, decision, None

        decision = self._select_chart(df, (ctx.query_pattern or "").lower())
        self._emit_event(
            session_id, "chart_selected",
            {
                "chart_type": decision.chart_type.value if decision.chart_type else "table",
                "rule": decision.rule,
            },
        )

        if decision.chart_type is None:
            return df, decision, None

        try:
            fig = self._build_figure(df, decision, ctx)
        except Exception as exc:
            logger.warning("Figure build failed, falling back to table: %s", exc)
            decision = _ChartDecision(chart_type=None, rule="table")
            return df, decision, None

        viz_meta = self._viz_metadata(df, decision)
        chart_ref = ctx.put_artifact(
            "chart",
            {"figure": fig, "spec": fig.to_dict(), "metadata": viz_meta},
        )
        return df, decision, chart_ref

    def _load_dataframe(
        self, message: ValidatedResult, ctx: SessionContext
    ) -> Optional[pd.DataFrame]:
        sql_result = message.sql_result
        if sql_result.execution_status != "success" or sql_result.result_row_count == 0:
            return None
        if ctx.adapter is None:
            if sql_result.result_sample:
                return self._coerce(pd.DataFrame(sql_result.result_sample))
            return None
        adapter: DatabaseAdapter = ctx.adapter
        max_rows = ctx.db_config.max_rows if ctx.db_config else settings.db_max_rows
        try:
            rows, columns = adapter.execute_query(sql_result.sql_query, max_rows)
        except Exception as exc:
            logger.warning("Re-execution for plotting failed: %s", exc)
            if sql_result.result_sample:
                return self._coerce(pd.DataFrame(sql_result.result_sample))
            return None
        if not rows:
            return None
        return self._coerce(pd.DataFrame(rows, columns=columns))

    @staticmethod
    def _coerce(df: pd.DataFrame) -> pd.DataFrame:
        for col in df.columns:
            if df[col].dtype == object:
                converted = pd.to_numeric(df[col], errors="coerce")
                if converted.notna().all():
                    df[col] = converted
        return df

    # ------------------------------------------------------------------
    # Deterministic chart rules
    # ------------------------------------------------------------------

    def _select_chart(self, df: pd.DataFrame, pattern: str) -> _ChartDecision:
        numeric, categorical, temporal = self._classify_columns(df)

        if not numeric:
            return _ChartDecision(chart_type=None, rule="table")

        # 1. Time series -> line
        if temporal or pattern == "trend":
            x = temporal[0] if temporal else (categorical[0] if categorical else None)
            if x is not None:
                return _ChartDecision(ChartType.LINE, "time_series", x=x, y=numeric[0])

        # 2 & 3. Ranking / comparison -> bar
        if pattern in {"ranking", "comparison"} and categorical:
            n = int(df[categorical[0]].nunique())
            chart = ChartType.HORIZONTAL_BAR if n >= _HBAR_MIN_CATEGORIES else ChartType.BAR
            return _ChartDecision(chart, pattern, x=categorical[0], y=numeric[0])

        # 4. Share / distribution with <= 8 categories -> pie
        if pattern in {"share", "distribution"} and categorical:
            n = int(df[categorical[0]].nunique())
            if 0 < n <= _PIE_MAX_CATEGORIES:
                return _ChartDecision(
                    ChartType.PIE, "share_distribution",
                    label_col=categorical[0], value_col=numeric[0],
                )

        # 5. Otherwise -> table
        return _ChartDecision(chart_type=None, rule="table")

    def _classify_columns(
        self, df: pd.DataFrame
    ) -> tuple[list[str], list[str], list[str]]:
        numeric: list[str] = []
        categorical: list[str] = []
        temporal: list[str] = []
        for col in df.columns:
            name = str(col).lower()
            is_time_name = any(k in name for k in _TIME_KEYWORDS)
            if pd.api.types.is_numeric_dtype(df[col]):
                if is_time_name and df[col].nunique() > 1:
                    temporal.append(col)
                else:
                    numeric.append(col)
            elif pd.api.types.is_datetime64_any_dtype(df[col]):
                temporal.append(col)
            elif is_time_name:
                temporal.append(col)
            else:
                categorical.append(col)
        return numeric, categorical, temporal

    # ------------------------------------------------------------------
    # Figure construction
    # ------------------------------------------------------------------

    def _build_figure(
        self, df: pd.DataFrame, decision: _ChartDecision, ctx: SessionContext
    ) -> go.Figure:
        title = self._title_for(ctx)
        chart = decision.chart_type
        fig: go.Figure

        if chart == ChartType.PIE:
            fig = go.Figure(data=[go.Pie(
                labels=df[decision.label_col], values=df[decision.value_col],
                hole=0.3, textinfo="label+percent",
                marker=dict(line=dict(color="white", width=2)),
            )])
            fig.update_layout(title=title, showlegend=True)

        elif chart in (ChartType.BAR, ChartType.HORIZONTAL_BAR):
            horizontal = chart == ChartType.HORIZONTAL_BAR
            x_data = df[decision.y] if horizontal else df[decision.x]
            y_data = df[decision.x] if horizontal else df[decision.y]
            fig = go.Figure(data=[go.Bar(
                x=x_data, y=y_data, orientation="h" if horizontal else "v",
                marker=dict(color=df[decision.y], colorscale="Viridis",
                            line=dict(color="rgba(0,0,0,0.3)", width=1)),
            )])
            fig.update_layout(
                title=title,
                xaxis=dict(title=self._label(decision.y if horizontal else decision.x)),
                yaxis=dict(title=self._label(decision.x if horizontal else decision.y)),
            )

        elif chart == ChartType.LINE:
            fig = go.Figure(data=[go.Scatter(
                x=df[decision.x], y=df[decision.y], mode="lines+markers",
                line=dict(width=3), marker=dict(size=8),
            )])
            fig.update_layout(
                title=title,
                xaxis=dict(title=self._label(decision.x)),
                yaxis=dict(title=self._label(decision.y)),
                hovermode="x unified",
            )
        else:  # pragma: no cover
            fig = px.bar(df, title=title)

        fig.update_layout(
            template="plotly_white", height=520,
            font=dict(family="Arial, sans-serif", size=12),
            margin=dict(l=70, r=70, t=90, b=70),
        )
        return fig

    def _viz_metadata(self, df: pd.DataFrame, decision: _ChartDecision) -> dict[str, Any]:
        return {
            "chart_type": decision.chart_type.value if decision.chart_type else "table",
            "rule_applied": decision.rule,
            "x": decision.x,
            "y": decision.y,
            "label_col": decision.label_col,
            "value_col": decision.value_col,
            "row_count": int(len(df)),
            "columns": [str(c) for c in df.columns],
        }

    @staticmethod
    def _label(col: Optional[str]) -> str:
        return str(col).replace("_", " ").title() if col else ""

    @staticmethod
    def _title_for(ctx: SessionContext) -> str:
        q = ctx.normalized_question.strip()
        return q[:80] if q else "Analysis Results"

    # ------------------------------------------------------------------
    # Executive summary (single optional LLM call, 3-5 bullets)
    # ------------------------------------------------------------------

    def _generate_summary(
        self, message: ValidatedResult, ctx: SessionContext,
        df: Optional[pd.DataFrame], decision: _ChartDecision,
    ) -> tuple[str, str]:
        if not self._should_use_llm(message, df):
            text = self._fallback_summary(message, df, decision)
            self._emit_event(message.envelope.session_id, "summary_generated",
                             {"method": "deterministic"})
            return text, "deterministic"
        try:
            resp = self.call_llm(
                session_id=message.envelope.session_id,
                prompt=self._summary_prompt(message, ctx, df, decision),
            )
            text = self._clean_decision_text(resp.content) or self._fallback_summary(
                message, df, decision)
            method = "llm" if resp.content.strip() else "deterministic"
        except LLMError as exc:
            logger.warning("Summary LLM failed, using deterministic summary: %s", exc)
            text = self._fallback_summary(message, df, decision)
            method = "deterministic"
        self._emit_event(message.envelope.session_id, "summary_generated",
                         {"method": method})
        return text, method

    async def _agenerate_summary(
        self, message: ValidatedResult, ctx: SessionContext,
        df: Optional[pd.DataFrame], decision: _ChartDecision,
    ) -> tuple[str, str]:
        if not self._should_use_llm(message, df):
            text = self._fallback_summary(message, df, decision)
            self._emit_event(message.envelope.session_id, "summary_generated",
                             {"method": "deterministic"})
            return text, "deterministic"
        try:
            resp = await self.acall_llm(
                session_id=message.envelope.session_id,
                prompt=self._summary_prompt(message, ctx, df, decision),
            )
            text = self._clean_decision_text(resp.content) or self._fallback_summary(
                message, df, decision)
            method = "llm" if resp.content.strip() else "deterministic"
        except LLMError as exc:
            logger.warning("Summary LLM failed, using deterministic summary: %s", exc)
            text = self._fallback_summary(message, df, decision)
            method = "deterministic"
        self._emit_event(message.envelope.session_id, "summary_generated",
                         {"method": method})
        return text, method

    def _should_use_llm(
        self, message: ValidatedResult, df: Optional[pd.DataFrame]
    ) -> bool:
        if message.sql_result.execution_status != "success":
            return False
        if df is None or df.empty:
            return False
        if self.provider == LLMProvider.OLLAMA:
            return True
        return bool(settings.api_key_for(self.provider))

    def _summary_prompt(
        self, message: ValidatedResult, ctx: SessionContext,
        df: Optional[pd.DataFrame], decision: _ChartDecision,
    ) -> str:
        sql_result = message.sql_result
        sample = json.dumps(sql_result.result_sample[:10], default=str)[:1600]
        chart_label = decision.chart_type.value if decision.chart_type else "table"
        notes = "; ".join(message.data_quality_notes[:3])
        return f"""You are a senior data analyst writing the analysis section of an
executive report. Produce a substantive, specific analysis of the query result
below — not a one-line description.

Write these four labeled sections. FINDING, IMPLICATION and ANALYSIS must each be
2-4 full sentences; ACTION may be 1-3 sentences. Ground every claim in concrete
numbers from the data: cite exact values, the leading and trailing items, the
gap between the top result and the rest, totals/shares, and any notable
concentration, spread, or outliers. Do NOT invent data and never inflate
magnitudes (e.g. never turn 138.60 into "138 million"). Use only what the data
supports.

FINDING: <the key quantified results — what stands out, the top value(s), how far ahead the leader is, any concentration or even spread across rows>
IMPLICATION: <what this means for the business and why it matters; connect the numbers to a concrete decision context>
ACTION: <specific, prioritized next step(s) with brief rationale tied to the finding>
ANALYSIS: <a cohesive paragraph that synthesizes the above into a clear narrative a decision-maker can act on>

Question: {ctx.normalized_question}
Query pattern: {ctx.query_pattern}
Columns: {sql_result.result_columns}
Row count: {sql_result.result_row_count}
Chart chosen: {chart_label}
Sample rows: {sample}
Data quality notes: {notes}"""

    @staticmethod
    def _normalize_bullets(content: str) -> str:
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        bullets: list[str] = []
        for ln in lines:
            if ln[0] in "-*\u2022":
                ln = "- " + ln.lstrip("-*\u2022 ").strip()
            else:
                ln = "- " + ln
            bullets.append(ln)
            if len(bullets) >= _MAX_SUMMARY_BULLETS:
                break
        return "\n".join(bullets)

    @staticmethod
    def _clean_decision_text(content: str) -> str:
        """Keep the labeled, possibly multi-line analysis as-is. Drops any
        preamble before the first label; falls back to the trimmed text when no
        labels are present."""
        labels = ("FINDING:", "IMPLICATION:", "ACTION:", "ANALYSIS:", "SUMMARY:")
        text = (content or "").strip()
        if not text:
            return ""
        lines = text.splitlines()
        start = next((i for i, ln in enumerate(lines)
                      if ln.strip().upper().startswith(labels)), None)
        if start is None:
            return text
        return "\n".join(lines[start:]).strip()

    @staticmethod
    def _parse_decision(text: str) -> dict:
        """Extract decision fields from labeled summary text. Content for a label
        may span multiple lines (until the next label)."""
        label_map = {
            "FINDING": "finding",
            "IMPLICATION": "implication",
            "ACTION": "recommended_action",
            "ANALYSIS": "narrative",
            "SUMMARY": "recap",
        }
        out = {v: "" for v in label_map.values()}
        buf: dict[str, list[str]] = {v: [] for v in label_map.values()}
        current: Optional[str] = None
        for ln in (text or "").splitlines():
            s = ln.strip()
            if not s:
                continue
            matched = False
            for lab, key in label_map.items():
                if s.upper().startswith(lab + ":"):
                    buf[key].append(s.split(":", 1)[1].strip())
                    current = key
                    matched = True
                    break
            if not matched and current is not None:
                buf[current].append(s)
        for key, parts in buf.items():
            out[key] = " ".join(p for p in parts if p).strip()
        return out

    def _decision_fields(self, summary: str, sql_result) -> dict:
        """Derive the Decision Advisor + governance fields for the FinalReport."""
        parsed = self._parse_decision(summary)
        est = getattr(sql_result, "cost_estimate", None)

        # Risk + approval: driven by the Cost Sentinel's estimate when present.
        risk = "low"
        approval = False
        if est is not None:
            risk = est.risk_level
            # High cost/risk or out-of-budget queries need human sign-off.
            approval = (est.risk_level == "high") or (not est.within_budget)

        cost_model = None
        if est is not None:
            try:
                cost_model = est.model_copy()
            except Exception:
                cost_model = est

        return {
            "finding": parsed.get("finding", ""),
            "implication": parsed.get("implication", ""),
            "recommended_action": parsed.get("recommended_action", ""),
            "approval_required": approval,
            "risk_level": risk,
            "cost_estimate": cost_model,
        }

    def _fallback_summary(
        self, message: ValidatedResult, df: Optional[pd.DataFrame],
        decision: _ChartDecision,
    ) -> str:
        sql_result = message.sql_result
        if sql_result.execution_status != "success":
            err = sql_result.error_message or "no usable result"
            return (
                f"FINDING: The query did not return a usable result ({err}).\n"
                f"IMPLICATION: No reliable answer can be given for this question yet.\n"
                f"ACTION: Revise the query or clarify the question, then re-run.\n"
                f"SUMMARY: The request could not be completed as asked."
            )

        cols = sql_result.result_columns
        n = sql_result.result_row_count
        chart_label = decision.chart_type.value if decision.chart_type else "table"
        ycol = decision.y or decision.value_col
        label_col = decision.x or decision.label_col
        finding = f"The query returned {n} row(s) across {len(cols)} field(s): {', '.join(cols)}."
        analysis = f"The result set has {n} row(s); see the {chart_label} for the full distribution."
        action = (f"Review the {chart_label} and confirm it answers the question; "
                  f"drill into specific segments if needed.")
        try:
            if df is not None and not df.empty and ycol and ycol in df.columns:
                s = pd.to_numeric(df[ycol], errors="coerce").dropna()
                if not s.empty:
                    total = float(s.sum())
                    top_val = float(s.max())
                    share = (top_val / total * 100.0) if total else 0.0
                    ylabel = self._label(ycol)
                    if label_col and label_col in df.columns:
                        top_name = df.loc[s.idxmax(), label_col]
                        ordered = df.assign(_v=s).sort_values("_v", ascending=False)
                        gap = ""
                        if len(ordered) >= 2 and float(ordered.iloc[1]["_v"]):
                            sv = float(ordered.iloc[1]["_v"])
                            gap = (f" — {top_val/sv:.1f}x the next item "
                                   f"({ordered.iloc[1][label_col]}, {sv:,.2f})")
                        finding = (f"{top_name} leads {ylabel} with {top_val:,.2f}, "
                                   f"{share:.0f}% of the {total:,.2f} total across {n} rows{gap}.")
                        spread = "concentrated in" if share >= 40 else "led by"
                        analysis = (f"Across {n} rows, {ylabel} is {spread} {top_name} "
                                    f"({top_val:,.2f} of {total:,.2f} total). "
                                    f"The {chart_label} shows how the remaining items compare.")
                        action = (f"Prioritize {top_name} given its share of {ylabel}; "
                                  f"investigate what drives the gap to the rest.")
                    else:
                        finding = f"Peak {ylabel} is {top_val:,.2f} (total {total:,.2f}) across {n} rows."
        except Exception:
            pass

        note = message.data_quality_notes[0] if message.data_quality_notes else "Data passed quality checks."
        return (
            f"FINDING: {finding}\n"
            f"IMPLICATION: {note}\n"
            f"ACTION: {action}\n"
            f"ANALYSIS: {analysis}"
        )

    # ------------------------------------------------------------------
    # FinalReport assembly + reporting metadata write
    # ------------------------------------------------------------------

    def _compose_report(
        self, message: ValidatedResult, ctx: SessionContext,
        decision: _ChartDecision, chart_ref: Optional[str],
        summary: str, summary_method: str,
    ) -> FinalReport:
        sql_result = message.sql_result
        now = datetime.now(timezone.utc)
        total_latency = max(0.0, (now - ctx.created_at).total_seconds())
        revision_occurred = bool(message.revision_applied or ctx.revision_count >= 1)
        parsed = self._parse_decision(summary)
        narrative = parsed.get("narrative") or parsed.get("recap") or summary

        ctx.put_artifact("reporting_metadata", {
            "chart_spec_ref": chart_ref,
            "chart_type": decision.chart_type.value if decision.chart_type else "table",
            "rule_applied": decision.rule,
            "summary_method": summary_method,
            "query_pattern": ctx.query_pattern,
            "complexity": ctx.complexity,
            "row_count": sql_result.result_row_count,
            "generated_at": now.isoformat(),
        })

        report = FinalReport(
            envelope=make_envelope(
                session_id=message.envelope.session_id,
                from_role=self.role,
                channel=BandConfig.CHANNEL_TASKS,
                topic=BandConfig.TOPIC_COMPLETION,
                to_role=None,
                revision_count=message.envelope.revision_count,
            ),
            normalized_question=ctx.normalized_question or "",
            sql_query=sql_result.sql_query,
            result_columns=sql_result.result_columns,
            result_row_count=sql_result.result_row_count,
            chart_type=decision.chart_type,
            chart_spec_ref=chart_ref,
            narrative_summary=narrative,
            total_latency_seconds=round(total_latency, 2),
            llm_call_count=ctx.total_llm_calls(),
            revision_occurred=revision_occurred,
            **self._decision_fields(summary, sql_result),
        )

        self._emit_event(message.envelope.session_id, "report_completed", {
            "chart_type": decision.chart_type.value if decision.chart_type else "table",
            "chart_spec_ref": chart_ref,
            "llm_call_count": report.llm_call_count,
            "revision_occurred": revision_occurred,
        })
        return report

    # ------------------------------------------------------------------
    # Telemetry helper (named events via detail, within AgentEvent contract)
    # ------------------------------------------------------------------

    def _emit_event(self, session_id: str, name: str, detail: dict[str, Any]) -> None:
        payload = {"role": self.role, "event": name}
        payload.update(detail)
        self._emit(session_id, event_type="tool_call", detail=payload)
