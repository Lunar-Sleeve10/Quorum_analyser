# Getting started — every step, from scratch (Windows-first)

This is the hand-held version. Follow it top to bottom after you download the
zip. Commands are shown for **Windows PowerShell** first; macOS/Linux notes are
in parentheses. You only need to do Steps 1–9 to see it working locally.

> What you'll have at the end of Step 9: the backend API running, the Command
> Center open in your browser, and a sample database you can ask questions about.

---

## 0. What you need installed first

- **Python 3.11 or 3.12** — check with `python --version`. If missing, install
  from python.org and tick "Add Python to PATH".
- (Optional, for real answers) an **LLM**: either **Ollama** (free, local — Step 6b)
  or an API key for Groq / AI/ML API.
- (Optional, only for the live Band demo) a **Band account** at app.band.ai.

You do NOT need PostgreSQL — local mode uses SQLite automatically.

---

## 1. Unzip the project

Unzip `quorum_v2_complete.zip`. You'll get a folder called `quorum`.
Remember where it is, e.g. `D:\projects\quorum`.

## 2. Open a terminal IN that folder

- Windows: open the `quorum` folder in File Explorer, click the address bar,
  type `powershell`, press Enter.
- (macOS/Linux: open Terminal and `cd` into the folder.)

Confirm you're in the right place:
```
ls            # you should see backend, frontend, agents, data, render.yaml ...
```

## 3. Create and activate a virtual environment

```
python -m venv venv
venv\Scripts\Activate.ps1
```
(macOS/Linux: `python3 -m venv venv` then `source venv/bin/activate`.)

Your prompt now starts with `(venv)`. If PowerShell blocks activation, run once:
```
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
then activate again.

## 4. Install dependencies

```
pip install -r requirements/backend.txt
pip install -r requirements.txt
```
The first line installs the API/UI stack; the second installs the agent stack
(pandas, plotly, litellm, etc.). This can take a couple of minutes.

## 5. Add the sample database

Put your `northwind.db` file here (exact name and place):
```
quorum\data\samples\northwind.db
```
That's all — the app auto-registers it on startup. (No DB handy? You can skip
this; you just won't have a source to query until you add one.)

## 6. Create your settings file

Copy the example and open it in a text editor:
```
copy .env.example .env       # (macOS/Linux: cp .env.example .env)
notepad .env
```

### 6a. Generate an encryption key (for storing DB credentials safely)
Run this and paste the output after `CREDENTIAL_ENCRYPTION_KEY=` in `.env`:
```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 6b. Pick an LLM (needed for the agents to actually answer)
**Easiest free option — Ollama (local):**
1. Install Ollama from ollama.com.
2. In a terminal: `ollama pull qwen2.5-coder:7b` then `ollama serve`.
3. In `.env` set:
   ```
   LLM_BACKEND=ollama
   ```
**Or use a hosted key** (faster): set `LLM_BACKEND=groq` and `GROQ_API_KEY=...`
(or `LLM_BACKEND=aiml` and the AI/ML API key — see `AIML_INTEGRATION.md`).

Leave `DATABASE_URL` as the default SQLite line for now. Save and close `.env`.

## 7. Start the backend (API)

```
uvicorn backend.main:app --reload --port 8000
```
Leave this terminal running. Check it works:
- Open http://localhost:8000/healthz → you should see `{"status":"ok",...}`.
- Open http://localhost:8000/docs → the interactive API.

## 8. Start the Command Center (UI) — in a SECOND terminal

Open a new PowerShell in the same `quorum` folder, then:
```
venv\Scripts\Activate.ps1
pip install -r requirements/frontend.txt
$env:API_BASE_URL = "http://localhost:8000"
streamlit run frontend/app.py
```
(macOS/Linux: `export API_BASE_URL=http://localhost:8000` instead of the `$env:` line.)

