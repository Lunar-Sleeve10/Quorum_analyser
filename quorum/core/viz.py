"""
core/viz.py — UI-agnostic visualization helpers.

These functions hold all the logic a front-end needs to turn a stored run into
a visual: re-run the report's SQL, build a chart, and format the decision /
governance panel. They have no dependency on any UI framework, which keeps the
front-end fully swappable on top of the engine.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from config import DatabaseType, settings
from core.database import make_adapter
from models.state import DatabaseConfig

logger = logging.getLogger(__name__)


def run_sql(sql: str) -> pd.DataFrame:
    """Re-execute a report's SQL against the configured database and return a
    DataFrame. The front-end rebuilds the chart from this — no image needs to
    travel from the Band backend."""
    if not sql.strip():
        return pd.DataFrame()
    cfg = DatabaseConfig(
        db_type=DatabaseType.SQLITE,
        connection_string=settings.db_path,
        max_rows=settings.db_max_rows,
        timeout=settings.db_timeout,
        read_only=True,
    )
    adapter = make_adapter(cfg)
    try:
        rows, cols = adapter.execute_query(sql, settings.db_max_rows)
        if not cols:
            return pd.DataFrame()
        return pd.DataFrame([dict(zip(cols, r)) for r in rows], columns=cols)
    finally:
        try:
            adapter.close()
        except Exception:
            pass


def build_chart(df: pd.DataFrame, chart_type: Optional[str], question: str) -> go.Figure:
    if df is None or df.empty:
        return go.Figure()
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cats = [c for c in df.columns if c not in numeric]
    title = (question or "Result")[:80]
    try:
        if chart_type in ("bar", "stacked_bar", "grouped_bar") and numeric and cats:
            return px.bar(df, x=cats[0], y=numeric[0], title=title)
        if chart_type == "horizontal_bar" and numeric and cats:
            return px.bar(df, x=numeric[0], y=cats[0], orientation="h", title=title)
        if chart_type == "line" and numeric:
            x = cats[0] if cats else df.columns[0]
            return px.line(df, x=x, y=numeric[0], title=title, markers=True)
        if chart_type == "scatter" and len(numeric) >= 2:
            return px.scatter(df, x=numeric[0], y=numeric[1], title=title)
        if chart_type == "pie" and numeric and cats:
            return px.pie(df, names=cats[0], values=numeric[0], title=title)
    except Exception as exc:
        logger.warning("chart render failed: %s", exc)
    # Sensible default: a bar if we have a category + measure, else nothing.
    try:
        if numeric and cats:
            return px.bar(df, x=cats[0], y=numeric[0], title=title)
        if len(numeric) >= 2:
            return px.scatter(df, x=numeric[0], y=numeric[1], title=title)
    except Exception:
        pass
    return go.Figure()


def decision_markdown(report: dict) -> str:
    """Format the decision + governance panel as markdown (any markdown surface)."""
    finding = report.get("finding") or ""
    implication = report.get("implication") or ""
    action = report.get("recommended_action") or ""
    risk = report.get("risk_level", "low")
    approval = report.get("approval_required", False)
    est = report.get("cost_estimate") or {}

    lines = [f"### Decision · risk: **{risk}**"]
    if approval:
        lines.append("> ⚠ **APPROVAL REQUIRED** — high-cost/high-risk; needs human sign-off.")
    if finding:
        lines.append(f"**Finding:** {finding}")
    if implication:
        lines.append(f"**Implication:** {implication}")
    if action:
        lines.append(f"**Recommended action:** {action}")
    if est:
        if est.get("estimated_cost_usd") is not None:
            lines.append(
                f"**Cost (pre-execution):** ~${est['estimated_cost_usd']:.2f} "
                f"on {est.get('engine','?')} ({est.get('method','')})"
            )
        elif est.get("estimated_rows_scanned") is not None:
            lines.append(
                f"**Cost (pre-execution):** ~{est['estimated_rows_scanned']} rows scanned "
                f"on {est.get('engine','?')} ({est.get('method','')})"
            )
        for n in est.get("notes", [])[:3]:
            lines.append(f"- {n}")
    lines.append(
        f"**LLM calls:** {report.get('llm_call_count','?')} · "
        f"**Latency:** {report.get('total_latency_seconds','?')}s · "
        f"**Revision:** {'yes' if report.get('revision_occurred') else 'no'}"
    )
    return "\n\n".join(lines)


def investigation_chart(findings: list[dict]) -> "go.Figure":
    """Horizontal bar of each factor's explained share of the gap — the visual
    of who contributed what to the board's verdict."""
    if not findings:
        return go.Figure()
    labels = [f["factor_label"] for f in findings]
    shares = [f["explained_share"] * 100 for f in findings]
    colors = []
    for f in findings:
        v = f["verdict"]
        colors.append("#2563eb" if v == "primary" else
                      "#60a5fa" if v == "contributing" else "#cbd5e1")
    fig = go.Figure(go.Bar(
        x=shares, y=labels, orientation="h",
        marker_color=colors,
        text=[f"{s:.0f}%" for s in shares], textposition="auto",
    ))
    fig.update_layout(
        title="Share of the gap explained by each factor",
        xaxis_title="% of revenue gap", yaxis=dict(autorange="reversed"),
        height=260, margin=dict(l=10, r=10, t=40, b=30),
    )
    return fig


# ---------------------------------------------------------------------------
# Post-execution chart decision (owned by the Governance Guardian)
# ---------------------------------------------------------------------------

_TIME_KEYWORDS = ("date", "time", "year", "month", "day", "quarter", "week")
_PIE_MAX = 8
_HBAR_MIN = 11


def decide_chart(df, pattern: str, needs_viz: bool = True) -> tuple[Optional[str], str]:
    """Decide whether (and how) to chart a result, using REAL post-execution
    data stats. Returns (chart_type | None, human reason). None => table only.

    Made on actual data, not guessed up front: a single value or a single row
    is a number, not a chart; high-cardinality rankings become horizontal bars;
    small share/distribution becomes a pie; time series become a line.
    """
    if df is None or getattr(df, "empty", True):
        return None, "no rows to chart"
    if not needs_viz:
        return None, "question asks for a value, not a visual"

    import pandas as pd
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    cats = [c for c in df.columns if c not in numeric]
    n = len(df)

    if n == 1 or not numeric:
        return None, "single value / no numeric measure — table is clearer"

    p = (pattern or "").lower()
    has_time = any(any(k in str(c).lower() for k in _TIME_KEYWORDS) for c in df.columns)
    if p == "trend" or has_time:
        return "line", "time/trend data → line chart"
    if p in {"ranking", "comparison"} and cats:
        card = int(df[cats[0]].nunique())
        return ("horizontal_bar" if card >= _HBAR_MIN else "bar"), f"{p} over {card} categories → bar"
    if p in {"share", "distribution"} and cats:
        card = int(df[cats[0]].nunique())
        if 0 < card <= _PIE_MAX:
            return "pie", f"share across {card} categories → pie"
    if cats:
        return "bar", "categorical breakdown of a measure → bar"
    return None, "no suitable categorical dimension — table"
