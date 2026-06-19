# Quorum — Demo Runbook

A tight, ~2-minute scripted run that triggers every non-linear behavior **inside
the Band room** and ends on the deterministic moats judges remember. Database:
the bundled `chinook` SQLite sample.

> Setup: `python launch_all.py` (the 7 agents connect), then open the console
> (`streamlit run streamlit_app.py`) with the live agent discussion on (default).
> Keep the discussion panel on screen the whole time — **that** is the product.

---

## Beat 1 — Human-in-the-loop (escalation is real)

**Type:** `@Supervisor how are sales doing?`

**What to point at:** the Planner can't ground a vague question, so the
Supervisor posts an `@user` clarification *in the room* instead of crashing.
Say: *"It doesn't guess — it asks. That's a real human-in-the-loop branch, not a
fallback message."*

## Beat 2 — Governance debate (agents argue, then converge)

**Type:** `@Supervisor rank customers by total revenue`

**What to point at:** SQL Analyst posts the query → **Governance Guardian
challenges it** (e.g. ranking without an explicit `LIMIT`) and sends a
`RevisionRequest` back → the Analyst revises → the Guardian passes it. Say:
*"This is adversarial self-correction — the Guardian is paid to find flaws in the
Analyst's work, and the loop terminates the moment it's compliant."*

## Beat 3 — Deterministic cost gate (the moat nobody else has)

**What to point at:** between the Analyst and the Guardian, the **Cost Sentinel**
prices the query with `EXPLAIN QUERY PLAN` (SQLite) — **no LLM call**. Say:
*"Before any expensive query runs, a deterministic, non-LLM gate prices it. On a
warehouse this is a real bytes-scanned dry-run with a dollar estimate and a hard
budget. That's how you put an LLM near a production database safely."*

## Beat 4 — Parallel investigation board (genuine non-linear fan-out/join)

**Type:** `@Supervisor why does the USA generate more revenue than Germany?`

**What to point at:**
1. The Supervisor classifies this as *diagnostic* and **recruits the
   investigation board into the room on demand** (`band_add_participant`) — a
   visible "Recruiting N factor investigators…" message.
2. N Factor Investigators run **concurrently**, each posting a finding.
3. The **Adjudicator holds a join barrier** — it waits for *all* findings
   (counted from the room transcript) before it fires **once**, then attributes
   the gap to ranked, reconciling factors.

Say: *"Most 'multi-agent' demos are a sequential pipeline. This actually forks,
runs in parallel, and joins — and the join is driven by the Band room history,
so it works with each agent in its own process."*

## Beat 5 — The reward + the receipt

**What to point at:** only now reveal the chart and the decision report
(finding → implication → action). Then open **Audit trail → Download audit
record (JSON)**. Say: *"The chart is the reward; the collaboration is the
product — and every run leaves a governance receipt: the cost gate, the verdict,
and which model each agent used."*

---

## Talking points (the four moats)

1. **Deterministic Cost Sentinel** — pre-execution cost/safety with no LLM.
   Unique here.
2. **Certified semantic layer** — one agreed SQL definition per metric, so the
   same question always maps to the same formula (no hallucinated joins).
3. **True parallel fan-out/join** — a real review board, not a prompt chain.
4. **Audit + governance by construction** — visible debate, authorized-only
   results (the UI never runs SQL), and an exportable record.

## If something fails live (graceful degradation)

- If a specialist process is down, the Supervisor still routes; a missing Cost
  Sentinel just omits the estimate (the flow continues).
- If Band auto-create isn't available, use a fixed room: set `BAND_ROOM_ID` in
  `.env` (see `BAND_INTEGRATION.md`).
- Worst case, the offline engine (`tests/smoke_test.py`) proves the agent logic
  end-to-end without a network.

**Target time:** ~2 minutes. Don't rush Beat 4 — the parallel fan-out and the
join are the highest-scoring 20 seconds of the demo.
