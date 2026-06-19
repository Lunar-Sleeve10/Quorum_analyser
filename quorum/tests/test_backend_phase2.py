"""tests/test_backend_phase2.py — Phase 2 executor + persistence (offline).

Runs the LOCAL executor with a fake router against a tiny SQLite DB and asserts
the full schema is persisted and queryable through the API: room + messages,
authorized result (descriptive), findings + board decision (diagnostic).
"""
import os, sys, types, sqlite3, tempfile, random

sys.modules.setdefault("litellm", types.ModuleType("litellm"))
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); os.chdir(ROOT)

# --- tiny chinook-like DB (USA orders more than Germany) ---
DB = tempfile.mktemp(suffix=".db")
con = sqlite3.connect(DB); cur = con.cursor()
cur.executescript("""
CREATE TABLE Genre(GenreId INTEGER PRIMARY KEY, Name TEXT);
CREATE TABLE Track(TrackId INTEGER PRIMARY KEY, GenreId INTEGER);
CREATE TABLE Invoice(InvoiceId INTEGER PRIMARY KEY, CustomerId INTEGER, BillingCountry TEXT, Total NUMERIC);
CREATE TABLE InvoiceLine(InvoiceLineId INTEGER PRIMARY KEY, InvoiceId INTEGER, TrackId INTEGER, UnitPrice NUMERIC, Quantity INTEGER);
CREATE TABLE Customer(CustomerId INTEGER PRIMARY KEY, Country TEXT);
""")
cur.executemany("INSERT INTO Genre VALUES(?,?)", [(1,"Rock"),(2,"Jazz"),(3,"Metal")])
cur.executemany("INSERT INTO Track VALUES(?,?)", [(t, g) for g in (1,2,3) for t in range((g-1)*10+1, g*10+1)])
cur.executemany("INSERT INTO Customer VALUES(?,?)", [(c,"USA" if c%2 else "Germany") for c in range(1,21)])
random.seed(1); inv=[]; il=[]; iid=1; ilid=1
for c in range(1,21):
    for _ in range(5 if c<=12 else 2):
        country="USA" if c%2 else "Germany"
        inv.append((iid,c,country,0))
        gt = random.choice(range(1,11)) if c<=12 else random.choice(range(11,21))
        for _ in range(random.randint(1,4)):
            il.append((ilid,iid,gt, round(random.uniform(0.99,1.99),2),1)); ilid+=1
        iid+=1
cur.executemany("INSERT INTO Invoice VALUES(?,?,?,?)", inv)
cur.executemany("INSERT INTO InvoiceLine VALUES(?,?,?,?,?)", il)
con.commit(); con.close()

os.environ["DB_PATH"] = DB
os.environ["METRIC_CATALOG_PATH"] = os.path.join(ROOT, "metric_catalog.yaml")
os.environ["MEMORY_DIR"] = tempfile.mkdtemp()
os.environ["GROQ_API_KEY"] = ""
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from core.llm_router import LLMResponse  # noqa: E402


class FakeRouter:
    def complete(self, *, provider, model, prompt, temperature=None, max_tokens=None):
        if "produce a short construction plan" in prompt.lower():
            c = ("JOINS: InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId\n"
                 "AGGREGATION: SUM(il.UnitPrice*il.Quantity) grouped by g.Name\nFILTERS: none\n"
                 "OUTPUT: g.Name, revenue\nORDER/LIMIT: revenue DESC LIMIT 5")
        elif "Decompose the metric" in prompt:
            c = '{"metric_expr":"SUM(UnitPrice*Quantity)","factors":[{"key":"vol","label":"Volume","expr":"COUNT(*)","question":"more rows?"},{"key":"avg","label":"Avg","expr":"SUM(UnitPrice*Quantity)*1.0/NULLIF(COUNT(*),0)","question":"higher avg?"}]}'
        elif "relevant_tables" in prompt or "Return ONLY this JSON" in prompt:
            c = ('{"is_clear": true, "clarification_message": "", "query_pattern": "ranking", '
                 '"normalized_question": "top genres by revenue", "complexity": "medium", '
                 '"subtasks": ["join","aggregate","rank"], "relevant_tables": ["Genre","Track","InvoiceLine"], '
                 '"relevant_columns": {"Genre":["Name","GenreId"],"Track":["TrackId","GenreId"],"InvoiceLine":["TrackId","UnitPrice","Quantity"]}}')
        else:
            c = ("```sql\nSELECT g.Name AS genre, SUM(il.UnitPrice*il.Quantity) AS revenue "
                 "FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId "
                 "GROUP BY g.Name ORDER BY revenue DESC LIMIT 5;\n```")
        return LLMResponse(content=c, model=model, provider=provider, tokens_in=5, tokens_out=5, latency_ms=1.0)
    async def acomplete(self, **kw):
        return self.complete(**kw)


from fastapi.testclient import TestClient          # noqa: E402
from backend.main import create_app                 # noqa: E402
from backend.db.base import SessionLocal, Base, engine  # noqa: E402
from backend.db import models                        # noqa: E402
from backend.services.execution import execute_investigation  # noqa: E402

Base.metadata.create_all(bind=engine)


def _new_investigation(question, topology, ds_id, sess_id):
    db = SessionLocal()
    try:
        inv = models.Investigation(session_id=sess_id, data_source_id=ds_id,
                                   question=question, topology=topology, status="planning")
        db.add(inv); db.commit(); db.refresh(inv)
        return inv.id
    finally:
        db.close()


def main():
    db = SessionLocal()
    sess = models.Session(); db.add(sess)
    ds = models.DataSource(kind="sqlite", display_name="tiny", is_sample=True,
                           connection_meta={"path": DB})
    db.add(ds); db.commit(); ds_id, sess_id = ds.id, sess.id
    db.close()

    app = create_app()
    with TestClient(app) as c:
        # --- descriptive ---
        d_id = _new_investigation("top 5 genres by revenue", "governed_chain", ds_id, sess_id)
        execute_investigation(d_id, router=FakeRouter())
        got = c.get(f"/investigations/{d_id}").json()
        assert got["status"] == "completed", got["status"]
        assert got["authorized_result"] and got["authorized_result"]["row_count"] > 0
        room = c.get(f"/rooms/{d_id}").json()
        senders = {m["sender"] for m in room["messages"]}
        assert len(room["messages"]) >= 4 and "Supervisor" in senders
        print(f"PASS descriptive — rows={got['authorized_result']['row_count']}, "
              f"messages={len(room['messages'])}, agents={room['active_agents']}")

        # --- diagnostic ---
        g_id = _new_investigation("why does the USA generate more revenue than Germany?",
                                  "investigation_board", ds_id, sess_id)
        execute_investigation(g_id, router=FakeRouter())
        got = c.get(f"/investigations/{g_id}").json()
        assert got["status"] == "completed"
        assert got["board_decision"] and got["board_decision"]["headline"]
        assert len(got["findings"]) >= 2, got["findings"]
        room = c.get(f"/rooms/{g_id}").json()
        assert len(room["messages"]) >= 4
        print(f"PASS diagnostic — findings={len(got['findings'])}, "
              f"primary={got['board_decision']['primary_factor']}, "
              f"confidence={got['confidence']}, messages={len(room['messages'])}")

    print("\nALL BACKEND PHASE 2 TESTS PASSED")


if __name__ == "__main__":
    main()
