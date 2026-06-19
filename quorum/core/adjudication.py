"""
core/adjudication.py — The review-board adjudicator.

Turns independent investigator findings (factor contributions) into a ranked,
reconciled board verdict. Deterministic by design: it RANKS by explained-share,
detects CONFLICT (two primary-strength factors), lists what was RULED OUT, and
reports the unexplained RESIDUAL. An LLM may later narrate the verdict, but the
judgment itself is computed, not guessed. Fully domain-agnostic — it reasons in
terms of factor labels and directions, never a fixed schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core.decomposition import DecompositionResult, FactorContribution


@dataclass(slots=True)
class BoardVerdict:
    question: str
    slice_a_label: str
    slice_b_label: str
    gap: float
    metric: str
    primary: Optional[FactorContribution]
    contributing: list[FactorContribution] = field(default_factory=list)
    ruled_out: list[FactorContribution] = field(default_factory=list)
    residual_share: float = 0.0
    conflict_note: str = ""
    headline: str = ""
    recommendation: str = ""
    confidence: str = "medium"


def adjudicate(question: str, decomp: DecompositionResult, *, metric: str = "metric") -> BoardVerdict:
    ranked = decomp.ranked()
    primary = next((c for c in ranked if c.verdict == "primary"), None)
    contributing = [c for c in ranked if c.verdict == "contributing"]
    ruled_out = [c for c in ranked if c.verdict == "ruled_out"]

    a, b = decomp.slice_a, decomp.slice_b
    gap = decomp.gap

    strong = [c for c in ranked if abs(c.explained_share) >= 0.40]
    conflict = ""
    if len(strong) >= 2:
        conflict = (
            f"Two factors compete for primacy: {strong[0].label} "
            f"({strong[0].explained_share:.0%}) and {strong[1].label} "
            f"({strong[1].explained_share:.0%}). Both are real and additive here."
        )

    if primary and abs(decomp.residual_share) < 0.20:
        confidence = "high" if abs(primary.explained_share) >= 0.50 else "medium"
    elif primary:
        confidence = "medium"
    else:
        confidence = "low"

    headline, recommendation = _narrate(a.label, b.label, gap, metric, primary, ruled_out)

    return BoardVerdict(
        question=question, slice_a_label=a.label, slice_b_label=b.label, gap=gap,
        metric=metric, primary=primary, contributing=contributing, ruled_out=ruled_out,
        residual_share=decomp.residual_share, conflict_note=conflict,
        headline=headline, recommendation=recommendation, confidence=confidence,
    )


def _fmt(v: float) -> str:
    av = abs(v)
    if av >= 1000:
        return f"{v:,.0f}"
    if av >= 1:
        return f"{v:,.1f}"
    return f"{v:.2f}"


def _narrate(a_label, b_label, gap, metric, primary, ruled_out):
    if primary is None:
        return (
            f"No single factor dominates the {_fmt(abs(gap))} {metric} gap between "
            f"{a_label} and {b_label}; it is diffuse across factors.",
            f"Investigate finer segments — no single lever explains the gap.",
        )
    move = "higher" if primary.direction == "higher" else "lower"
    ruled = ", ".join(c.label for c in ruled_out) or "none"
    headline = (
        f"The {_fmt(abs(gap))} {metric} gap is primarily driven by "
        f"{primary.label} ({primary.explained_share:.0%} of the gap; "
        f"{a_label} {move} than {b_label}: {_fmt(primary.a_value)} vs "
        f"{_fmt(primary.b_value)}). Ruled out: {ruled}."
    )
    recommendation = (
        f"Recommendation: focus on {primary.label.lower()} when closing the gap "
        f"between {b_label} and {a_label}; the ruled-out factors ({ruled}) are not "
        f"where the difference lives."
    )
    return headline, recommendation


def verdict_to_markdown(v: BoardVerdict) -> str:
    lines = [f"### Board verdict — {v.confidence} confidence", f"**{v.headline}**", ""]
    if v.primary:
        lines.append(f"- **Primary driver:** {v.primary.label} "
                     f"({v.primary.explained_share:.0%}, {v.primary.confidence} confidence)")
    for c in v.contributing:
        lines.append(f"- **Contributing:** {c.label} ({c.explained_share:.0%})")
    for c in v.ruled_out:
        lines.append(f"- **Ruled out:** {c.label} ({c.explained_share:.0%})")
    if abs(v.residual_share) >= 0.05:
        lines.append(f"- **Unexplained:** {abs(v.residual_share):.0%} (interaction effects)")
    if v.conflict_note:
        lines.append(f"\n_{v.conflict_note}_")
    lines.append(f"\n{v.recommendation}")
    return "\n".join(lines)
