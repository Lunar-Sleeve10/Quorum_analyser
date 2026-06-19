"""Offline smoke test: exercises the engine end-to-end with a fake router and a
tiny SQLite database (no network, no real LLM). Not shipped as a product path."""
import sys, types, os, sqlite3, tempfile

# Stub litellm so importing the router works without the heavy dependency.
sys.modules.setdefault("litellm", types.ModuleType("litellm"))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

# --- build a tiny chinook-like DB ---
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
tracks=[]; tid=1
for g in (1,2,3):
    for _ in range(10):
        tracks.append((tid,g)); tid+=1
cur.executemany("INSERT INTO Track VALUES(?,?)", tracks)
# customers
cur.executemany("INSERT INTO Customer VALUES(?,?)", [(c,"USA" if c%2 else "Germany") for c in range(1,21)])
inv=[]; il=[]; iid=1; ilid=1
import random; random.seed(1)
for c in range(1,21):
    n_orders = 5 if c<=12 else 2   # Rock buyers order more
    for _ in range(n_orders):
        country="USA" if c%2 else "Germany"
        inv.append((iid,c,country,0)); 
        # rock tracks 1-10, jazz 11-20, metal 21-30
        genre_track = random.choice(range(1,11)) if c<=12 else random.choice(range(11,21))
        for _ in range(random.randint(1,4)):
            il.append((ilid,iid,genre_track, round(random.uniform(0.99,1.99),2), 1)); ilid+=1
        iid+=1
cur.executemany("INSERT INTO Invoice VALUES(?,?,?,?)", inv)
cur.executemany("INSERT INTO InvoiceLine VALUES(?,?,?,?,?)", il)
con.commit(); con.close()

# --- point settings at the test db/catalog ---
os.environ["DB_PATH"]=DB
os.environ["METRIC_CATALOG_PATH"]=os.path.join(ROOT,"metric_catalog.yaml")
os.environ["MEMORY_DIR"]=tempfile.mkdtemp()
os.environ["GROQ_API_KEY"]=""   # forces reporter to deterministic summary

from config import LLMProvider
from core.llm_router import LLMResponse

class FakeRouter:
    """Returns canned grounding JSON for the planner and canned SQL for the analyst."""
    def complete(self, *, provider, model, prompt, temperature=None, max_tokens=None):
        if "produce a short construction plan" in prompt.lower():
            content = ("JOINS: InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId JOIN Genre g ON t.GenreId=g.GenreId\n"
                       "AGGREGATION: SUM(il.UnitPrice*il.Quantity) grouped by g.Name\n"
                       "FILTERS: none\nOUTPUT: g.Name, revenue\nORDER/LIMIT: revenue DESC LIMIT 5")
            return LLMResponse(content=content, model=model, provider=provider, tokens_in=5, tokens_out=5, latency_ms=1.0)
        if "Decompose the metric" in prompt:
            content = '{"metric_expr":"SUM(UnitPrice*Quantity)","factors":[{"key":"vol","label":"Volume","expr":"COUNT(*)","question":"more rows?"},{"key":"avg","label":"Avg","expr":"SUM(UnitPrice*Quantity)*1.0/NULLIF(COUNT(*),0)","question":"higher avg?"}]}'
            return LLMResponse(content=content, model=model, provider=provider, tokens_in=5, tokens_out=5, latency_ms=1.0)
        if "relevant_tables" in prompt or "Return ONLY this JSON" in prompt:
            content = ('{"is_clear": true, "clarification_message": "", '
                       '"query_pattern": "ranking", "normalized_question": "top genres by revenue", '
                       '"complexity": "medium", "subtasks": ["join","aggregate","rank"], '
                       '"relevant_tables": ["Genre","Track","InvoiceLine"], '
                       '"relevant_columns": {"Genre":["Name","GenreId"],"Track":["TrackId","GenreId"],"InvoiceLine":["TrackId","UnitPrice","Quantity"]}}')
        else:
            content = ("```sql\nSELECT g.Name AS genre, SUM(il.UnitPrice*il.Quantity) AS revenue "
                       "FROM InvoiceLine il JOIN Track t ON il.TrackId=t.TrackId "
                       "JOIN Genre g ON t.GenreId=g.GenreId GROUP BY g.Name "
                       "ORDER BY revenue DESC LIMIT 5;\n```")
        return LLMResponse(content=content, model=model, provider=provider,
                           tokens_in=10, tokens_out=10, latency_ms=1.0)
    async def acomplete(self, **kw):
        return self.complete(**kw)

from core.coordination import AnalyticsEngine
eng = AnalyticsEngine(router=FakeRouter())

print("\n=== DESCRIPTIVE ===")
r = eng.run("top 5 genres by revenue", db_path=DB, db_type="sqlite")
print("status:", r.status, "| intent:", r.intent, "| llm_calls:", r.llm_call_count)
print("chart:", r.report.get("chart_type"), "| reason:", r.report.get("viz_reason"))
print("finding:", r.report.get("finding")[:80])
print("plan steps:", [(s["id"],s["status"]) for s in r.plan["steps"]])
assert r.status=="completed" and r.intent=="descriptive"
assert r.dataframe is not None and len(r.dataframe)>0

print("\n=== DESCRIPTIVE (cache hit) ===")
r2 = eng.run("top 5 genres by revenue", db_path=DB, db_type="sqlite")
print("cache_hit:", r2.cache_hit, "| llm_calls:", r2.llm_call_count)

print("\n=== DIAGNOSTIC ===")
d = eng.run("why does Rock generate more revenue than Jazz?", db_path=DB, db_type="sqlite")
print("status:", d.status, "| intent:", d.intent, "| llm_calls:", d.llm_call_count)
print("headline:", d.report.get("headline"))
print("primary:", d.report.get("primary_factor"), "| confidence:", d.report.get("confidence"))
print("plan steps:", [(s["id"],s["status"]) for s in d.plan["steps"]])
print("trace:")
for t in d.trace: print("  -", t)
assert d.status=="completed" and d.intent=="diagnostic"
assert len(d.report["findings"])>=2

print("\nALL SMOKE TESTS PASSED")
