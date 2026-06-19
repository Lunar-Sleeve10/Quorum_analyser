"""
core/ui_safety.py — Pure, UI-framework-agnostic helpers for safely turning the
Band room transcript into a human-readable discussion, and for rendering the
AUTHORIZED result without ever executing SQL.

Kept free of Streamlit so it can be unit-tested headlessly. The Streamlit app
imports these and only adds the actual on-screen widgets.

Safety properties enforced here:
  * the raw ```band JSON payload is never surfaced — only vetted summaries;
  * secret-looking text and stack traces are redacted from the visible feed;
  * line length is capped so a long agent message can't break the layout;
  * the UI builds dataframes only from the authorized run-store payload.
"""

from __future__ import annotations

import re
from typing import Any, Optional

BAND_BLOCK = re.compile(r"```band.*?```", re.DOTALL)
_KIND_RE = re.compile(r'"kind"\s*:\s*"([A-Za-z]+)"')
_MENTION_RE = re.compile(r"@([\w.\-/]+)")
# Never surface secrets or stack traces in the visible discussion.
_SECRETISH = re.compile(r"(api[_-]?key|password|secret|token|traceback)", re.I)

# A structured band-payload kind -> safe, human-readable action label.
KIND_LABELS = {
    "RawText": "\U0001F4AC asked a question",
    "SchemaGroundedTask": "\U0001F9E0 grounded the question and handed off the plan",
    "SQLResult": "✍️ wrote and ran the SQL",
    "RevisionRequest": "⚠️ challenged the query and requested a revision",
    "ValidatedResult": "✅ reviewed the result — passed",
    "InvestigationTask": "\U0001F50E dispatched an investigator",
    "InvestigatorFinding": "\U0001F4CA reported a factor finding",
    "BoardDecision": "⚖️ delivered the board verdict",
    "FinalReport": "\U0001F4DD composed the decision report",
}


def kind_of(content: str) -> str:
    m = _KIND_RE.search(content or "")
    return m.group(1) if m else ""


def safe_summary(content: str) -> str:
    """Short, safe one-line summary: strip the band JSON, drop @mentions, hide
    anything secret-looking or stack-trace-like, and cap the length."""
    text = BAND_BLOCK.sub("", content or "").strip()
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    first = _MENTION_RE.sub("", first).strip(" :—-")
    if _SECRETISH.search(first) or "error:" in first.lower():
        return "(internal detail hidden)"
    return first[:160]


def transcript(messages: list[dict]) -> list[dict]:
    """Turn raw room messages into safe, ordered discussion entries:
    {sender, target, label, summary}."""
    entries: list[dict] = []
    for m in messages or []:
        content = m.get("content", "") or ""
        sender = (m.get("sender") or "Agent").split("/")[-1].replace("-", " ").title()
        target = ""
        mt = _MENTION_RE.search(content)
        if mt:
            target = mt.group(1).split("/")[-1].replace("-", " ").title()
        entries.append({
            "sender": sender, "target": target,
            "label": KIND_LABELS.get(kind_of(content), ""),
            "summary": safe_summary(content),
        })
    return entries


def authorized_rows(report: dict) -> Optional[tuple[list, list]]:
    """Return (rows, columns) from the AUTHORIZED run-store payload, or None.
    The UI must use this instead of executing SQL itself (which would bypass
    the Cost Sentinel)."""
    rows = report.get("result_rows")
    cols = report.get("result_columns")
    if not rows or not cols:
        return None
    return rows, cols
