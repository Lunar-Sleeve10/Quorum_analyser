# Phases 2 & 3 — live orchestration + Command Center UI

Phase 2 makes investigations actually run and persist; Phase 3 turns Streamlit
into a pure API client (the Command Center).

## Run it (two processes)

Terminal 1 — backend:
```
pip install -r requirements/backend.txt
# for live agents also: pip install -r requirements.txt   (pandas, plotly, litellm, band-sdk)
uvicorn backend.main:app --reload --port 8000
```

Terminal 2 — UI:
```
pip install -r requirements/frontend.txt
export API_BASE_URL=http://localhost:8000
streamlit run frontend/app.py
```

Put `northwind.db` at `quorum/data/samples/northwind.db` first — it auto-registers
as a selectable data source.

## How a run works (Phase 2)

`POST /investigations` persists the investigation, picks the **topology**
(governed_chain vs investigation_board), and kicks off execution in the
background. Two execution backends, one persistence path:

- **Band mode** (when Band creds are configured): drives a real Band room via the
  console bridge; the listener polls the room, persists every message
  (sanitized) to `room_messages`, and records findings, the board verdict, and
  the authorized result.
- **Local mode** (fallback, no Band creds): runs the verified in-process engine
  and synthesizes the room transcript from the execution plan + trace — so the
  Band Room page is populated either way.

Both write the same tables: `rooms`, `room_messages`, `findings`,
`board_decisions`, `authorized_results`, `governance_events`, `audit_log`.

### Endpoints added
| Endpoint | Purpose |
| --- | --- |
| `GET /rooms/{id}` | room state + full message transcript + active agents |
| `GET /rooms/{id}/stream` | **SSE** live feed: emits messages as they persist, then a terminal status event |

## The Command Center (Phase 3)

`frontend/app.py` is a pure API client (no business logic). Pages:
- **Dashboard** — KPI cards (active investigations, review boards, escalations, queries remaining) + recent decisions.
- **Investigations** — pick a data source, ask a question; the detected topology is shown; quota enforced server-side.
- **Band Room** — room id, status, confidence, the agent-network graph, and the live discussion feed (auto-refreshes while running).
- **Insights** — board verdict + findings (diagnostic) or the authorized result with the right chart (descriptive); audit JSON.
- **Audit Trail** — pick any past investigation → transcript replay + decision + download JSON.
- **Data Sources / System Status** — connected sources; DB/Band/LLM health.

## Tests
```
python tests/test_backend_phase1.py    # topology routing, quota, follow-ups
python tests/test_backend_phase2.py    # executor persists room/findings/verdict/result
python tests/test_frontend_phase3.py   # the Streamlit client is a pure API client
```

## Notes
- In this offline build, local-mode execution needs an LLM configured (Ollama /
  Groq / AI/ML API) for the SQL Analyst + diagnostic decomposition — the same as
  the original console. With no LLM/Band the API stays up and marks the run
  `error` gracefully (it never crashes the request).
- SSE is single-process / DB-poll based (no Redis); fine for the demo. Swap in
  Redis pub/sub later for horizontal scale (roadmap).
- Next: Phase 4 polish (theme + remaining pages), then Phase 7 Render deploy
  (`render.yaml`, migrations, health, agents worker).
