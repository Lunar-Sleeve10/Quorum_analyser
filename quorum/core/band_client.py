"""
core/band_client.py — Thin REST wrapper so the console can drive a Band room.

The console (and each agent) post questions/handoffs through the Band REST API
with the SDK's verified signatures. The specialist agents collaborate in the
room and the result comes back via the run-store.

Verified against band-sdk 1.0.0:
  - agent_api_chats.create_agent_chat(chat=ChatRoomRequest(title=...))
  - agent_api_participants.add_agent_chat_participant(chat_id, participant=ParticipantRequest(participant_id=..., role="member"))
  - agent_api_chats.list_agent_chats(page, page_size)
  - agent_api_participants.list_agent_chat_participants(chat_id)
  - agent_api_messages.create_agent_chat_message(chat_id, message=ChatMessageRequest(...))
  - agent_api_identity.get_agent_me()
  (delete_agent_chat is NOT exposed by this SDK version.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://app.band.ai"


@dataclass
class RoomInfo:
    id: str
    name: str


@dataclass
class ParticipantInfo:
    id: str
    handle: str
    name: str


class BandRestError(RuntimeError):
    pass


class BandDashboardClient:
    """Posts into a Band room as the identity behind `api_key`."""

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        if not api_key:
            raise BandRestError("No Band API key configured.")
        try:
            from band.client.rest import RestClient
        except Exception as exc:  # pragma: no cover
            raise BandRestError(f"Band SDK not installed: {exc}")
        self._client = RestClient(api_key=api_key, base_url=base_url)

    # -- connection check -------------------------------------------------
    def whoami(self) -> dict:
        me = self._client.agent_api_identity.get_agent_me()
        data = getattr(me, "data", me)
        return {"id": getattr(data, "id", None), "handle": getattr(data, "handle", None),
                "name": getattr(data, "name", None)}

    # -- room lifecycle (VERIFIED) ---------------------------------------
    def create_room(self, name: str) -> RoomInfo:
        from band.client.rest import ChatRoomRequest
        try:
            resp = self._client.agent_api_chats.create_agent_chat(
                chat=ChatRoomRequest(title=name))
        except Exception as exc:
            raise BandRestError(f"create_room failed: {exc}") from exc
        data = getattr(resp, "data", resp)
        room_id = getattr(data, "id", None) or (data.get("id") if isinstance(data, dict) else None)
        room_name = (getattr(data, "name", None) or getattr(data, "title", None)
                     or (data.get("name") if isinstance(data, dict) else None)
                     or (data.get("title") if isinstance(data, dict) else None) or name)
        if not room_id:
            raise BandRestError(f"create_room returned no room id. Response={data!r}")
        logger.info("Created room '%s' (%s)", room_name, room_id)
        return RoomInfo(id=str(room_id), name=str(room_name))

    def add_agent(self, chat_id: str, agent_id: str) -> bool:
        from band.client.rest import ParticipantRequest
        try:
            self._client.agent_api_participants.add_agent_chat_participant(
                chat_id, participant=ParticipantRequest(participant_id=agent_id, role="member"))
            logger.info("Added participant %s to room %s", agent_id, chat_id)
            return True
        except Exception as exc:
            logger.error("Failed adding participant %s to room %s: %s", agent_id, chat_id, exc)
            return False

    def delete_room(self, chat_id: str) -> bool:
        # band-sdk 1.0.0 does not expose delete_agent_chat(); deletion is a no-op.
        logger.warning("Band SDK has no delete_agent_chat(); cannot delete room %s", chat_id)
        return False

    # -- rooms / participants --------------------------------------------
    def list_rooms(self, limit: int = 50) -> list[RoomInfo]:
        resp = self._client.agent_api_chats.list_agent_chats(page=1, page_size=limit)
        rooms: list[RoomInfo] = []
        for it in self._items(resp):
            rid = getattr(it, "id", None) or (it.get("id") if isinstance(it, dict) else None)
            name = (getattr(it, "name", None) or getattr(it, "title", None)
                    or (it.get("name") if isinstance(it, dict) else None) or rid)
            if rid:
                rooms.append(RoomInfo(id=str(rid), name=str(name)))
        return rooms

    def list_participants(self, chat_id: str) -> list[ParticipantInfo]:
        resp = self._client.agent_api_participants.list_agent_chat_participants(chat_id)
        out: list[ParticipantInfo] = []
        for it in self._items(resp):
            pid = getattr(it, "id", None) or (it.get("id") if isinstance(it, dict) else None)
            handle = getattr(it, "handle", None) or (it.get("handle") if isinstance(it, dict) else None) or ""
            name = getattr(it, "name", None) or (it.get("name") if isinstance(it, dict) else None) or ""
            if pid:
                out.append(ParticipantInfo(id=str(pid), handle=str(handle), name=str(name)))
        return out

    def find_participant(self, chat_id: str, *, role_slug: str = "supervisor") -> Optional[ParticipantInfo]:
        slug = role_slug.lower()
        for p in self.list_participants(chat_id):
            tail = p.handle.split("/")[-1].strip().lower()
            if tail == slug or p.name.strip().lower() == slug or p.name.strip().lower().replace(" ", "-") == slug:
                return p
        return None

    # -- reading messages (Live Review Board) ----------------------------
    def list_messages(self, chat_id: str, limit: int = 100) -> list[dict]:
        """Return recent room messages (oldest->newest) as
        {id, sender, content, ts}. Used by the console to stream the agents'
        conversation live. Method name follows the verified SDK convention."""
        svc = self._client.agent_api_messages
        fn = (getattr(svc, "list_agent_chat_messages", None)
              or getattr(svc, "list_agent_chat_message", None)
              or getattr(svc, "list_agent_messages", None)
              or getattr(svc, "list_messages", None))
        if fn is None:
            logger.error(
                "BAND MESSAGE API NOT FOUND. Available methods=%s",
                dir(svc),
            )
            return []
        logger.warning(
            "BAND MESSAGE FUNCTION=%s ROOM=%s",
            getattr(fn, "__name__", str(fn)),
            chat_id,
            )
        try:
            try:
                resp = fn(chat_id, page=1, page_size=limit)
            except TypeError:
                resp = fn(chat_id)
        except Exception as exc:
            logger.exception("BAND MESSAGE CALL FAILED")
            return []
        logger.warning("BAND RAW RESPONSE TYPE=%s", type(resp))
        logger.warning("BAND RAW RESPONSE=%r", resp)

        items = self._items(resp)

        logger.warning(
            "BAND EXTRACTED ITEMS count=%s sample=%s",
            len(items),
            items[:2] if items else []
            )
        out: list[dict] = []
        for it in items:
            logger.warning(
                  "MESSAGE sender=%s content=%s",
                   getattr(it, "sender_name", None),
                  str(getattr(it, "content", ""))[:120],
            )
            def g(o, *names):
                for n in names:
                    v = getattr(o, n, None) if not isinstance(o, dict) else o.get(n)
                    if v is not None:
                        return v
                return None
            sender = g(it, "sender_name", "sender", "from", "author", "name")
            if isinstance(sender, (dict,)) or hasattr(sender, "name"):
                sender = g(sender, "name", "handle") if sender else None
            out.append({
                "id": g(it, "id", "message_id"),
                "sender": str(sender) if sender else "",
                "content": g(it, "content", "body", "text") or "",
                "ts": g(it, "inserted_at", "created_at", "timestamp", "ts"),
            })
        return out

    # -- posting ----------------------------------------------------------
    def ask(self, chat_id: str, question: str, *, target_role_slug: str = "supervisor") -> dict:
        """Post '@<target> <content>' into the room, with a structured mention."""
        from band.client.rest import ChatMessageRequest, ChatMessageRequestMentionsItem
        target = self.find_participant(chat_id, role_slug=target_role_slug)
        if target is None:
            raise BandRestError(
                f"No participant matching '{target_role_slug}' in room {chat_id}. "
                "Make sure the agent is added to the room.")
        handle_tag = target.handle or target.name
        content = f"@{handle_tag} {question}".strip()
        message = ChatMessageRequest(
            content=content,
            mentions=[ChatMessageRequestMentionsItem(
                id=target.id, handle=target.handle or None, name=target.name or None)])
        resp = self._client.agent_api_messages.create_agent_chat_message(chat_id, message=message)
        data = getattr(resp, "data", resp)
        return {"message_id": getattr(data, "id", None), "content": content, "target": handle_tag}

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _items(resp):
        data = getattr(resp, "data", resp)
        for attr in ("items", "results", "participants", "chats", "messages", "data"):
            value = getattr(data, attr, None)
            if isinstance(value, (list, tuple)):
                return list(value)
        if isinstance(data, (list, tuple)):
            return list(data)
        return []
