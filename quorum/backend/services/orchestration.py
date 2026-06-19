"""backend/services/orchestration.py — bridges the API to the Band agent stack.

Phase 1 keeps this thin and import-safe: topology classification works offline;
the live Band run is wrapped behind a lazy import so the backend boots without
the Band SDK / credentials present (dev mode). Later phases connect the room
listener that persists the transcript.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def classify_topology(question: str) -> str:
    """governed_chain (descriptive) vs investigation_board (diagnostic).
    Reuses the deterministic diagnostic gate when the core package is available;
    falls back to a keyword heuristic otherwise."""
    ql = (question or "").lower()
    keyword_diag = any(w in ql for w in ("why", "decline", "declined", "drop", "dropped",
                                         "underperform", "increase", "increasing", "decrease",
                                         "cause", "reason", "driver", "outperform", "trail"))
    core_diag = False
    try:
        from core import investigation
        core_diag = bool(investigation.is_diagnostic(question))
    except Exception:
        core_diag = False
    # Diagnostic if EITHER the deterministic core gate (needs a resolvable A-vs-B
    # comparison) or the intent keywords fire. This matches spec examples like
    # "Why did profitability decline?" that have no explicit comparison.
    return "investigation_board" if (core_diag or keyword_diag) else "governed_chain"


def band_available() -> bool:
    try:
        from core.band_bridge import BandBridge  # noqa: F401
        from config import settings
        return bool(getattr(settings, "dashboard_api_key", ""))
    except Exception:
        return False
