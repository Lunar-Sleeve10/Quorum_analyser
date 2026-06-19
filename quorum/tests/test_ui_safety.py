"""
tests/test_ui_safety.py — Headless tests for the visible-discussion safety layer.

Verifies that the Band room transcript is rendered SAFELY:
  * the raw ```band JSON payload is never leaked into the summary;
  * @mentions become an explicit handoff target;
  * the structured kind becomes a vetted action label (incl. the debate);
  * secrets and stack traces are redacted from the visible feed;
  * the UI builds dataframes only from the authorized run-store payload.
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import ui_safety  # noqa: E402

BAND = '```band\n{"kind": "%s", "data": {"x": 1}}\n```'


def msg(sender, content):
    return {"sender": sender, "content": content}


def test_handoff_and_label():
    content = f"@cost-sentinel Execution success, 10 row(s).\n{BAND % 'SQLResult'}"
    e = ui_safety.transcript([msg("agent.band/sql-analyst", content)])[0]
    assert e["sender"] == "Sql Analyst", e
    assert e["target"] == "Cost Sentinel", e
    assert "wrote and ran the SQL" in e["label"], e
    assert "{" not in e["summary"] and "kind" not in e["summary"], "band JSON leaked!"
    assert "Execution success" in e["summary"], e


def test_debate_is_visible():
    content = f"@sql-analyst Challenge: missing_limit — please revise.\n{BAND % 'RevisionRequest'}"
    e = ui_safety.transcript([msg("agent/governance-guardian", content)])[0]
    assert "challenged the query" in e["label"], "the debate must be visible"
    assert e["target"] == "Sql Analyst"


def test_secret_and_trace_redaction():
    assert ui_safety.safe_summary("here is api_key=sk-12345") == "(internal detail hidden)"
    assert ui_safety.safe_summary("Supervisor error: Traceback (most recent call last)") \
        == "(internal detail hidden)"
    assert ui_safety.safe_summary("PASSWORD is hunter2") == "(internal detail hidden)"


def test_length_cap():
    long = "x" * 500
    assert len(ui_safety.safe_summary(long)) <= 160


def test_authorized_rows_only():
    assert ui_safety.authorized_rows({}) is None
    assert ui_safety.authorized_rows({"result_rows": [], "result_columns": ["a"]}) is None
    got = ui_safety.authorized_rows(
        {"result_rows": [[1, 2]], "result_columns": ["a", "b"]})
    assert got == ([[1, 2]], ["a", "b"])


def test_no_client_side_sql_in_ui():
    src = open(os.path.join(ROOT, "streamlit_app.py")).read()
    assert "_exec_sql" not in src, "client-side SQL execution must be gone"
    assert "make_adapter" not in src, "UI must not construct a DB adapter to run SQL"


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
    print("\nALL UI-SAFETY TESTS PASSED")


if __name__ == "__main__":
    main()
