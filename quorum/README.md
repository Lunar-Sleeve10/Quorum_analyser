# Quorum — Governed Analytics Review Board

Quorum answers business questions over a database in plain English and returns a
**decision with an audit trail** — not just a number. A Supervisor classifies the
question and chooses the **collaboration topology**, then a band of specialist
agents collaborates **inside a Band chat room** via `@mention` handoffs: they
ground metrics, price the query before running it, review for policy, debate
revisions, and — for "why" questions — convene a parallel investigation board
that joins to a verdict.

**The collaboration is the product; SQL is the payload.** The Band room — agent
recruitment, handoffs, findings, adjudication, escalation — is the primary
surface, visible live in the UI.

## Architecture (v2 — three tiers + Band)

```
Streamlit Command Center  →  FastAPI control plane  →  Band platform (7 agents)
   (pure API client)          (system of record,        @mention handoffs,
   8 pages, live feed          orchestration, quotas,    recruitment, parallel
                               scope, crypto, audit)      fan-out / join
                                      │
                                 PostgreSQL  +  LLM providers (litellm)
```

- **Tier 1 — Streamlit Command Center** (`frontend/`): Dashboard, Investigations,
  Band Room, Insights, Audit Trail, Data Sources, System Status. No business
  logic — every action calls the API.
- **Tier 2 — FastAPI control plane** (`backend/`): the system of record. Persists
  every investigation, room message, finding, verdict, governance event, and
  authorized result to Postgres; enforces quotas and scope; encrypts credentials.
- **Tier 3 — Band agents** (`agents/`, `pipeline/`, `core/`): the seven agents,
  each a separate connected process collaborating in a Band room.

## Two collaboration topologies (the Supervisor chooses)

```
Governed Chain (descriptive — "top 10 customers by revenue")
  Supervisor → SQL Analyst → Cost Sentinel → Governance Guardian → Decision Reporter
                   ↑──────── bounded debate / revision ──────────┘

Investigation Board (diagnostic — "why did profitability decline?")
  Supervisor recruits N Investigators (parallel) → Adjudicator (join) → Decision Reporter

Unclear ("how are sales doing?") → @user clarification (human-in-the-loop)
```

## The agents

| Agent | Role | LLM | Non-linear capability |
| --- | --- | --- | --- |
| Supervisor (Planner) | intent + topology + plan; drives handoffs | 1 call | descriptive vs diagnostic; fan-out/join; recruitment; escalation |
| SQL Analyst | optimized SQL from the plan | 1 call | revises under challenge |
| Cost Sentinel | pre-execution cost / safety gate | deterministic | challenges expensive queries |
| Governance Guardian | compliance + correctness + viz decision | deterministic-first | bounded debate loop |
| Decision Reporter | finding → implication → action; emits authorized result | optional | — |
| Factor Investigators | one factor each (diagnostic) | deterministic | run in parallel |
| Adjudicator | join findings + attribute the gap | optional | distributed join barrier |

## What makes it defensible

- **Deterministic Cost Sentinel** — pre-execution cost/safety with no LLM
  (`EXPLAIN QUERY PLAN` / Postgres `EXPLAIN` / BigQuery dry-run).
- **Certified semantic layer** (`metric_catalog.yaml`) — one agreed SQL
  definition per metric; no hallucinated joins.
- **Genuine non-linear collaboration** — a real parallel fan-out/join review
  board (regression-tested) and an adversarial debate loop, not a prompt chain.
- **Governance by construction** — visible debate, authorized-only results (the
  UI never executes SQL), bounded investigation scope (≤3 tables / ≤6 columns),
  encrypted credentials at rest, and an exportable audit record.

## Project layout

```
quorum/
├── backend/                FastAPI control plane (system of record)
│   ├── main.py  config.py  deps.py
│   ├── api/        investigations, rooms (SSE), dashboard, data_sources,
│   │               schema_scope, dictionary, system, quota, health
│   ├── services/   orchestration, execution, scope, dictionary, crypto, quota
│   └── db/         base.py, models.py  (16 tables)
├── frontend/               Streamlit Command Center (pure API client)
│   ├── app.py  api_client.py  components/charts.py
├── agents/  pipeline/  core/   the Band agent stack (collaboration core)
├── alembic/                migrations (initial schema generated)
├── data/samples/           drop northwind.db here (auto-registered)
├── render.yaml             one-click Render blueprint
├── tests/                  9 offline test suites
└── docs: GETTING_STARTED.md · QUORUM_V2_INDEX.md · PHASE1_BACKEND.md ·
         PHASE2_3.md · DEPLOY_RENDER.md · DEMO.md · POSITIONING.md · BAND_INTEGRATION.md
```

## Quick start (local, SQLite — zero setup)

```
pip install -r requirements/backend.txt -r requirements.txt
uvicorn backend.main:app --reload --port 8000          # http://localhost:8000/docs

pip install -r requirements/frontend.txt
# new terminal:
streamlit run frontend/app.py                          # set API_BASE_URL if not default
```

Put a sample DB at `data/samples/northwind.db` first. For a live Band room, fill
`agent_config.yaml` + `.env` and run `python launch_all.py` (verify with
`python tools/preflight.py`). **New here? Follow `GETTING_STARTED.md` step by step.**

## Deploy

Push to GitHub → Render → New → Blueprint (reads `render.yaml`): API + UI +
Postgres + agents worker, migrations on deploy. See `DEPLOY_RENDER.md`.

## Tests

```
python tests/test_backend_phase1.py   python tests/test_backend_phase2.py
python tests/test_backend_phase4.py   python tests/test_backend_phase56.py
python tests/test_frontend_phase3.py  python tests/test_chart_rules.py
python tests/test_join_barrier.py     python tests/test_ui_safety.py
python tests/test_audit_recruit.py
```

Licensed under the MIT License (`LICENSE`).
