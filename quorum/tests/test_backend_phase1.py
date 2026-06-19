"""tests/test_backend_phase1.py — Phase 1 backend API regression (SQLite, offline)."""
import os, sys, tempfile
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient   # noqa: E402
from backend.main import create_app          # noqa: E402


def main():
    with TestClient(create_app()) as c:
        assert c.get("/healthz").json()["status"] == "ok"
        hdr = {"X-Session-Token": c.get("/quota").json()["session_token"]}

        # topology routing
        cases = {"why did profitability decline?": "investigation_board",
                 "top 10 customers by revenue": "governed_chain"}
        ids = {}
        for q, exp in cases.items():
            r = c.post("/investigations", json={"question": q}, headers=hdr).json()
            assert r["topology"] == exp, (q, r["topology"])
            ids[exp] = r["id"]
        print("PASS topology routing")

        # follow-up attaches + quota
        fu = c.post(f"/investigations/{ids['investigation_board']}/followup",
                    json={"question": "explain confidence"}, headers=hdr).json()
        assert fu["followups_used"] == 1
        print("PASS follow-up attach")

        # investigation quota: 3rd ok, 4th -> 429
        c.post("/investigations", json={"question": "third"}, headers=hdr)
        over = c.post("/investigations", json={"question": "fourth"}, headers=hdr)
        assert over.status_code == 429
        print("PASS quota enforcement")

        # detail + system
        d = c.get(f"/investigations/{ids['governed_chain']}", headers=hdr).json()
        assert "findings" in d and "board_decision" in d
        assert c.get("/system/status").json()["investigations"] >= 3
        print("PASS detail + system status")
    print("\nALL BACKEND PHASE 1 TESTS PASSED")


if __name__ == "__main__":
    main()
