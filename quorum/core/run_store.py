"""
core/run_store.py — Shared run-store bridging the Band agents and any reader.

Band agents run as separate processes, so they cannot share in-memory state.
When the Decision Reporter finishes a run it writes the report to a small JSON
file here; a reader (the console, an API, a dashboard) picks up completed runs
and rebuilds the view by re-running the SQL. Filesystem-based and
dependency-free; the format is plain JSON (the report dump plus metadata).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_DIR = os.getenv("RUN_STORE_DIR", "runs")


def _dir() -> Path:
    p = Path(DEFAULT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_run(report: dict[str, Any], *, room_id: str = "") -> Optional[str]:
    """Persist a completed FinalReport. Returns the run id, or None on failure.
    Atomic write (temp file + rename) so the dashboard never reads a partial."""
    try:
        ts = time.time()
        session = room_id or report.get("envelope", {}).get("session_id", "") or "run"
        run_id = f"{int(ts*1000)}_{session[:12]}"
        record = {
            "run_id": run_id,
            "saved_at": ts,
            "room_id": session,
            "report": report,
        }
        d = _dir()
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(record, f, default=str)
        os.replace(tmp, d / f"{run_id}.json")
        logger.info("Saved run %s to %s", run_id, d)
        return run_id
    except Exception as exc:  # never let persistence break the pipeline
        logger.warning("save_run failed: %s", exc)
        return None


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Return run metadata (newest first): run_id, saved_at, room_id, question."""
    out: list[dict[str, Any]] = []
    for p in sorted(_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
            rep = rec.get("report", {})
            out.append({
                "run_id": rec.get("run_id", p.stem),
                "saved_at": rec.get("saved_at", p.stat().st_mtime),
                "room_id": rec.get("room_id", ""),
                "question": rep.get("normalized_question", ""),
                "risk_level": rep.get("risk_level", ""),
                "approval_required": rep.get("approval_required", False),
                "kind": rep.get("kind", "report"),
            })
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def load_run(run_id: str) -> Optional[dict[str, Any]]:
    p = _dir() / f"{run_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("load_run failed for %s: %s", run_id, exc)
        return None


def latest_run() -> Optional[dict[str, Any]]:
    runs = list_runs(limit=1)
    if not runs:
        return None
    return load_run(runs[0]["run_id"])


def newest_run_after(ts: float, *, room_id: str = "") -> Optional[dict[str, Any]]:
    """Return the newest run saved after `ts` (optionally for a specific room),
    or None if none yet. Used by the dashboard to detect the answer to a
    just-asked question."""
    for r in list_runs(limit=20):
        if r["saved_at"] <= ts:
            continue
        if room_id and r.get("room_id") and r["room_id"] != room_id:
            continue
        return load_run(r["run_id"])
    return None
