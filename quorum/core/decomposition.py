"""
core/decomposition.py — Engine-agnostic factor attribution.

Decomposes the gap in a metric between two slices (A vs B) into independent,
reconciling factors, then attributes each factor's contribution by sequential
attribution (hold all factors, step one at a time to A's level). Factor shares
reconcile to the total gap up to a small interaction residual that is reported,
not hidden.

There is NO hardcoded schema here. A FactorModel supplies:
  - the metric scalar expression (e.g. "SUM(amount)"),
  - the FROM/JOIN clause over the fact,
  - an ordered list of factor expressions whose product equals the metric.

Two ways a model is obtained (see core/investigation.py):
  1. Catalog-defined: declared in metric_catalog.yaml for a certified metric.
  2. Generic fallback: any additive metric decomposes into
        volume (COUNT(*))  x  intensity (metric / COUNT(*))
     which reconciles exactly on any database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from math import prod
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model specification
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FactorSpec:
    key: str
    label: str
    expr: str               # SQL scalar expression evaluated over the sliced fact
    question: str = ""       # human-readable "did this factor differ?"


@dataclass(slots=True)
class FactorModel:
    """A multiplicative decomposition of one metric. product(factors)==metric."""
    metric: str
    metric_expr: str
    from_sql: str           # "FROM fact f [JOIN ...]"
    factors: list[FactorSpec]
    certified: bool = False


# ---------------------------------------------------------------------------
# Measurement + attribution results
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SliceMeasure:
    label: str
    metric_value: float = 0.0
    factor_values: dict[str, float] = field(default_factory=dict)

    def reconstructed(self, keys: list[str]) -> float:
        return prod(self.factor_values.get(k, 0.0) for k in keys) if keys else 0.0


@dataclass(slots=True)
class FactorContribution:
    factor: str
    label: str
    a_value: float
    b_value: float
    direction: str          # "higher" | "lower" | "equal" (A relative to B)
    contribution: float     # units of the gap explained by this factor
    explained_share: float  # fraction of the total gap
    verdict: str            # "primary" | "contributing" | "ruled_out"
    confidence: str         # "high" | "medium" | "low"
    question: str = ""


@dataclass(slots=True)
class DecompositionResult:
    slice_a: SliceMeasure
    slice_b: SliceMeasure
    gap: float
    contributions: list[FactorContribution] = field(default_factory=list)
    residual_share: float = 0.0

    def ranked(self) -> list[FactorContribution]:
        return sorted(self.contributions, key=lambda c: abs(c.explained_share), reverse=True)


# ---------------------------------------------------------------------------
# Generic model builder (no catalog needed)
# ---------------------------------------------------------------------------

def generic_factor_model(metric: str, metric_expr: str, from_sql: str) -> FactorModel:
    """Volume x intensity decomposition that reconciles on any database."""
    return FactorModel(
        metric=metric,
        metric_expr=metric_expr,
        from_sql=from_sql,
        factors=[
            FactorSpec("volume", "Volume", "COUNT(*)",
                       "Did the number of records differ?"),
            FactorSpec("intensity", "Average per record",
                       f"({metric_expr}) * 1.0 / NULLIF(COUNT(*), 0)",
                       "Was the average value per record different?"),
        ],
        certified=False,
    )


# ---------------------------------------------------------------------------
# Measuring one slice
# ---------------------------------------------------------------------------

def measure_slice(adapter, model: FactorModel, *, where_sql: str, label: str) -> SliceMeasure:
    base = f"{model.from_sql} WHERE {where_sql}"
    metric_value = _scalar(adapter, f"SELECT {model.metric_expr} {base}") or 0.0
    fv: dict[str, float] = {}
    for fac in model.factors:
        fv[fac.key] = float(_scalar(adapter, f"SELECT {fac.expr} {base}") or 0.0)
    return SliceMeasure(label=label, metric_value=float(metric_value), factor_values=fv)


# ---------------------------------------------------------------------------
# Sequential attribution over N factors
# ---------------------------------------------------------------------------

def attribute(a: SliceMeasure, b: SliceMeasure, model: FactorModel) -> DecompositionResult:
    keys = [f.key for f in model.factors]
    gap = a.metric_value - b.metric_value

    cur = [b.factor_values.get(k, 0.0) for k in keys]
    running = prod(cur) if cur else 0.0
    raw: dict[str, float] = {}
    for i, k in enumerate(keys):
        cur[i] = a.factor_values.get(k, 0.0)
        new_prod = prod(cur) if cur else 0.0
        raw[k] = new_prod - running
        running = new_prod

    explained = sum(raw.values())
    residual = gap - explained
    residual_share = (residual / gap) if abs(gap) > 1e-9 else 0.0

    label_by = {f.key: f.label for f in model.factors}
    question_by = {f.key: f.question for f in model.factors}
    contribs: list[FactorContribution] = []
    for k in keys:
        contrib = raw[k]
        share = (contrib / gap) if abs(gap) > 1e-9 else 0.0
        a_val, b_val = a.factor_values.get(k, 0.0), b.factor_values.get(k, 0.0)
        if abs(a_val - b_val) < 1e-9:
            direction = "equal"
        else:
            direction = "higher" if a_val > b_val else "lower"
        contribs.append(FactorContribution(
            factor=k, label=label_by[k], a_value=a_val, b_value=b_val,
            direction=direction, contribution=contrib, explained_share=share,
            verdict=_verdict(share), confidence=_confidence(share, direction),
            question=question_by.get(k, ""),
        ))

    return DecompositionResult(slice_a=a, slice_b=b, gap=gap,
                               contributions=contribs, residual_share=residual_share)


def _verdict(share: float) -> str:
    s = abs(share)
    if s >= 0.40:
        return "primary"
    if s >= 0.15:
        return "contributing"
    return "ruled_out"


def _confidence(share: float, direction: str) -> str:
    s = abs(share)
    if direction == "equal":
        return "high"
    if s >= 0.40 or s < 0.05:
        return "high"
    if s >= 0.15:
        return "medium"
    return "medium"


def _scalar(adapter, sql: str):
    rows, _ = adapter.execute_query(sql, 1)
    if not rows:
        return None
    first = rows[0]
    if isinstance(first, dict):
        return list(first.values())[0]
    return first[0]
