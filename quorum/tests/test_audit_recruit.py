"""
tests/test_audit_recruit.py — Tests for the audit-trail record, the model map,
and graceful dynamic-recruitment fallback (all offline).
"""
import os, sys, types
sys.modules.setdefault("litellm", types.ModuleType("litellm"))
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); os.chdir(ROOT)
os.environ.setdefault("METRIC_CATALOG_PATH", os.path.join(ROOT, "metric_catalog.yaml"))

from types import SimpleNamespace as NS  # noqa: E402
from pipeline.adapter import QuorumBandAdapter  # noqa: E402


def test_model_map_marks_cost_sentinel_deterministic():
    mm = QuorumBandAdapter._model_map()
    assert mm["cost_sentinel"]["provider"].startswith("deterministic")
    for role in ("supervisor", "sql_analyst", "guardian", "decision_reporter", "adjudicator"):
        assert role in mm and "provider" in mm[role]
    print("model_map:", {k: v["provider"] for k, v in mm.items()})


def test_audit_descriptive_shape():
    est = NS(engine="sqlite", risk_level="low", within_budget=True,
             estimated_rows_scanned=42, estimated_bytes_scanned=None,
             estimated_cost_usd=None, method="explain_query_plan")
    report = NS(normalized_question="top genres by revenue",
                sql_query="SELECT 1", revision_occurred=True, finding="F",
                implication="I", recommended_action="A", risk_level="low",
                approval_required=False, metric_definitions_used=["revenue"],
                llm_call_count=2, total_latency_seconds=1.2)
    validated = NS(sql_result=NS(cost_estimate=est), review_method=NS(value="deterministic"))
    a = QuorumBandAdapter._audit_descriptive(report, validated)
    assert a["intent"] == "descriptive"
    assert a["cost_estimate"]["risk_level"] == "low"
    assert a["governance"]["verdict"] == "pass"
    assert a["governance"]["revision_occurred"] is True
    assert a["decision"]["finding"] == "F"
    assert a["metric_definitions_used"] == ["revenue"]
    assert "timestamp" in a
    print("audit keys:", sorted(a.keys()))


def test_recruit_graceful_without_poster():
    adj = QuorumBandAdapter(role="supervisor")  # no api_key -> _poster is None
    assert adj._poster is None
    assert adj._recruit("room-x", ["investigator", "adjudicator"]) == []
    print("recruit no-op without poster: OK")


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print("PASS", name)
    print("\nALL AUDIT/RECRUIT TESTS PASSED")


if __name__ == "__main__":
    main()
