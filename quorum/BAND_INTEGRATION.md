# Band Integration Guide

Quorum runs on the [Band](https://band.ai) platform with each agent as a
separate connected process. Collaboration happens **inside** a Band chat room
via `@mention` handoffs — Band is the coordination layer, not a final
notification channel. The local console (`streamlit_app.py`) runs the identical
business logic in-process through `core/coordination.py`; only the message
transport differs.

## Collaboration map

```
Human → @Supervisor                         (plans the work, posts the DAG)
          ├─ descriptive
          │     @SQL Analyst → @Cost Sentinel → @Governance Guardian → @Decision Reporter → Human
          │            ↑──────── bounded debate / revision ───────────┘
          └─ diagnostic
                fan-out: @Investigator (one per factor, in parallel)
                join:    @Adjudicator → @Decision Reporter → Human
```

The agent-decided moments are real, visible exchanges in the room:
- the **Governance Guardian challenging the SQL Analyst** (debate → revision),
- the **parallel investigator fan-out and the Adjudicator join barrier**.

Structured contracts travel inside a fenced ` ```band ` JSON block with a
human-readable lead-in (see `pipeline/payload.py`), so the transcript stays
legible while the agents exchange typed messages.

## Step 1 — Install the Band SDK

```
pip install "band-sdk[pydantic-ai]"
```

## Step 2 — Create the agents on the platform

In Band → **Agents** → **New Agent** → **Remote Agent**, create one per role.
Use these exact display names so `@mention` routing matches the adapter:

| Display name          | Role (internal)    |
| --------------------- | ------------------ |
| `Supervisor`          | supervisor         |
| `SQL Analyst`         | sql_analyst        |
| `Cost Sentinel`       | cost_sentinel      |
| `Governance Guardian` | guardian           |
| `Decision Reporter`   | decision_reporter  |
| `Investigator`        | investigator       |
| `Adjudicator`         | adjudicator        |

For each, copy the Agent UUID and API key into `agent_config.yaml` (keyed by the
internal role name).

## Step 3 — Configure credentials

```
cp .env.example .env
cp agent_config.example.yaml agent_config.yaml
```

`.env` needs the platform URLs, an LLM key (or Ollama), and `DB_PATH`:

```
THENVOI_REST_URL=https://app.band.ai/
THENVOI_WS_URL=wss://app.band.ai/api/v1/socket/websocket
LLM_BACKEND=groq
GROQ_API_KEY=gsk_...
DB_PATH=chinook.db
```

## Step 4 — Launch the team

One process per role:

```
python -m pipeline.run_agent --role supervisor
python -m pipeline.run_agent --role sql_analyst
python -m pipeline.run_agent --role cost_sentinel
python -m pipeline.run_agent --role guardian
python -m pipeline.run_agent --role decision_reporter
python -m pipeline.run_agent --role investigator
python -m pipeline.run_agent --role adjudicator
```

## Step 5 — Ask in a room

Create a room, add all agents as participants, and mention the Supervisor:

```
@Supervisor top 10 artists by sales
@Supervisor why does the USA generate more revenue than Germany?
```

The Supervisor posts the execution plan, then the handoffs flow through the
room: the descriptive pipeline for the first question, and the parallel
investigation board for the second.

## Notes

- Each room's database comes from `DB_PATH`. A production deployment would carry
  the database reference in room/task metadata instead of a global setting.
- The diagnostic investigators re-derive the comparison deterministically from
  the question + catalog, so each runs self-sufficiently in its own process.
