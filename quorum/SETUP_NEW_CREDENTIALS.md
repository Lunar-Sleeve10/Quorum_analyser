# Setting up new Band credentials

You regenerated your Band agents, so you have a **new agent_id + api_key for
each role** and (optionally) a new **console/dashboard** agent. Here's exactly
what to change. Nothing else in the code needs editing.

> ⚠️ **Rotate the keys you pasted in chat.** The Groq key and all Band keys you
> shared are now exposed — regenerate them in Band (each agent → rotate key) and
> at console.groq.com, and use the fresh values below. Never commit
> `agent_config.yaml` or `.env` (they're git-ignored).

## 1. `agent_config.yaml` — the 7 worker agents

Same structure as before; just paste the **new** `agent_id` and `api_key` for
each role. Every role needs its **own** agent (no sharing an id):

```yaml
supervisor:        {agent_id: "<new>", api_key: "<new>"}
sql_analyst:       {agent_id: "<new>", api_key: "<new>"}
cost_sentinel:     {agent_id: "<new>", api_key: "<new>"}
guardian:          {agent_id: "<new>", api_key: "<new>"}
decision_reporter: {agent_id: "<new>", api_key: "<new>"}
investigator:      {agent_id: "<new>", api_key: "<new>"}
adjudicator:       {agent_id: "<new>", api_key: "<new>"}
```

(The display names in Band must still match: `Supervisor`, `SQL Analyst`,
`Cost Sentinel`, `Governance Guardian`, `Decision Reporter`, `Investigator`,
`Adjudicator` — see `BAND_INTEGRATION.md`.)

## 2. `.env` — console identity + keys (fix the duplicates!)

Your old `.env` defined `DASHBOARD_API_KEY` and `DASHBOARD_AGENT_ID` **twice**,
and the second copies had a **stray space after `=`**. dotenv keeps the *last*
line, so you may have been authenticating with the wrong key. Keep **exactly
one** of each, no space:

```dotenv
# LLM (new Groq key)
LLM_BACKEND=groq
GROQ_API_KEY=<new-groq-key>

# Local SQL model (optional)
SQL_ENGINEER_PROVIDER=ollama
SQL_ENGINEER_MODEL_LOCAL=qwen2.5-coder:7b
OLLAMA_BASE_URL=http://localhost:11434

# Database (demo)
DB_TYPE=sqlite
DB_PATH=chinook.db
DB_MAX_ROWS=1000
DB_READ_ONLY=true

# Band platform
THENVOI_REST_URL=https://app.band.ai/
THENVOI_WS_URL=wss://app.band.ai/api/v1/socket/websocket
BAND_REST_URL=https://app.band.ai

# Console -> Band identity (ONE line each, NO space after '=')
DASHBOARD_API_KEY=<new-console-agent-key>
DASHBOARD_AGENT_ID=<new-console-agent-id>

# Optional but recommended for a reliable demo (see step 3)
# BAND_ROOM_ID=<room-id-you-created-in-the-band-ui>

# Governance / memory / app
METRIC_CATALOG_PATH=metric_catalog.yaml
RUN_STORE_DIR=runs
ENABLE_MEMORY=true
MEMORY_DIR=.quorum_memory
LOG_LEVEL=INFO
```

Notes:
- The **console/dashboard** agent should be a *separate* lightweight Band agent,
  not one of the 7 workers (your old `DASHBOARD_AGENT_ID` already was separate —
  keep it that way).
- `USE_BAND` is a dead flag in the code — it doesn't affect anything, ignore it.
- `PG_*` / `BQ_*` are **not needed** for the SQLite demo. With the new ephemeral
  credential handling, remote-DB secrets are entered per-session in the UI (or
  injected via env for the agent processes) and are never written to disk.

## 3. Recommended: fixed-room mode (most reliable for the demo)

In the Band UI create one room, add all 7 worker agents **and** the console
agent, copy the room id, and set `BAND_ROOM_ID=<that id>` in `.env`. The console
will reuse it every run (no create/delete API needed).

## 4. Verify, then launch

```
python -m tools.preflight        # checks .env + agent_config.yaml, live-auths every key
python launch_all.py             # brings the 7 agents online
streamlit run streamlit_app.py   # the console (live discussion on by default)
```

`preflight` prints `READY — 0 problems` when everything authenticates. If any
key fails `whoami`, that key is wrong/rotated; fix it before the demo.
