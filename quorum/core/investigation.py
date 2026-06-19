"""
core/investigation.py — Diagnostic ("why") classification + investigation builder.

Two jobs, both fully database-agnostic:

1. CLASSIFY whether a question is causal/comparative ("why does A differ from
   B") and DISCOVER, from the live database + semantic catalog, the metric, the
   comparison dimension, and the two slice values — with NO hardcoded vocabulary.

2. BUILD an Investigation: a FactorModel (multiplicative decomposition) plus the
   two slice predicates. Factor models come from the certified catalog when
   present; otherwise a generic volume x intensity model is synthesised, which
   reconciles on any database.

Discovery is transparent (regex causal/comparative gate + SELECT DISTINCT value
matching) rather than an opaque classifier, so the trigger is explainable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.decomposition import (
    DecompositionResult, FactorModel, FactorSpec, attribute,
    generic_factor_model, measure_slice,
)
from core.adjudication import BoardVerdict, adjudicate
from core.parsers import LLMResponseParser

logger = logging.getLogger(__name__)

_CAUSAL = re.compile(
    r"\b(why|what\s+drives?|what\s+caused?|what\s+explains?|reason\s+for|"
    r"driver(s)?\s+of|account\s+for|root\s+cause)\b", re.I)
_COMPARATIVE = re.compile(
    r"\b(more|less|higher|lower|than|compared?\s+to|vs\.?|versus|gap|"
    r"differ|outperform|underperform|behind|ahead|beat|trail)\b", re.I)

_MAX_DISTINCT = 500


@dataclass(slots=True)
class Investigation:
    question: str
    metric: str
    from_sql: str               # FROM/JOIN incl. dimension joins
    a_label: str
    b_label: str
    a_where: str
    b_where: str
    dimension: str
    model: FactorModel

    @property
    def factor_keys(self) -> list[str]:
        return [f.key for f in self.model.factors]


def is_diagnostic(question: str) -> bool:
    return bool(_CAUSAL.search(question) and _COMPARATIVE.search(question))


# ---------------------------------------------------------------------------
# Catalog loading (factor models + comparable dimensions)
# ---------------------------------------------------------------------------

def _load_catalog(path: str | Path) -> dict:
    try:
        import yaml
        p = Path(path)
        if not p.exists():
            return {}
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.warning("catalog load failed: %s", exc)
        return {}


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _distinct_values(adapter, sql: str) -> list[str]:
    try:
        rows, _ = adapter.execute_query(sql, _MAX_DISTINCT)
        out = []
        for r in rows:
            v = list(r.values())[0] if isinstance(r, dict) else r[0]
            if v is not None:
                out.append(str(v))
        return out
    except Exception:
        return []


def _find_two_in_question(question: str, values: list[str]) -> Optional[tuple[str, str]]:
    low = question.lower()
    hits: list[tuple[int, str]] = []
    for v in values:
        if not v:
            continue
        idx = low.find(v.lower())
        if idx >= 0:
            hits.append((idx, v))
    hits.sort()
    seen, ordered = set(), []
    for _, v in hits:
        if v.lower() not in seen:
            seen.add(v.lower())
            ordered.append(v)
    if len(ordered) >= 2:
        return ordered[0], ordered[1]
    return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(adapter, question: str, *, catalog_path: str | Path, router=None) -> Optional[Investigation]:
    """Return an Investigation if the question is diagnostic and two comparable
    slices can be resolved, else None (caller falls back to the descriptive path).

    Resolution order: (1) certified catalog factor model; (2) an LLM-proposed
    factor model that is VALIDATED by reconciliation on the real data (only when
    a router is supplied); (3) the generic volume x intensity model. So a fresh
    database needs no catalog, and a weak model can't push a wrong decomposition
    through — it must reconcile or it falls back."""
    if not is_diagnostic(question):
        return None

    catalog = _load_catalog(catalog_path)
    inv = _discover_from_catalog(adapter, question, catalog)
    if inv is not None:
        return inv
    return _discover_generic(adapter, question, catalog, router=router)


def _build_model(fm: dict, extra_joins: str = "") -> FactorModel:
    from_sql = fm["from_sql"]
    if extra_joins:
        from_sql = f"{from_sql} {extra_joins}"
    factors = [
        FactorSpec(key=f["key"], label=f.get("label", f["key"]),
                   expr=f["expr"], question=f.get("question", ""))
        for f in fm.get("factors", [])
    ]
    return FactorModel(metric=fm.get("metric", "metric"),
                       metric_expr=fm["metric_expr"], from_sql=from_sql,
                       factors=factors, certified=bool(fm.get("certified", False)))


def _discover_from_catalog(adapter, question: str, catalog: dict) -> Optional[Investigation]:
    for fm in catalog.get("factor_models", []) or []:
        for dim in fm.get("dimensions", []) or []:
            values_sql = dim.get("values_sql") or f"SELECT DISTINCT {dim['column']} {fm['from_sql']}"
            values = _distinct_values(adapter, values_sql)
            pair = _find_two_in_question(question, values)
            if not pair:
                continue
            a, b = pair
            col = dim["column"]
            model = _build_model(fm, dim.get("joins", ""))
            return Investigation(
                question=question, metric=fm.get("metric", "metric"),
                from_sql=model.from_sql,
                a_label=a, b_label=b,
                a_where=f"{col}='{_esc(a)}'", b_where=f"{col}='{_esc(b)}'",
                dimension=dim.get("name", col), model=model,
            )
    return None


def _validate_reconciles(adapter, inv: "Investigation", tol: float = 0.15) -> bool:
    """A proposed factor model is trusted only if product(factors) reconciles to
    the metric on the real data for both slices."""
    try:
        a = measure_slice(adapter, inv.model, where_sql=inv.a_where, label=inv.a_label)
        b = measure_slice(adapter, inv.model, where_sql=inv.b_where, label=inv.b_label)
        decomp = attribute(a, b, inv.model)
        return abs(decomp.residual_share) <= tol
    except Exception:
        return False


def _propose_factor_model(router, adapter, *, table, metric_col, col, a, b, question) -> Optional["Investigation"]:
    """Ask the LLM to propose a multiplicative decomposition for the metric over
    this fact table. Returns an Investigation only if it reconciles on the data."""
    from config import settings
    try:
        cols = adapter.get_columns(table)
    except Exception:
        return None
    metric_expr = f"SUM({metric_col})" if metric_col else "COUNT(*)"
    prompt = f"""You are a metrics analyst. Decompose the metric below into 2-4
