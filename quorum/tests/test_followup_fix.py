"""tests/test_followup_fix.py — follow-ups create a context-linked child run."""
import os, sys, types, tempfile
sys.modules.setdefault("litellm", types.ModuleType("litellm"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DATABASE_URL"] = "sqlite:///" + tempfile.mktemp(suffix=".db")

from fastapi.testclient import TestClient          # noqa: E402
from backend.main import create_app                 # noqa: E402
from backend.db.base import SessionLocal, Base, engine  # noqa: E402
from backend.db import models                        # noqa: E402
from backend.services.execution import _question_for # noqa: E402

Base.metadata.create_all(bind=engine)


def _seed_parent():
    db = SessionLocal()
    sess = models.Session(); db.add(sess); db.flush()
    ds = models.DataSource(kind="sqlite", display_name="src", connection_meta={"path": "x.db"})
    db.add(ds); db.flush()
    parent = models.Investigation(session_id=sess.id, data_source_id=ds.id, scope_id=None,
                                  question="why did revenue drop?", normalized_question="revenue drop",
                                  topology="investigation_board", status="completed")
    db.add(parent); db.flush()
    db.add(models.BoardDecision(investigation_id=parent.id, headline="funding cost is the driver",
                                confidence="high"))
    db.commit()
    ids = (parent.id, ds.id)
    db.close()
    return ids


def main():
    parent_id, ds_id = _seed_parent()
    with TestClient(create_app()) as c:
        # follow-up creates a CHILD investigation, linked + inheriting the source
        r = c.post(f"/investigations/{parent_id}/followup",
                   json={"question": "show supporting evidence"}).json()
        child_id = r["id"]
        assert child_id != parent_id
        assert r["parent_investigation_id"] == parent_id, r
        assert r["data_source_id"] == ds_id, "follow-up must inherit the data source"
        assert r["followups_used"] == 1
        print("PASS follow-up creates linked child inheriting the data source")

        # parent now lists the follow-up
        parent = c.get(f"/investigations/{parent_id}").json()
        assert any(f["id"] == child_id for f in parent["followups"])
        print("PASS parent exposes its follow-ups:", len(parent["followups"]))

        # context preservation: the child's run question carries parent context
        db = SessionLocal()
        child = db.get(models.Investigation, child_id)
        q = _question_for(db, child)
        db.close()
        assert "revenue drop" in q and "funding cost is the driver" in q and "show supporting evidence" in q, q
        print("PASS context preserved in follow-up question:\n   ", q[:120], "...")

        # quota: 2 allowed, 3rd blocked
        c.post(f"/investigations/{parent_id}/followup", json={"question": "compare prev period"})
        over = c.post(f"/investigations/{parent_id}/followup", json={"question": "third one"})
        assert over.status_code == 429
        print("PASS follow-up quota enforced (3rd -> 429)")
    print("\nALL FOLLOW-UP FIX TESTS PASSED")


if __name__ == "__main__":
    main()
