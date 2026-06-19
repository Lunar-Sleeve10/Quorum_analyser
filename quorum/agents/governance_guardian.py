"""
agents/governance_guardian.py — Governance Guardian (risk + decision layer).

A post-execution governance specialist that sits after the SQL runs, so its
decisions are made on REAL data statistics:

  - compliance + correctness review (deterministic-first; reuses the certified
    Reviewer checks — empty result, ranking-without-ORDER-BY, top-N-without-
    LIMIT, null-heavy), which can send a bounded revision back to the Analyst;
  - the VISUALIZATION decision, made here (not in Reporting) because only after
    execution do we know row count, cardinality, and column types.

Keeping the viz decision in the Guardian means the chart choice is governed and
travels downstream as a decided spec; the Decision Reporter only renders it.
"""

from __future__ import annotations

import logging
from typing import Optional

from agents.reviewer import InsightsComplianceReviewerAgent
from core.viz import decide_chart

logger = logging.getLogger(__name__)


class GovernanceGuardianAgent:
    role = "guardian"

    def __init__(self, *, llm_router=None, telemetry=None) -> None:
        self._reviewer = InsightsComplianceReviewerAgent(llm_router=llm_router, telemetry=telemetry)

    @property
    def telemetry(self):
        return self._reviewer.telemetry

    @telemetry.setter
    def telemetry(self, value) -> None:
        self._reviewer.telemetry = value

    # Correctness / compliance gate -> ValidatedResult | RevisionRequest
    def review(self, sql_result):
        return self._reviewer.run(sql_result)

    # Visualization decision on real post-execution data.
    def decide_visual(self, df, pattern: str, needs_viz: bool = True) -> tuple[Optional[str], str]:
        chart, reason = decide_chart(df, pattern, needs_viz)
        logger.info("Guardian viz decision: %s (%s)", chart or "table", reason)
        return chart, reason
