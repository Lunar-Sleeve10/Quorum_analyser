# Quorum — Complete Deployment Guide

Repo: https://github.com/Lunar-Sleeve10/Quorum_analyser
Backend: Render (free tier) | Frontend: Vercel (free tier)

---

## Prerequisites (install once on your machine)

| Tool | Version | Install |
|---|---|---|
| Git | any | https://git-scm.com/downloads |
| Python | 3.12+ | https://python.org/downloads |
| Node.js | 20+ | https://nodejs.org |
| pnpm | 9+ | `npm install -g pnpm` |

---

## Part 1 — Local setup (first time)

### 1.1 Clone the repo

```
git clone https://github.com/Lunar-Sleeve10/Quorum_analyser.git
cd Quorum_analyser
```

Your folder structure after clone:
```
Quorum_analyser/
├── quorum/          ← Python backend
├── quorum-ui/       ← Next.js frontend
├── render.yaml
├── vercel.json
└── README.md
```

---

### 1.2 Backend setup

```
cd quorum
```

Create virtual environment:
```
python -m venv .venv
```

Activate it:
- Windows:  `.venv\Scripts\activate`
- Mac/Linux: `source .venv/bin/activate`

Install dependencies:
```
pip install -r requirements/backend.txt -r requirements.txt
```

Create your env file (never commit this):
```
copy .env.example .env
```
or manually create `quorum/.env` with at minimum:
```
LLM_BACKEND=groq
GROQ_API_KEY=gsk_your_key_here
DATABASE_URL=sqlite:///./quorum_app.db
```

Run the backend:
```
uvicorn backend.main:app --reload
```

Verify: open http://localhost:8000/healthz — should return `{"status":"ok"}`
Docs: http://localhost:8000/docs

---

### 1.3 Frontend setup

Open a second terminal:
```
cd Quorum_analyser/quorum-ui
pnpm install
pnpm dev
```

Verify: open http://localhost:3000 — you should see the animated cover page.

The cover page auto-calls the backend at http://localhost:8000.
Click Enter dashboard to reach the workspace.

---

### 1.4 Test end to end locally

1. http://localhost:3000 → cover page loads (status dot: "online")
2. Type a question, click "Run & enter" → investigation starts
3. Dashboard opens with live agent activity

---

## Part 2 — Push to GitHub (handling the old version)

You already pushed an older version to the repo. The steps below clean up stale tracked files and push everything properly.

### 2.1 Unstage files that are now gitignored

Some files from the old push might still be tracked by git even though they are now in .gitignore (databases, pycache, cover backup, etc.). Run this from the repo root to remove them from tracking without deleting them from disk:

```
cd Quorum_analyser

git rm --cached -r quorum/__pycache__ 2>nul
git rm --cached -r quorum/agents/__pycache__ 2>nul
git rm --cached -r quorum/backend/__pycache__ 2>nul
git rm --cached -r quorum/core/__pycache__ 2>nul
git rm --cached -r quorum/pipeline/__pycache__ 2>nul
git rm --cached -r quorum/models/__pycache__ 2>nul
git rm --cached quorum/quorum_app.db 2>nul
git rm --cached quorum/.env 2>nul
git rm --cached quorum-ui/quorum-cover.html 2>nul
git rm --cached quorum/combined_code.txt 2>nul
git rm --cached quorum/tree.txt 2>nul
git rm --cached quorum/db_dump.txt 2>nul
git rm --cached quorum/stuff.py 2>nul
git rm --cached quorum/inspect_db.py 2>nul
git rm --cached quorum/fix_imports.py 2>nul
git rm --cached quorum/fix_sample_paths.py 2>nul
git rm --cached requirements1.txt 2>nul
```

Note: `2>nul` suppresses "not tracked" errors for files that were never tracked — safe to ignore.

### 2.2 Stage everything

```
git add .
```

### 2.3 Verify what will be committed

```
git status
```

Make sure you do NOT see:
- any `.env` files
- any `.db` or `.sqlite` files
- any `__pycache__` directories
- `quorum-cover.html` at quorum-ui root
- `requirements1.txt`
- `.next/` directory
- `node_modules/`

If any of these appear, something went wrong — do NOT commit until resolved.

### 2.4 Commit and push

```
git commit -m "redesign: enterprise UI, cover page, deployment config"
git push origin main
```

---

## Part 3 — Deploy backend on Render

Do this BEFORE Vercel — you need the backend URL first.

### 3.1 Create a Render account

Go to https://dashboard.render.com
Click "Sign in with GitHub" and connect your account.

### 3.2 Create a new Blueprint

Click: New + → Blueprint
Select your GitHub repo: Lunar-Sleeve10/Quorum_analyser
Click Connect.

Render reads render.yaml from the repo root and shows:
- quorum-db (free Postgres database)
- quorum-api (FastAPI web service)

Click Apply.

### 3.3 Set environment variables

While Render is building, go to:
Dashboard → quorum-api → Environment tab

Add these variables (click "Add Environment Variable" for each):

REQUIRED (pick one LLM provider):

| Key | Value |
|---|---|
| LLM_BACKEND | groq |
| GROQ_API_KEY | gsk_your_groq_key_here |

OR for AI/ML API:

| Key | Value |
|---|---|
| LLM_BACKEND | aiml |
| AIML_API_KEY | your_aiml_key_here |

OR for Featherless:

| Key | Value |
|---|---|
| LLM_BACKEND | featherless |
| FEATHERLESS_API_KEY | your_featherless_key_here |
| PLANNER_MODEL | Qwen/Qwen2.5-72B-Instruct |
| GUARDIAN_MODEL | Qwen/Qwen2.5-72B-Instruct |
| REPORTER_MODEL | Qwen/Qwen2.5-72B-Instruct |
| ADJUDICATOR_MODEL | Qwen/Qwen2.5-72B-Instruct |
| SQL_ANALYST_MODEL_CLOUD | Qwen/Qwen2.5-Coder-32B-Instruct |

