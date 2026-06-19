# Quorum v2 — build index

Governed Analytics Review Board on Band. Three tiers: Streamlit Command Center →
FastAPI control plane (system of record) → Band collaboration, with PostgreSQL.

## Status by phase (all implemented + tested)

| Phase | What | Key files |
| --- | --- | --- |
| 0/1 | FastAPI + SQLAlchemy + Alembic; anonymous sessions; quotas; topology routing | `backend/`, `alembic/` |
| 2 | Live execution (Band mode + local fallback) → persists room, transcript, findings, verdict, authorized result; SSE feed | `backend/services/execution.py`, `backend/api/rooms.py` |
| 3 | Streamlit as a pure API client | `frontend/api_client.py`, `frontend/app.py` |
| 4 | Command Center pages + Band Room (live feed + agent network) | `frontend/app.py` |
| 5 | Data sources: encrypted connections, file upload, schema discovery, bounded scope (≤3 tables/≤6 cols), data dictionary | `backend/services/scope.py`, `backend/services/dictionary.py` |
| 6 | Dashboard aggregates, Insights chart rules, Audit replay, System Status | `backend/api/dashboard.py`, `frontend/components/charts.py` |
| 7 | Render deploy: `render.yaml`, migrations on deploy, health, agents worker | `render.yaml`, `DEPLOY_RENDER.md` |

Detail guides: `PHASE1_BACKEND.md`, `PHASE2_3.md`, `DEPLOY_RENDER.md`.

## Run locally (SQLite, zero setup)

```
# 1) put your sample DB here:
#    data/samples/northwind.db
# 2) backend
pip install -r requirements/backend.txt -r requirements.txt
uvicorn backend.main:app --reload --port 8000          # docs at /docs
# 3) UI
pip install -r requirements/frontend.txt
API_BASE_URL=http://localhost:8000 streamlit run frontend/app.py
```

For a live Band room, also fill `agent_config.yaml` + `.env` (Band URLs, LLM key)
and run `python launch_all.py`; verify with `python tools/preflight.py`.

## Deploy (Render)

Push to GitHub → Render → New → Blueprint (reads `render.yaml`): provisions API,
UI, Postgres, and the agents worker; runs `alembic upgrade head` on deploy. See
`DEPLOY_RENDER.md`.

## Demo

Follow `DEMO.md` (5 beats: clarification → debate → cost gate → parallel
investigation → reward + audit). The Band Room page is the star.

## Tests (all green, offline)

```
python tests/test_backend_phase1.py     # sessions, quotas, topology routing
python tests/test_backend_phase2.py     # executor persists the full schema
python tests/test_backend_phase4.py     # schema discovery, scope limits, encrypted creds
python tests/test_backend_phase56.py    # dashboard aggregates + system status
python tests/test_frontend_phase3.py    # UI is a pure API client
python tests/test_chart_rules.py        # chart selection rules
python tests/test_join_barrier.py       # distributed fan-in join barrier (agents)
python tests/test_ui_safety.py          # transcript sanitization
python tests/test_audit_recruit.py      # audit record + dynamic recruitment
```

## What's left (operational, not architectural)

- Connect real Band agent credentials and record the demo.
- Push to GitHub + click Blueprint on Render.
- Optional: richer theming, more sample datasets.