multiplicative factors whose product EQUALS the metric (factor1 * factor2 * ... = metric).

Fact table: {table}
Columns: {', '.join(cols)}
Metric: {metric_expr}

Return ONLY JSON:
{{"metric_expr": "{metric_expr}",
  "factors": [
    {{"key": "short_key", "label": "Human Label", "expr": "SQL scalar over {table}", "question": "did this differ?"}}
  ]}}
Each expr is a SQL scalar aggregate over {table} only. The product of the factor
exprs must equal metric_expr (e.g. COUNT(DISTINCT x) * (SUM(y)*1.0/COUNT(DISTINCT x)))."""
    try:
        resp = router.complete(provider=settings.provider_for("planner"),
                               model=settings.model_for("planner"), prompt=prompt, max_tokens=500)
        data = LLMResponseParser.extract_json(resp.content)
    except Exception as exc:
        logger.warning("factor-model proposal failed: %s", exc)
        return None
    if not data or not isinstance(data.get("factors"), list) or len(data["factors"]) < 2:
        return None
    try:
        factors = [FactorSpec(key=str(f["key"]), label=f.get("label", f["key"]),
                              expr=str(f["expr"]), question=f.get("question", ""))
                   for f in data["factors"]]
    except Exception:
        return None
    model = FactorModel(metric=(metric_col or "count").lower(),
                        metric_expr=str(data.get("metric_expr", metric_expr)),
                        from_sql=f"FROM {table}", factors=factors, certified=False)
    inv = Investigation(question=question, metric=model.metric, from_sql=model.from_sql,
                        a_label=a, b_label=b, a_where=f"{col}='{_esc(a)}'",
                        b_where=f"{col}='{_esc(b)}'", dimension=col, model=model)
    if _validate_reconciles(adapter, inv):
        logger.info("Using LLM-proposed factor model (validated) for %s", model.metric)
        return inv
    logger.info("LLM-proposed factor model did not reconcile; using generic fallback")
    return None


def _discover_generic(adapter, question: str, catalog: dict, router=None) -> Optional[Investigation]:
    """Single-fact-table fallback: find a categorical column with two values
    named in the question, plus a numeric metric column on the same table."""
    metric_hints = ("amount", "revenue", "sales", "total", "price", "value", "cost")
    try:
        tables = adapter.get_tables()
    except Exception:
        return None

    for table in tables:
        try:
            cols = adapter.get_columns(table)
        except Exception:
            continue
        # candidate metric column (numeric-ish by name)
        metric_col = next((c for c in cols if any(h in c.lower() for h in metric_hints)), None)
        for col in cols:
            if col == metric_col:
                continue
            values = _distinct_values(adapter, f"SELECT DISTINCT {col} FROM {table}")
            if len(values) < 2 or len(values) > 200:
                continue
            pair = _find_two_in_question(question, values)
            if not pair:
                continue
            a, b = pair
            if router is not None:
                proposed = _propose_factor_model(router, adapter, table=table,
                                                 metric_col=metric_col, col=col, a=a, b=b,
                                                 question=question)
                if proposed is not None:
                    return proposed
            metric_expr = f"SUM({metric_col})" if metric_col else "COUNT(*)"
            metric_name = metric_col.lower() if metric_col else "count"
            model = generic_factor_model(metric_name, metric_expr, f"FROM {table}")
            return Investigation(
                question=question, metric=metric_name, from_sql=model.from_sql,
                a_label=a, b_label=b,
                a_where=f"{col}='{_esc(a)}'", b_where=f"{col}='{_esc(b)}'",
                dimension=col, model=model,
            )
    return None


# ---------------------------------------------------------------------------
# Measurement (one factor — used by parallel investigators)
# ---------------------------------------------------------------------------

def measure_factor(adapter, inv: Investigation, factor_key: str) -> dict:
    """Measure ONE factor for both slices. This is what a single Investigator
    agent owns. Deterministic, no LLM."""
    spec = next((f for f in inv.model.factors if f.key == factor_key), None)
    if spec is None:
        raise ValueError(f"Unknown factor: {factor_key}")
    a_val = _scalar(adapter, f"SELECT {spec.expr} {inv.from_sql} WHERE {inv.a_where}")
    b_val = _scalar(adapter, f"SELECT {spec.expr} {inv.from_sql} WHERE {inv.b_where}")
    return {"factor": factor_key, "label": spec.label,
            "a_value": float(a_val or 0.0), "b_value": float(b_val or 0.0),
            "question": spec.question}


def _scalar(adapter, sql: str):
    rows, _ = adapter.execute_query(sql, 1)
    if not rows:
        return None
    first = rows[0]
    return list(first.values())[0] if isinstance(first, dict) else first[0]


# ---------------------------------------------------------------------------
# Full investigation (in-process / adjudication side)
# ---------------------------------------------------------------------------

def adjudicate_from_factor_values(
    inv: Investigation, factor_values: dict[str, dict], *, metric_a: float, metric_b: float
) -> tuple[BoardVerdict, DecompositionResult]:
    """Assemble the per-factor measurements (from investigators) into slice
    vectors, attribute the gap, and adjudicate the board verdict."""
    from core.decomposition import SliceMeasure
    a = SliceMeasure(label=inv.a_label, metric_value=metric_a,
                     factor_values={k: v["a_value"] for k, v in factor_values.items()})
    b = SliceMeasure(label=inv.b_label, metric_value=metric_b,
                     factor_values={k: v["b_value"] for k, v in factor_values.items()})
    decomp = attribute(a, b, inv.model)
    verdict = adjudicate(inv.question, decomp, metric=inv.metric)
    return verdict, decomp


def measure_metric(adapter, inv: Investigation) -> tuple[float, float]:
    a = _scalar(adapter, f"SELECT {inv.model.metric_expr} {inv.from_sql} WHERE {inv.a_where}")
    b = _scalar(adapter, f"SELECT {inv.model.metric_expr} {inv.from_sql} WHERE {inv.b_where}")
    return float(a or 0.0), float(b or 0.0)


def build_record(inv: Investigation, verdict: BoardVerdict, decomp: DecompositionResult) -> dict:
    findings = []
    for c in decomp.ranked():
        findings.append({
            "factor": c.factor, "factor_label": c.label,
            "a_label": inv.a_label, "b_label": inv.b_label,
            "a_value": c.a_value, "b_value": c.b_value, "direction": c.direction,
            "contribution": round(c.contribution, 2),
            "explained_share": round(c.explained_share, 4),
            "verdict": c.verdict, "confidence": c.confidence,
            "evidence": f"{c.label}: {inv.a_label} {c.a_value:,.2f} vs {inv.b_label} {c.b_value:,.2f}.",
        })
    return {
        "kind": "investigation", "normalized_question": inv.question,
        "metric": inv.metric, "dimension": inv.dimension,
        "a_label": inv.a_label, "b_label": inv.b_label, "gap": round(verdict.gap, 2),
        "headline": verdict.headline,
        "primary_factor": verdict.primary.factor if verdict.primary else None,
        "ruled_out": [c.label for c in verdict.ruled_out],
        "residual_share": round(verdict.residual_share, 4),
        "confidence": verdict.confidence, "conflict_note": verdict.conflict_note,
        "recommendation": verdict.recommendation, "findings": findings,
    }


def investigate(adapter, question: str, *, catalog_path: str | Path) -> Optional[dict]:
    """End-to-end in-process investigation (used by the engine when Band is off)."""
    inv = discover(adapter, question, catalog_path=catalog_path)
    if inv is None:
        return None
    factor_values = {f.key: measure_factor(adapter, inv, f.key) for f in inv.model.factors}
    metric_a, metric_b = measure_metric(adapter, inv)
    verdict, decomp = adjudicate_from_factor_values(
        inv, factor_values, metric_a=metric_a, metric_b=metric_b)
    return build_record(inv, verdict, decomp)


# ---------------------------------------------------------------------------
# Serialization — lets the resolved Investigation travel across Band processes
# so investigators/adjudicator use the SAME model the planner resolved (catalog,
# generic, or LLM-proposed), instead of re-discovering inconsistently.
# ---------------------------------------------------------------------------

def inv_to_dict(inv: "Investigation") -> dict:
    return {
        "question": inv.question, "metric": inv.metric, "from_sql": inv.from_sql,
        "a_label": inv.a_label, "b_label": inv.b_label,
        "a_where": inv.a_where, "b_where": inv.b_where, "dimension": inv.dimension,
        "model": {
            "metric": inv.model.metric, "metric_expr": inv.model.metric_expr,
            "from_sql": inv.model.from_sql, "certified": inv.model.certified,
            "factors": [{"key": f.key, "label": f.label, "expr": f.expr, "question": f.question}
                        for f in inv.model.factors],
        },
    }


def inv_from_dict(d: dict) -> "Investigation":
    m = d["model"]
    model = FactorModel(
        metric=m["metric"], metric_expr=m["metric_expr"], from_sql=m["from_sql"],
        certified=bool(m.get("certified", False)),
        factors=[FactorSpec(key=f["key"], label=f.get("label", f["key"]),
                            expr=f["expr"], question=f.get("question", ""))
                 for f in m["factors"]])
    return Investigation(question=d["question"], metric=d["metric"], from_sql=d["from_sql"],
                         a_label=d["a_label"], b_label=d["b_label"], a_where=d["a_where"],
                         b_where=d["b_where"], dimension=d["dimension"], model=model)
