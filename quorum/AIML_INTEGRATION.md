# AI/ML API Integration

Quorum can route any or all of its reasoning agents through the
[AI/ML API](https://aimlapi.com) (`aimlapi.com`), which exposes an
OpenAI-compatible endpoint. This is wired through the same provider-switch as
every other backend, so turning it on is a configuration change — no code edits.

## How it is wired

- `LLMProvider.AIML` is a first-class provider in `config.py`.
- The router (`core/llm_router.py`) sends AI/ML calls through the OpenAI
  transport with a custom `base_url` and key:
  - `api_base = AIML_BASE_URL` (default `https://api.aimlapi.com/v1`)
  - `api_key  = AIML_API_KEY`
- Default model ids for the provider live in `config.ModelNames`
  (`AIML_REASONING`, `AIML_SQL`) and can be overridden per agent.

## Step 1 — Get a key

Create an account at https://aimlapi.com, generate an API key, and note the
model ids you want from their catalog (e.g. a GPT-class model for reasoning and
a coder model for SQL).

## Step 2 — Configure `.env`

Route **every** agent through AI/ML API with the master switch:

```
LLM_BACKEND=aiml
AIML_API_KEY=your_aiml_key
AIML_BASE_URL=https://api.aimlapi.com/v1
```

Or route **only specific** agents (leave `LLM_BACKEND` blank):

```
PLANNER_PROVIDER=aiml
ADJUDICATOR_PROVIDER=aiml
SQL_ANALYST_PROVIDER=ollama        # keep SQL local, reasoning on AI/ML
AIML_API_KEY=your_aiml_key
```

## Step 3 — (Optional) pick exact models

```
PLANNER_MODEL=openai/gpt-4o-mini
ADJUDICATOR_MODEL=openai/gpt-4o
SQL_ANALYST_MODEL_CLOUD=qwen/qwen2.5-coder-32b-instruct
```

A leading `openai/` prefix is stripped automatically for the AI/ML endpoint, so
either form works.

## Step 4 — Run

```
streamlit run streamlit_app.py
```

The sidebar shows the active routing. Switch providers any time by editing
`LLM_BACKEND` (or the per-agent vars) and restarting — no other change needed.

## Where AI/ML API does the most work

- **Planner** — intent classification + schema grounding (the one reasoning call
  on the descriptive path).
- **Adjudicator** — narrating the diagnostic board verdict.
- **SQL Analyst** — query generation (use a coder model here).

Because the deterministic agents (Cost Sentinel, Investigators, most of the
Guardian) make no LLM calls, AI/ML usage stays concentrated on the steps where
reasoning quality matters, keeping spend predictable.
