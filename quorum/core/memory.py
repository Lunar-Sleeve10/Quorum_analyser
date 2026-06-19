"""
core/memory.py — Plan & Insight Memory (persistence across sessions).

Two things persist between runs:

  1. Approved-plan cache — keyed by the normalized question + a fingerprint of
     the database schema. A cache hit lets the engine skip planning AND SQL
     generation: it re-executes the certified SQL and rebuilds the view, for
     zero LLM calls. This is both a governance feature (re-use a vetted plan)
     and an efficiency win.

  2. Certified insights — approved findings the organisation can look back on.

Storage is plain JSON files under MEMORY_DIR; dependency-free and inspectable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def schema_fingerprint(schema_text: str) -> str:
    return hashlib.sha1((schema_text or "").encode("utf-8")).hexdigest()[:12]


class Memory:
    def __init__(self, directory: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self.dir = Path(directory)
        self.plans_dir = self.dir / "plans"
        self.insights_path = self.dir / "insights.jsonl"
        if enabled:
            self.plans_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, question: str, schema_fp: str) -> str:
        raw = f"{_norm(question)}::{schema_fp}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    # ---- approved-plan cache -----------------------------------------
    def lookup_plan(self, question: str, schema_fp: str) -> Optional[dict[str, Any]]:
        if not self.enabled:
            return None
        p = self.plans_dir / f"{self._key(question, schema_fp)}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def store_plan(self, question: str, schema_fp: str, record: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            record = {**record, "cached_at": time.time(), "question": question}
            p = self.plans_dir / f"{self._key(question, schema_fp)}.json"
            p.write_text(json.dumps(record, default=str, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("store_plan failed: %s", exc)

    # ---- certified insights ------------------------------------------
    def add_insight(self, insight: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            with self.insights_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**insight, "at": time.time()}, default=str) + "\n")
        except Exception as exc:
            logger.warning("add_insight failed: %s", exc)

    def insights(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.enabled or not self.insights_path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            for line in self.insights_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        except Exception:
            return []
        return out[-limit:][::-1]
