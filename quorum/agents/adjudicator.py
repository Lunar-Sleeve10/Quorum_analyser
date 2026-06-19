"""
agents/adjudicator.py — Adjudicator (join barrier + verdict).

Waits for all factor investigators (the join), assembles their findings into
slice vectors, attributes the gap by sequential decomposition, and produces the
ranked board verdict. The judgment is computed deterministically; an optional
single LLM call only rephrases the headline into business language.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import LLMProvider, settings
from core.investigation import (
    Investigation, adjudicate_from_factor_values, build_record, measure_metric,
)
from core.llm_router import LLMError, LLMRouter, router as default_router

logger = logging.getLogger(__name__)


class AdjudicatorAgent:
    role = "adjudicator"

    def __init__(self, *, llm_router: Optional[LLMRouter] = None) -> None:
        self.router = llm_router or default_router

    def adjudicate(self, adapter, inv: Investigation, findings: dict,
                   *, narrate: bool = False) -> dict:
        metric_a, metric_b = measure_metric(adapter, inv)
        verdict, decomp = adjudicate_from_factor_values(
            inv, findings, metric_a=metric_a, metric_b=metric_b)
        record = build_record(inv, verdict, decomp)
        if narrate:
            try:
                record["headline"] = self._narrate(record) or record["headline"]
            except LLMError as exc:
                logger.warning("adjudicator narration failed: %s", exc)
        return record

    def _narrate(self, record: dict) -> str:
        prompt = (
            "Rephrase this analytics board verdict as ONE crisp executive sentence. "
            "Keep the numbers exact; no preamble.\n\n"
            f"Question: {record['normalized_question']}\n"
            f"Gap: {record['gap']} ({record['a_label']} vs {record['b_label']})\n"
            f"Primary driver: {record.get('primary_factor')}\n"
            f"Headline: {record['headline']}"
        )
        resp = self.router.complete(
            provider=settings.provider_for("adjudicator"),
            model=settings.model_for("adjudicator"), prompt=prompt, max_tokens=180)
        return (resp.content or "").strip().split("\n")[0]
