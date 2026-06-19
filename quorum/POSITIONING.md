# Quorum — Positioning & Business Value

## The problem (and why a single agent can't own it)

Enterprises are stuck between two bad options for ad-hoc analytics: human
analysts who are accurate but take days, and single-agent text-to-SQL copilots
that answer in seconds but hallucinate joins, run runaway queries, and leave no
trail. The fast option creates a **trust deficit** exactly where it costs the
most — production data, regulated decisions, money that moves in minutes.

**Quorum automates the data *department*, not the query.** An AI-generated query
is subjected to a deterministic cost gate, a governance review, and (for "why"
questions) an independent investigation board before it influences a decision —
the speed of AI with the controls of software engineering, and a receipt for
every decision.

## What we actually defend on (the moats)

1. **Deterministic Cost Sentinel** — pre-execution cost/safety with *no LLM*
   (`EXPLAIN QUERY PLAN`, Postgres `EXPLAIN`, BigQuery dry-run; risk + budget
   gate). This is the thing that makes putting an LLM near a production
   warehouse defensible. No competitor here has it.
2. **Certified semantic layer** — one agreed SQL definition per metric, so the
   same question always maps to the agreed formula. Kills hallucinated joins at
   the source.
3. **Genuine non-linear collaboration** — a real parallel fan-out/join review
   board and an adversarial debate loop, not a sequential prompt chain.
4. **Governance by construction** — visible debate, authorized-only results (the
   UI never executes SQL), ephemeral credentials, and an exportable audit
   record.

## How we clear the field

| Rival | Their strength | Where Quorum wins |
| --- | --- | --- |
| **AutoReview Crew** (Track 2) | Best Band-native exec; recruits specialists mid-flow; cross-model; 51s demo | We match dynamic recruitment + cross-model, and add a **deterministic safety gate** and a **certified metric layer** they have no analogue for. Different track. |
| **YOUSUN Secura** (governance) | Visible decision room, policy/risk scoring, audit trails | Same "visible + audited" DNA, but Quorum couples it to **real analytics depth** — diagnostic causal attribution and a non-LLM cost gate, not just an approve/reject layer. |
| **Council / llm-council** (regulated) | Parallel archetypes + Oracle; Brier-score calibration | Strong concept, but **does not wrap Band yet** (their own disclosure) — for a Band hackathon Quorum is natively Band-coordinated *today*. |
| **StockSense / SkillPath / AI PDF OS** | Polished vertical products | Broad feature surface, but their multi-agent layer is largely sequential; Quorum's collaboration is the verifiable, non-linear core, not a label. |

**One-liner:** *Users don't choose Quorum because it writes SQL faster — they
choose it because it's the only system where the SQL is independently defended,
priced, and audited before it runs, and where the disagreement between agents is
visible.*

## Honest disclosure — ships now vs roadmap

**Ships now (verified):**
- Band-coordinated multi-agent flow over `@mention` handoffs (one process/role).
- The four non-linear behaviors over Band: debate/revision, parallel
  fan-out/**join barrier** (regression-tested), human-in-the-loop clarification,
  and on-demand recruitment of the investigation board.
- Deterministic Cost Sentinel; certified semantic layer; authorized-only UI
  (no client-side SQL); ephemeral credentials; exportable audit record;
  cross-model routing (litellm: Ollama / Groq / AI/ML API / Featherless /
  OpenAI).

**Roadmap (not claimed as done):**
- Distributed state store (Redis/Postgres) to replace the filesystem run-store.
- dbt Semantic Layer integration for the metric catalog.
- Hard dollar-limit auto-termination on warehouses; multi-tenant isolation;
  cryptographic execution tracing.

**Known limits:** end-to-end timing depends on the chosen providers; the
authorized result is capped at `DB_MAX_ROWS`; remote-DB credentials for the
agent processes are injected via environment, not the console.