Your browser opens the Command Center (usually http://localhost:8501).

## 9. Use it

1. Left sidebar → **Data Sources** → you should see "Northwind (sample)".
   (Optional: discover schema and pick a scope of ≤3 tables / ≤6 columns.)
2. Sidebar → **Investigations** → choose the data source, type a question:
   - Descriptive: `top 10 customers by revenue`
   - Diagnostic: `why did profitability decline?`
   Click **Ask**. The detected topology is shown.
3. Sidebar → **Band Room** → watch the live discussion + agent network.
4. Sidebar → **Insights** → the chart/verdict; **Audit Trail** → replay + export.

> If a run shows `error`: that almost always means the LLM isn't reachable.
> Re-check Step 6b (is `ollama serve` running, or is your key set?). The API
> itself stays up either way.

You're done with the local demo. Steps 10–12 are optional.

---

## 10. (Optional) Run the REAL Band room

Without this, Quorum uses the built-in local engine. To show true Band
collaboration:

1. On app.band.ai → **Agents → New Agent → Remote Agent**, create **seven**
   agents with these display names: `Supervisor`, `SQL Analyst`, `Cost Sentinel`,
   `Governance Guardian`, `Decision Reporter`, `Investigator`, `Adjudicator`.
2. Copy each agent's **UUID and API key**.
3. Make the config file:
   ```
   copy agent_config.example.yaml agent_config.yaml
   notepad agent_config.yaml
   ```
   Fill in each role's `agent_id` and `api_key` (no `<...>` placeholders left).
4. In `.env` set the Band URLs:
   ```
   THENVOI_REST_URL=https://app.band.ai/
   THENVOI_WS_URL=wss://app.band.ai/api/v1/socket/websocket
   ```
5. Check everything is linked BEFORE launching:
   ```
   python tools/preflight.py
   ```
   Every agent should print `OK -> ...`. If you see `401 / not linked`, the key
   is wrong — recopy it from that agent's page.
6. Launch all seven agents (new terminal, venv activated):
   ```
   python launch_all.py
   ```
   Leave it running. Now investigations run over the real Band room.

## 11. Run the tests (optional, to confirm everything's healthy)

```
python tests/test_backend_phase1.py
python tests/test_backend_phase2.py
python tests/test_backend_phase4.py
python tests/test_backend_phase56.py
python tests/test_frontend_phase3.py
python tests/test_chart_rules.py
python tests/test_join_barrier.py
python tests/test_ui_safety.py
python tests/test_audit_recruit.py
```
Each prints `... PASSED`.

## 12. (Optional) Deploy to Render

1. Put the project on GitHub (new repo, push the `quorum` folder contents).
2. On render.com → **New → Blueprint** → select your repo. It reads
   `render.yaml` and creates: the API, the UI, a Postgres database, and the
   agents worker.
3. When asked, set the secret env vars: `LLM_BACKEND` (+ provider key),
   `THENVOI_REST_URL`, `THENVOI_WS_URL`, and `DB_PATH` for the worker. The
   encryption key is generated automatically; the database URL is wired in.
4. Deploy. Migrations run automatically (`alembic upgrade head`). Open the UI
   service URL. Full details in `DEPLOY_RENDER.md`.

---

## Troubleshooting (the common ones)

- **`ModuleNotFoundError: No module named 'litellm'`** → you skipped part of
  Step 4. Run `pip install -r requirements.txt` (with the venv active).
- **`Form data requires "python-multipart"`** → `pip install python-multipart`
  (it's in `requirements/backend.txt`; re-run that install).
- **Band `401 … API key not linked to a user or agent`** → the keys in
  `agent_config.yaml` aren't valid agent keys. Recreate the agents and recopy
  UUID + key; run `python tools/preflight.py` until all say `OK`.
- **`agent_config.yaml not found`** → you're in Step 10; do `copy
  agent_config.example.yaml agent_config.yaml` and fill it in.
- **UI says "Backend unreachable"** → the API (Step 7) isn't running, or
  `API_BASE_URL` is wrong in the UI terminal.
- **A run shows `error`** → no LLM reachable; see Step 6b.
- **PowerShell won't activate the venv** → run the `Set-ExecutionPolicy` line in
  Step 3, then activate again.

That's it — Steps 1–9 for the local demo, Step 10 for live Band, Step 12 to ship.
