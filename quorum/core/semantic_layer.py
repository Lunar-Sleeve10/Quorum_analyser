"""
core/semantic_layer.py — The certified semantic layer (metric catalog) and a
retrievable schema index.

This is the spine of the governed-analytics design. It solves two problems at
once:

1. CORRECTNESS — metrics ("revenue", "active customers") have ONE certified
   SQL definition, so the same question always maps to the agreed formula
   instead of the model inventing one (the root cause of the $138-vs-$1,233
   class of bug).

2. SCALE — on a warehouse with thousands of tables you cannot put the whole
   schema in the prompt. The SemanticLayer is a *retrievable* index: given a
   question, `retrieve()` returns only the top-k relevant tables, columns, and
   metrics. The model sees a small, relevant slice — never the whole warehouse.

Retrieval is pluggable:
- The default `LexicalRetriever` needs no extra dependencies (token-overlap +
  light synonym expansion). It runs anywhere and is enough for hundreds of
  tables.
- An embedding-backed retriever can be dropped in for true warehouse scale by
  implementing the same `Retriever` protocol; the call sites do not change.

The catalog is loaded from a YAML file (see metric_catalog.yaml) and is meant to
live as SHARED context in the Band room, so every agent grounds against the same
certified definitions.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9_]+")

# Light, domain-agnostic synonym expansion so a user's word ("sales", "buyer")
# can match catalog terms ("revenue", "customer"). Extend per deployment.
_SYNONYMS: dict[str, set[str]] = {
    "sales": {"revenue", "amount", "total", "spend"},
    "revenue": {"sales", "amount", "total"},
    "buyer": {"customer", "client", "account"},
    "customer": {"buyer", "client", "account"},
    "song": {"track", "title"},
    "track": {"song", "title"},
    "artist": {"band", "performer", "musician"},
    "purchase": {"invoice", "order", "transaction"},
    "order": {"invoice", "purchase", "transaction"},
    "top": {"best", "highest", "ranking", "most"},
    "count": {"number", "how many", "total"},
}


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _expand(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for t in tokens:
        out |= _SYNONYMS.get(t, set())
    return out


# ---------------------------------------------------------------------------
# Catalog data model
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ColumnSpec:
    name: str
    type: str = ""
    description: str = ""

    def search_text(self) -> str:
        return f"{self.name} {self.type} {self.description}"


@dataclass(slots=True)
class TableSpec:
    name: str
    description: str = ""
    grain: str = ""                       # "one row per ..." — disambiguates joins
    columns: list[ColumnSpec] = field(default_factory=list)
    certified: bool = False
    expensive: bool = False               # warehouse cost hint (large/unpartitioned)
    partition_column: str = ""            # for cost guardrails on warehouses

    def search_text(self) -> str:
        cols = " ".join(c.search_text() for c in self.columns)
        return f"{self.name} {self.description} {self.grain} {cols}"


@dataclass(slots=True)
class MetricSpec:
    name: str
    definition: str                       # the certified SQL expression
    description: str = ""
    grain: str = ""
    tables: list[str] = field(default_factory=list)
    certified: bool = False
    synonyms: list[str] = field(default_factory=list)

    def search_text(self) -> str:
        return f"{self.name} {self.description} {' '.join(self.synonyms)}"


@dataclass(slots=True)
class EntitySpec:
    name: str
    column: str                           # e.g. "Artist.Name"
    description: str = ""
    synonyms: list[str] = field(default_factory=list)

    def search_text(self) -> str:
        return f"{self.name} {self.column} {self.description} {' '.join(self.synonyms)}"


@dataclass(slots=True)
class RetrievedContext:
    """The small, relevant slice handed to the SQL generator."""
    tables: list[TableSpec] = field(default_factory=list)
    metrics: list[MetricSpec] = field(default_factory=list)
    entities: list[EntitySpec] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.tables or self.metrics or self.entities)

    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    def certified_metric(self, name: str) -> Optional[MetricSpec]:
        for m in self.metrics:
            if m.name.lower() == name.lower():
                return m
        return None


# ---------------------------------------------------------------------------
# Retriever protocol + lightweight default
# ---------------------------------------------------------------------------

class Retriever(Protocol):
    def retrieve(self, question: str, k: int) -> RetrievedContext: ...


class LexicalRetriever:
    """Dependency-free retriever: token overlap with light synonym expansion.
    Adequate for hundreds of tables; swap for an embedding retriever at
    warehouse scale (same interface)."""

    def __init__(self, catalog: "SemanticLayer") -> None:
        self._catalog = catalog

    def _score(self, q_tokens: set[str], target_text: str) -> float:
        t_tokens = _tokens(target_text)
        if not t_tokens:
            return 0.0
        overlap = len(q_tokens & t_tokens)
        if overlap == 0:
            return 0.0
        # Normalize by target size so huge descriptions don't dominate.
        return overlap / (len(t_tokens) ** 0.5)

    def retrieve(self, question: str, k: int) -> RetrievedContext:
        q = _expand(_tokens(question))

        scored_metrics = sorted(
            ((self._score(q, m.search_text()), m) for m in self._catalog.metrics),
            key=lambda p: p[0], reverse=True,
        )
        scored_entities = sorted(
            ((self._score(q, e.search_text()), e) for e in self._catalog.entities),
            key=lambda p: p[0], reverse=True,
        )
        metrics = [m for s, m in scored_metrics if s > 0][:k]
        entities = [e for s, e in scored_entities if s > 0][:k]

        # Tables: union of (a) tables referenced by matched metrics/entities and
        # (b) tables that themselves score on the question. This guarantees the
        # tables needed for a certified metric are always present.
        forced: set[str] = set()
        for m in metrics:
            forced |= set(m.tables)
        for e in entities:
            forced.add(e.column.split(".")[0])

        scored_tables = sorted(
            ((self._score(q, t.search_text()), t) for t in self._catalog.tables),
            key=lambda p: p[0], reverse=True,
        )
        table_by_name = {t.name: t for t in self._catalog.tables}
        chosen: list[TableSpec] = []
        seen: set[str] = set()
        for name in forced:
            if name in table_by_name and name not in seen:
                chosen.append(table_by_name[name]); seen.add(name)
        for s, t in scored_tables:
            if len(chosen) >= max(k, len(forced)) + k:
                break
            if s > 0 and t.name not in seen:
                chosen.append(t); seen.add(t.name)

        return RetrievedContext(tables=chosen, metrics=metrics, entities=entities)


# ---------------------------------------------------------------------------
# The semantic layer (catalog) itself
# ---------------------------------------------------------------------------

class SemanticLayer:
    def __init__(
        self,
        *,
        tables: list[TableSpec],
        metrics: list[MetricSpec],
        entities: list[EntitySpec],
        retriever: Optional[Retriever] = None,
    ) -> None:
        self.tables = tables
        self.metrics = metrics
        self.entities = entities
        self._retriever = retriever or LexicalRetriever(self)

    def retrieve(self, question: str, k: int = 8) -> RetrievedContext:
        """Return only the top-k relevant tables/metrics/entities for a question.
        This is what keeps prompts small on large schemas."""
        return self._retriever.retrieve(question, k)

    def metric(self, name: str) -> Optional[MetricSpec]:
        for m in self.metrics:
            if m.name.lower() == name.lower():
                return m
        return None

    @property
    def table_count(self) -> int:
        return len(self.tables)

    # ---- loading -------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SemanticLayer":
        import yaml  # local import; pyyaml ships with band-sdk anyway

        p = Path(path)
        if not p.exists():
            logger.warning("Metric catalog not found at %s; using empty layer", p)
            return cls(tables=[], metrics=[], entities=[])
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticLayer":
        tables = [
            TableSpec(
                name=t["name"],
                description=t.get("description", ""),
                grain=t.get("grain", ""),
                certified=bool(t.get("certified", False)),
                expensive=bool(t.get("expensive", False)),
                partition_column=t.get("partition_column", ""),
                columns=[
                    ColumnSpec(
                        name=c["name"] if isinstance(c, dict) else str(c),
                        type=(c.get("type", "") if isinstance(c, dict) else ""),
                        description=(c.get("description", "") if isinstance(c, dict) else ""),
                    )
                    for c in t.get("columns", [])
                ],
            )
            for t in data.get("tables", [])
        ]
        metrics = [
            MetricSpec(
                name=m["name"],
                definition=m["definition"],
                description=m.get("description", ""),
                grain=m.get("grain", ""),
                tables=list(m.get("tables", [])),
                certified=bool(m.get("certified", False)),
                synonyms=list(m.get("synonyms", [])),
            )
            for m in data.get("metrics", [])
        ]
        entities = [
            EntitySpec(
                name=e["name"],
                column=e["column"],
                description=e.get("description", ""),
                synonyms=list(e.get("synonyms", [])),
            )
            for e in data.get("entities", [])
        ]
        return cls(tables=tables, metrics=metrics, entities=entities)


_LAYER_CACHE: dict[str, SemanticLayer] = {}


def get_semantic_layer(path: str | Path) -> SemanticLayer:
    """Process-level cache so each agent loads the catalog once."""
    key = str(path)
    if key not in _LAYER_CACHE:
        _LAYER_CACHE[key] = SemanticLayer.from_yaml(path)
        logger.info("Loaded semantic layer from %s (%d tables, %d metrics)",
                    key, _LAYER_CACHE[key].table_count, len(_LAYER_CACHE[key].metrics))
    return _LAYER_CACHE[key]


def render_for_prompt(ctx: RetrievedContext) -> str:
    """Render a retrieved slice as a compact, model-friendly grounding block."""
    lines: list[str] = []
    if ctx.metrics:
        lines.append("CERTIFIED METRICS (use these exact definitions):")
        for m in ctx.metrics:
            tag = " [certified]" if m.certified else ""
            lines.append(f"- {m.name}{tag}: {m.definition}")
            if m.grain:
                lines.append(f"    grain: {m.grain}")
    if ctx.entities:
        lines.append("ENTITIES:")
        for e in ctx.entities:
            lines.append(f"- {e.name} -> {e.column}")
    if ctx.tables:
        lines.append("RELEVANT TABLES:")
        for t in ctx.tables:
            grain = f" (grain: {t.grain})" if t.grain else ""
            cols = ", ".join(c.name for c in t.columns) if t.columns else ""
            lines.append(f"- {t.name}{grain}: {t.description}")
            if cols:
                lines.append(f"    columns: {cols}")
    return "\n".join(lines)
