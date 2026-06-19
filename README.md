# Quorum — Governed Analytics

A multi-agent AI system that turns a plain-English business question into a **governed, auditable answer**. A council of specialist agents plans, generates SQL, estimates cost, reviews compliance, and produces a final finding — all with a full audit trail.

**Live demo:** [GitHub → Lunar-Sleeve10/Quorum_analyser](https://github.com/Lunar-Sleeve10/Quorum_analyser)

---

## How it works

```
Your question
  → Planner          decomposes into a structured analysis plan
  → Plan Guardian    pre-execution plan review
  → SQL Analyst      generates and executes queries
  → Cost Sentinel    validates cost + SQL compliance with the plan
  → Gov Guardian     post-execution correctness review
  → Decision Reporter  finding · implication · recommended action
```

Two investigation modes: **Governed Chain** (descriptive "what/how much") and **Investigation Board** (diagnostic "why" — parallel investigators + adjudicator).

---

## Project layout

```
Quorum_analyser/
├── quorum/          FastAPI backend + agent pipeline
├── quorum-ui/       Next.js 16 frontend
├── render.yaml      Render deployment blueprint (backend)
└── vercel.json      Vercel deployment config (frontend)
```

---

## Quickstart (local)

### 1 — Backend

```bash
cd quorum

# Create and activate a virtual environment
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements/backend.txt -r requirements.txt

# Copy and fill in the env file
cp .env.example .env          # or rename the existing .env.local.example
# Set at minimum: GROQ_API_KEY (or AIML_API_KEY / FEATHERLESS_API_KEY)

# Run the API  →  http://localhost:8000
uvicorn backend.main:app --reload
```

Docs available at `http://localhost:8000/docs`. On first boot, sample databases (`northwind.db`, `chinook.db`) in `data/samples/` are auto-registered as data sources.

### 2 — Frontend

```bash
cd quorum-ui
pnpm install
pnpm dev    # http://localhost:3000
```

Opening `localhost:3000` shows the cover page first. Click **Enter dashboard** to reach the workspace.

---

## Switching LLM provider

Edit `quorum/.env`:

### → AI/ML API (easiest — models auto-selected)
```env
LLM_BACKEND=aiml
AIML_API_KEY=your-key
# No model changes needed — defaults are wired in config.py
```

### → Featherless (must update model names too)
```env
LLM_BACKEND=featherless
FEATHERLESS_API_KEY=your-key

PLANNER_MODEL=Qwen/Qwen2.5-72B-Instruct
GUARDIAN_MODEL=Qwen/Qwen2.5-72B-Instruct
REPORTER_MODEL=Qwen/Qwen2.5-72B-Instruct
ADJUDICATOR_MODEL=Qwen/Qwen2.5-72B-Instruct
SQL_ANALYST_MODEL_CLOUD=Qwen/Qwen2.5-Coder-32B-Instruct
```

### → Groq (default)
```env
LLM_BACKEND=groq
GROQ_API_KEY=your-key
```

Per-agent overrides: leave `LLM_BACKEND=` blank and set `PLANNER_PROVIDER`, `SQL_ANALYST_PROVIDER`, etc. individually.

See `quorum/AIML_INTEGRATION.md` and `quorum/BAND_INTEGRATION.md` for detailed setup.

---

## Deployment

### Backend → Render

The repo includes `render.yaml` at the root for one-click deploy.

1. Go to [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint**
2. Connect `Lunar-Sleeve10/Quorum_analyser`
3. Render detects `render.yaml` and creates:
   - `quorum-db` — free Postgres instance
   - `quorum-api` — FastAPI web service
4. In the Render dashboard, add these **environment variables** (marked `sync: false` in the yaml):

   | Key | Value |
   |---|---|
   | `LLM_BACKEND` | `groq` / `aiml` / `featherless` |
   | `GROQ_API_KEY` | your key |
   | `AIML_API_KEY` | your key |
   | `FEATHERLESS_API_KEY` | your key |

5. After deploy, copy the service URL: `https://quorum-api.onrender.com`
6. Update `FRONTEND_ORIGIN` to your Vercel URL (or leave `*` for open CORS)

> **Note:** Free Render instances spin down after inactivity — the first request after a cold start takes ~30 s.

---

### Frontend → Vercel

The repo includes `vercel.json` at the root pointing to the `quorum-ui/` directory.

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Import `Lunar-Sleeve10/Quorum_analyser`
3. Vercel reads `vercel.json` — root directory is set to `quorum-ui` automatically
4. Add this **environment variable** in Vercel's project settings:

   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | `https://quorum-api.onrender.com` |

5. Deploy — the cover page will automatically point to your Render backend

---

## Environment variables reference

### Backend (`quorum/.env`)

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | *(blank)* | Master switch: `groq` / `aiml` / `featherless` / `openai` / `ollama` |
| `GROQ_API_KEY` | | Groq API key |
| `AIML_API_KEY` | | AI/ML API key (aimlapi.com) |
| `FEATHERLESS_API_KEY` | | Featherless API key |
| `DATABASE_URL` | `sqlite:///./quorum_app.db` | Postgres DSN in production |
| `CREDENTIAL_ENCRYPTION_KEY` | | Fernet key for encrypting DB credentials at rest |
| `FRONTEND_ORIGIN` | `*` | CORS allowed origin (set to your Vercel URL in prod) |
| `MAX_INVESTIGATIONS_PER_SESSION` | `3` | Quota per session |
| `MAX_FOLLOWUPS_PER_INVESTIGATION` | `2` | Follow-up quota |

### Frontend (`quorum-ui/.env.local`)

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | FastAPI backend URL |

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI + Uvicorn |
| Agent LLM routing | litellm (Groq / AI/ML / Featherless / Ollama / OpenAI) |
| Database | SQLite (dev) · PostgreSQL (prod) via SQLAlchemy + Alembic |
| Frontend | Next.js 16 · React 19 · TypeScript · Tailwind CSS 4 |
| Animations | Motion (Framer Motion successor) |
| State | Zustand + TanStack Query |
| Cover page | Three.js (CDN) — standalone HTML |
| Deploy | Render (backend) + Vercel (frontend) |
