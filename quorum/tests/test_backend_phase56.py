"""tests/test_backend_phase56.py — dashboard aggregates + enriched system status."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")
from fastapi.testclient import TestClient
from backend.main import create_app


def main():
    with TestClient(create_app()) as c:
        hdr = {"X-Session-Token": c.get("/quota").json()["session_token"]}
        c.post("/investigations", json={"question": "why did profitability decline?"}, headers=hdr)
        c.post("/investigations", json={"question": "top customers by revenue"}, headers=hdr)
        d = c.get("/dashboard/summary", headers=hdr).json()
        for k in ("active_investigations", "review_boards", "escalations",
                  "governance_events", "avg_confidence", "queries_remaining", "recent"):
            assert k in d, k
        assert d["review_boards"] >= 1 and len(d["recent"]) >= 2
        print("PASS dashboard summary:", {k: d[k] for k in ("review_boards", "queries_remaining")})
        s = c.get("/system/status").json()
        for k in ("rooms", "findings", "dictionaries", "semantic_catalog"):
            assert k in s, k
        print("PASS system status enriched:", {k: s[k] for k in ("rooms", "semantic_catalog")})
    print("\nALL BACKEND PHASE 5/6 TESTS PASSED")


if __name__ == "__main__":
    main()
