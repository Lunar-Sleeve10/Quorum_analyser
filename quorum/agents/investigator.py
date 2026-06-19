"""
agents/investigator.py — Factor Investigator (diagnostic specialist).

One investigator owns ONE factor. It measures that factor's value for both
slices (A and B) and reports a finding. Deterministic SQL only — zero LLM calls,
which is what lets the diagnostic fan-out scale to many factors without moving
the LLM budget. N investigators run in parallel; the Adjudicator joins them.
"""

from __future__ import annotations

import logging

from core.investigation import Investigation, measure_factor

logger = logging.getLogger(__name__)


class FactorInvestigatorAgent:
    role = "investigator"

    def __init__(self, factor_key: str) -> None:
        self.factor_key = factor_key

    def run(self, adapter, inv: Investigation) -> dict:
        finding = measure_factor(adapter, inv, self.factor_key)
        logger.info("Investigator[%s]: %s=%.2f vs %.2f", self.factor_key,
                    finding["label"], finding["a_value"], finding["b_value"])
        return finding
