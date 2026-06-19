# Phase 1 — Backend control plane (run guide)

This is the FastAPI + SQLAlchemy + Alembic backend from the approved v2 design.
It runs locally on **SQLite** (zero setup) and on **PostgreSQL** in production
(Render) by setting one env var. The existing Band agent stack is untouched.

## Where to put `northwind.db`

Drop your downloaded file here, named exactly `northwind.db`:

```
quorum/data/samples/northwind.db
```

That's it — no code change. On the next API start it is auto-registered as a
read-only data source named **"Northwind (sample)"** (see
`backend/main.py::_seed_samples`). Verify with:

```
curl http://localhost:8000/data-sources
```

(Chinook is also auto-registered if you add `chinook.db` or `chinook.sqlite`
to the same folder.)

## Install & run (local, SQLite)

```
pip install -r requirements/backend.txt
uvicorn backend.main:app --reload --port 8000
```

- API docs: http://localhost:8000/docs
- Health:  http://localhost:8000/healthz
- App DB:  `quorum_app.db` is created automatically in the project root.

## What works in Phase 1

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | DB connectivity + whether Band is configured (Render health check) |
| `GET /quota` | remaining investigations / follow-ups; returns your `session_token` |
| `POST /investigations` | create an investigation; **auto-classifies topology** (governed_chain vs investigation_board); enforces the 3-per-session quota |
| `GET /investigations` | list this session's investigations |
| `GET /investigations/{id}` | detail: findings, board decision, authorized result (populated in later phases) |
| `POST /investigations/{id}/followup` | attach a follow-up (max 2 per investigation), reusing the investigation |
| `GET /data-sources` | connected sources + bundled samples (Northwind/Chinook) |
| `GET /system/status` | DB, Band, LLM backend, cached plans, counts — for the System Status page |

**Sessions** are anonymous: the first call returns a `session_token`; send it
back as the `X-Session-Token` header to keep your quota and history.

## Quick smoke

```
python tests/test_backend_phase1.py     # topology routing, quota, follow-ups
```

## PostgreSQL / production (Render)

Set `DATABASE_URL` to your Postgres URL and run migrations instead of the dev
auto-create:

```
export DATABASE_URL="postgresql+psycopg://user:pass@host:5432/quorum"
alembic revision --autogenerate -m "init"   # first time only
alembic upgrade head
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

`render.yaml` (next phase) runs `alembic upgrade head` as the pre-deploy step.

## Env vars (add to `.env`)

```
DATABASE_URL=sqlite:///./quorum_app.db        # or postgresql+psycopg://...
CREDENTIAL_ENCRYPTION_KEY=                     # Fernet key; required for remote DB creds
MAX_INVESTIGATIONS_PER_SESSION=3
MAX_FOLLOWUPS_PER_INVESTIGATION=2
FRONTEND_ORIGIN=*                              # set to the Streamlit URL in prod
# Band passthrough (the agents also read THENVOI_* from .env):
THENVOI_REST_URL=
THENVOI_WS_URL=
LLM_BACKEND=
```

## What's next (per the migration plan)

- **Phase 2** — orchestration wires `POST /investigations` to a live Band room;
  the room listener persists transcript → `room_messages`, findings, verdicts,
  and the authorized result.
- **Phase 3** — Streamlit becomes a pure API client (SSE live feed).
- **Phase 4** — the 5 demo-critical pages (Dashboard, Investigations, Band Room,
  Insights, Audit).
