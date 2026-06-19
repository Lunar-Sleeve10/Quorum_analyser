"""
tests/test_join_barrier.py — Regression test for the distributed diagnostic
join barrier (the keystone non-linear behavior over Band).

This drives the Adjudicator's Band handler (`QuorumBandAdapter._on_adjudicator`)
directly, with NO live network and NO real LLM, simulating N investigator
findings arriving as separate Band messages. It asserts the Adjudicator:

  * holds the barrier until all N findings have arrived, and
  * fires its verdict exactly ONCE (idempotent), after the Nth finding.

The previous in-process smoke test never exercised this path, which is why the
broken barrier (expected=0 -> fire on first finding) shipped green.
"""
import asyncio
import os
import sys
import types

# Stub heavy optional deps so imports succeed offline.
sys.modules.setdefault("litellm", types.ModuleType("litellm"))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("METRIC_CATALOG_PATH", os.path.join(ROOT, "metric_catalog.yaml"))

from config import BandConfig                       # noqa: E402
from pipeline import adapter as adapter_mod          # noqa: E402
from pipeline.adapter import QuorumBandAdapter       # noqa: E402
from pipeline.models import InvestigatorFinding, make_envelope  # noqa: E402
from pipeline.session_context import context_store   # noqa: E402
from pipeline import payload                         # noqa: E402

ROOM = "room-test-1"
INV_ID = "abc123"
FACTORS = ["volume", "avg_price", "mix"]


class FakeMsg:
    def __init__(self, content: str) -> None:
        self.content = content


def _finding(factor: str) -> InvestigatorFinding:
    return InvestigatorFinding(
        envelope=make_envelope(session_id=ROOM, from_role="investigator",
                               channel=BandConfig.CHANNEL_TASKS,
                               topic=BandConfig.TOPIC_INVESTIGATION,
                               to_role="adjudicator"),
        investigation_id=INV_ID, question="why does A trail B?",
        total_factors=len(FACTORS), factor=factor, factor_label=factor.title(),
        a_value=1.0, b_value=2.0, direction="", contribution=0.0,
        explained_share=0.0, verdict="", confidence="", evidence="e",
        inv={"dummy": True})


def main() -> None:
    # --- isolate patches: adjudicate + inv reconstruction are stubbed so the
    #     test focuses purely on the barrier/idempotency logic. ---
    fired: list[dict] = []

    adj = QuorumBandAdapter(role="adjudicator")

    def fake_adjudicate(adapter, inv, findings, *, narrate=False):
        fired.append(dict(findings))
        return {"a_label": "A", "b_label": "B", "gap": 1.0, "headline": "h",
                "primary_factor": FACTORS[0], "findings": [], "ruled_out": [],
                "residual_share": 0.0, "confidence": "high", "recommendation": "r",
                "normalized_question": "q"}

    adj._agent.adjudicate = fake_adjudicate                       # type: ignore
    adapter_mod.inv_from_dict = lambda d: object()                # type: ignore

    # captured handoffs (verdict broadcasts) — avoid any network
    posted: list[str] = []

    async def fake_post(tools, room_id, content, *, target_role):
        posted.append(target_role)
    adj._post = fake_post                                          # type: ignore

    # fresh context (adapter unused because adjudicate is stubbed)
    if context_store.exists(ROOM):
        context_store.remove(ROOM)
    ctx = context_store.create(ROOM, adapter=None)

    async def deliver(n_seen: int) -> None:
        """Deliver finding #n_seen (1-based). Room history holds all findings
        seen so far (Band echoes posted messages), simulating cross-process
        visibility through the room transcript."""
        factor = FACTORS[n_seen - 1]
        adj._history = [FakeMsg(payload.encode(_finding(f))) for f in FACTORS[:n_seen]]
        decoded = payload.decode(payload.encode(_finding(factor)))
        await adj._on_adjudicator(decoded, None, ROOM, ctx)

    asyncio.run(deliver(1))
    assert fired == [], f"barrier should hold after 1/3 findings, got {len(fired)} fire(s)"

    asyncio.run(deliver(2))
    assert fired == [], f"barrier should hold after 2/3 findings, got {len(fired)} fire(s)"

    asyncio.run(deliver(3))
    assert len(fired) == 1, f"barrier should fire exactly once at 3/3, got {len(fired)}"
    assert len(fired[0]) == 3, f"adjudicator must see all 3 findings, saw {len(fired[0])}"

    # idempotency: a late/duplicate arrival must NOT re-fire
    asyncio.run(deliver(3))
    assert len(fired) == 1, f"adjudicator must not re-fire; fired {len(fired)} times"

    print("join steps -> fired counts: [0 after 1, 0 after 2, 1 after 3, 1 after dup]")
    print("findings seen by adjudicator:", sorted(fired[0].keys()))
    print("verdict broadcast target(s):", posted)
    print("\nJOIN BARRIER TEST PASSED")


if __name__ == "__main__":
    main()
