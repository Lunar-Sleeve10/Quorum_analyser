"""
core/band_bridge.py — Drive a Band room from the Streamlit console.

Room lifecycle
--------------
Band rooms are expensive to proliferate: Band provides no deletion API, every
room carries subscription overhead for all agents, and dangling rooms can
confuse the run-store sweep.

The bridge therefore reuses rooms aggressively:

  • One room per (session, data_source) pair.  All investigations that share a
    session *and* target the same database reuse the same room.
  • A new room is created only when the user switches to a different data source
    within a session, or when no room has ever been opened for the current pair.
  • The lookup/mint decision is made by ``get_or_create_room()``, which checks
    the ``session_rooms`` DB table before ever calling the Band API.

Two room-creation modes (unchanged from before):
  • Fixed room  — set BAND_ROOM_ID=<id> in .env; the room is always reused
    regardless of session/data-source.  Useful in demos / single-tenant deploys.
  • Auto-create — no BAND_ROOM_ID set; the bridge creates a room on first use
    per (session, data_source) pair and records it in ``session_rooms``.

Requires DASHBOARD_API_KEY in .env and agent_config.yaml with the seven agents'
UUIDs.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from sqlalchemy.orm import Session as DbSession

from config import settings
from core.band_client import BandDashboardClient, RoomInfo

load_dotenv()
logger = logging.getLogger(__name__)

# Roles whose agents must be present in every room.
ROOM_ROLES = [
    "supervisor", "sql_analyst", "cost_sentinel", "guardian",
    "decision_reporter", "investigator", "adjudicator",
]

_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = _ROOT / "agent_config.yaml"


# ---------------------------------------------------------------------------
# Agent-config helpers (unchanged)
# ---------------------------------------------------------------------------

def _load_agent_ids() -> dict[str, str]:
    p = _CONFIG if _CONFIG.exists() else Path("agent_config.yaml")
    if not p.exists():
        raise FileNotFoundError(
            "agent_config.yaml not found. Copy agent_config.example.yaml and fill "
            "in your seven agents' UUIDs/keys."
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    ids: dict[str, str] = {}
    for role in ROOM_ROLES:
        entry = data.get(role) or {}
        aid = str(entry.get("agent_id", "")).strip()
        if aid and not aid.startswith("<"):
            ids[role] = aid
    return ids


# ---------------------------------------------------------------------------
# BandBridge
# ---------------------------------------------------------------------------

class BandBridge:
    """Thin wrapper around BandDashboardClient with session-scoped room reuse.

    Callers should prefer ``get_or_create_room(db, session_id, data_source_id)``
    over the old ``start_fresh_session()``; the latter is kept for backward
    compatibility with any non-DB callers (e.g. the Streamlit console) but now
    also consults the DB when one is supplied.
    """

    def __init__(self) -> None:
        if not settings.dashboard_api_key:
            raise RuntimeError(
                "DASHBOARD_API_KEY is not set — add it to .env to drive Band from the console."
            )
        self.client = BandDashboardClient(settings.dashboard_api_key, settings.band_rest_url)
        self.agent_ids = _load_agent_ids()
        self.fixed_room_id = os.getenv("BAND_ROOM_ID", "").strip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add_agents(self, room_id: str) -> int:
        added = 0
        for role, aid in self.agent_ids.items():
            try:
                if self.client.add_agent(room_id, aid):
                    added += 1
            except Exception as exc:
                logger.warning("add_agent(%s) failed: %s", role, exc)
        logger.info("Room %s: ensured %d/%d agents", room_id, added, len(self.agent_ids))
        return added

    def _create_band_room(self, name: str) -> RoomInfo:
        """Create a new Band room via the API. Raises RuntimeError when
        auto-create is unavailable and no fixed room is configured."""
        try:
            return self.client.create_room(name)
        except Exception as exc:
            raise RuntimeError(
                "Could not create a Band room automatically.\n"
                f"Reason: {exc}\n\n"
                "Fix (recommended): create a room in the Band UI, add your 7 agents, "
                "then set BAND_ROOM_ID=<that room id> in .env to reuse it."
            ) from exc

    # ------------------------------------------------------------------
    # Primary API — session-scoped room reuse
    # ------------------------------------------------------------------

    def get_or_create_room(
        self,
        db: DbSession,
        session_id: str,
        data_source_id: Optional[str] = None,
    ) -> RoomInfo:
        """Return a Band room for the (session, data_source) pair, creating one
        only when none exists yet for that pair.

        Decision tree
        ~~~~~~~~~~~~~
        1. Fixed-room mode (BAND_ROOM_ID set) → always return that room; no DB
           lookup needed, agents are ensured on every call.
        2. Look up ``session_rooms`` for an existing (session_id, data_source_id)
           row → if found, bump ``last_used_at`` and return it without touching
           the Band API.
        3. No existing row → create a new Band room, persist a ``SessionRoom``
           row, ensure agents, and return it.

        The caller is responsible for committing the DB session after this
        returns; the new SessionRoom row is flushed but not committed here so
        it participates in the caller's transaction boundary.
        """
        from backend.db import models  # deferred to avoid circular imports

        # -- Fixed-room mode: skip the DB entirely, always reuse
        if self.fixed_room_id:
            room = RoomInfo(id=self.fixed_room_id, name="Quorum (fixed room)")
            self._add_agents(room.id)
            logger.info("Fixed Band room reused: %s (session=%s ds=%s)",
                        room.id, session_id, data_source_id)
            return room

        # -- Look for an existing session room
        existing: Optional[models.SessionRoom] = (
            db.query(models.SessionRoom)
            .filter_by(session_id=session_id, data_source_id=data_source_id)
            .first()
        )
        if existing is not None:
            existing.last_used_at = datetime.now(timezone.utc)
            db.add(existing)
            logger.info(
                "Reusing Band room %s for session=%s ds=%s",
                existing.band_room_id, session_id, data_source_id,
            )
            return RoomInfo(id=existing.band_room_id, name="Quorum (reused)")

        # -- No room yet for this (session, data_source) → create one
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        ds_tag = f" ds={data_source_id[:6]}" if data_source_id else ""
        name = f"Quorum {ts}{ds_tag}"
        room = self._create_band_room(name)
        self._add_agents(room.id)

        sr = models.SessionRoom(
            session_id=session_id,
            data_source_id=data_source_id,
            band_room_id=room.id,
        )
        db.add(sr)
        db.flush()  # assign PK; caller commits

        logger.warning(
            "Created Band room %s for session=%s ds=%s",
            room.id, session_id, data_source_id,
        )
        return room

    # ------------------------------------------------------------------
    # Legacy API — kept for Streamlit console and other non-DB callers
    # ------------------------------------------------------------------

    def start_fresh_session(
        self,
        db: Optional[DbSession] = None,
        session_id: Optional[str] = None,
        data_source_id: Optional[str] = None,
    ) -> RoomInfo:
        """Back-compat shim.

        When ``db`` and ``session_id`` are supplied this delegates to
        ``get_or_create_room()`` so the Streamlit console benefits from reuse
        too.  When called without those arguments (old behaviour) it creates a
        new room unconditionally, which is only correct for fixed-room mode
        (the console never needs auto-create today).
        """
        if db is not None and session_id:
            return self.get_or_create_room(db, session_id, data_source_id)

        # Legacy path: fixed-room only; warn if auto-create would be needed
        if self.fixed_room_id:
            room = RoomInfo(id=self.fixed_room_id, name="Quorum (fixed room)")
            self._add_agents(room.id)
            logger.info("start_fresh_session (legacy): fixed room %s", room.id)
            return room

        logger.warning(
            "start_fresh_session called without db/session_id — creating a new room. "
            "Pass db and session_id to enable room reuse."
        )
        name = "Quorum " + datetime.now(timezone.utc).strftime("%H:%M:%S")
        room = self._create_band_room(name)
        self._add_agents(room.id)
        return room

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def ask(self, room_id: str, question: str) -> dict:
        logger.warning("BAND ASK room_id=%s question_preview=%s", room_id, question[:80])
        return self.client.ask(room_id, question, target_role_slug="supervisor")

    def close(self) -> None:
        return