Click "Save Changes". Render will restart and pick up the new values.

### 3.4 Wait for first deploy

Build takes 3-5 minutes. Watch the logs in the Render dashboard.

On first start, `alembic upgrade head` runs automatically (merged into the start command) to create database tables.

### 3.5 Get your backend URL

Once the status turns "Live", copy your URL from the top of the page:
```
https://quorum-api.onrender.com
```
(the actual URL will have a unique suffix like quorum-api-abc1.onrender.com)

### 3.6 Verify

Open in browser: https://quorum-api.onrender.com/healthz
Expected response: {"status":"ok","database":true}

If you get a 503 or timeout, wait 60 seconds and try again (first boot takes longer).

---

## Part 4 — Deploy frontend on Vercel

### 4.1 Create a Vercel account

Go to https://vercel.com
Click "Sign up with GitHub".

### 4.2 Import the repo

Dashboard → Add New Project → Import Git Repository
Find Quorum_analyser and click Import.

Vercel reads vercel.json from the repo root.
It automatically sets:
- Root Directory: quorum-ui
- Framework: Next.js
- Build Command: pnpm build
- Install Command: pnpm install

Do NOT change any of these.

### 4.3 Set environment variable

Before clicking Deploy, scroll to Environment Variables:

| Key | Value |
|---|---|
| NEXT_PUBLIC_API_BASE_URL | https://quorum-api.onrender.com |

Replace the URL with your actual Render URL from Step 3.5.

Click Deploy.

### 4.4 Wait for first deploy

Build takes 1-2 minutes.

### 4.5 Get your frontend URL

Once deployed, copy your URL:
```
https://quorum-analyser.vercel.app
```

### 4.6 Update CORS on Render

Go back to: Render → quorum-api → Environment
Update (or add) this variable:

| Key | Value |
|---|---|
| FRONTEND_ORIGIN | https://quorum-analyser.vercel.app |

Click Save Changes. Render restarts (~30 seconds).

---

## Part 5 — Final verification

1. Open https://quorum-analyser.vercel.app
2. Cover page loads with Three.js animation
3. Top-right status dot should turn green and say "online"
4. Type a question, click "Run & enter"
5. Investigation starts, you're taken to the dashboard
6. Watch the agent activity stream in real time

If the status dot stays red ("offline demo"):
→ Check NEXT_PUBLIC_API_BASE_URL in Vercel settings (must match Render URL exactly, no trailing slash)
→ Check FRONTEND_ORIGIN in Render settings (must match Vercel URL exactly)
→ Check Render service is not sleeping (open the /healthz URL directly first to wake it)

---

## Part 6 — Changing the LLM provider after deployment

No code changes or redeployment needed. Everything is done through the Render dashboard.

Go to: https://dashboard.render.com → quorum-api → Environment

### Switch to Groq

Change or add:
```
LLM_BACKEND = groq
GROQ_API_KEY = gsk_your_new_key
```
Click Save Changes. Backend restarts in ~20 seconds. Done.

### Switch to AI/ML API

```
LLM_BACKEND = aiml
AIML_API_KEY = your_aiml_key
```
Click Save Changes.
Models are auto-selected (gpt-4o-mini for reasoning, Qwen2.5-Coder for SQL).
No model variables needed.

### Switch to Featherless

```
LLM_BACKEND       = featherless
FEATHERLESS_API_KEY = your_featherless_key
PLANNER_MODEL     = Qwen/Qwen2.5-72B-Instruct
GUARDIAN_MODEL    = Qwen/Qwen2.5-72B-Instruct
REPORTER_MODEL    = Qwen/Qwen2.5-72B-Instruct
ADJUDICATOR_MODEL = Qwen/Qwen2.5-72B-Instruct
SQL_ANALYST_MODEL_CLOUD = Qwen/Qwen2.5-Coder-32B-Instruct
```
Click Save Changes.

### Rotate an API key (same provider)

Just update the key value in Render Environment and click Save Changes.
The old key is gone, the new one is active within 30 seconds.
No code, no git, no redeploy needed.

---

## Part 7 — Future updates (code changes)

Push to main → both services update automatically.

```
# Make your changes, then:
git add .
git commit -m "your change description"
git push origin main
```

Vercel picks up the push and redeploys the frontend in ~60 seconds.
Render picks up the push and redeploys the backend in ~3 minutes.
`alembic upgrade head` runs automatically on each Render deploy.

---

## Known free-tier limitations

| Issue | Cause | Fix |
|---|---|---|
| First request after inactivity takes 30-60s | Render free tier spins down after 15 min | Upgrade to Starter ($7/mo) or accept the delay |
| 750 instance-hours/month | Render free limit | One service running 24/7 uses ~720 hours — just within limit |
| Vercel: 100GB bandwidth/month | Vercel free limit | Sufficient for personal/demo use |
| No persistent disk on Render | SQLite is ephemeral on Render free | Render.yaml provisions Postgres — SQLite is only for local dev |

---

## Quick reference

| What | Where |
|---|---|
| Backend live URL | Render dashboard → quorum-api → top of page |
| Frontend live URL | Vercel dashboard → quorum-analyser → Domains |
| Change LLM key | Render → quorum-api → Environment → Save |
| View backend logs | Render → quorum-api → Logs tab |
| View frontend logs | Vercel → quorum-analyser → Deployments → Functions |
| Trigger manual redeploy | Render → quorum-api → Manual Deploy button |
| Rollback frontend | Vercel → Deployments → pick an older one → Promote |
