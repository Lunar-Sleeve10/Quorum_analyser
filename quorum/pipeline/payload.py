"""
band/payload.py — Wire codec for carrying structured agent messages inside
Band chat-room messages.

Band routes plain-text messages between agents via @mentions. Our agents speak
structured Pydantic contracts (SchemaGroundedTask, SQLResult, RevisionRequest,
ValidatedResult, FinalReport). This module serializes one of those contracts
into a fenced block embedded in an otherwise human-readable message, and parses
it back out on the receiving side.

Wire format of a message body:

    @SQL Engineer  Handing off a grounded task.
    ```band
    {"kind": "SchemaGroundedTask", "data": { ... }}
    ```

The human-readable prefix is for people reading the room; the ```band fenced
JSON is the machine payload. Parsing is tolerant: if no band block is present
(e.g. a human typed a plain question), `decode` returns a RawText payload so the
adapter can treat it as an initial UserQuery question.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from pydantic import BaseModel

from pipeline.models import (
    BoardDecision,
    FinalReport,
    InvestigationTask,
    InvestigatorFinding,
    RevisionRequest,
    SchemaGroundedTask,
    SQLResult,
    UserQuery,
    ValidatedResult,
)

# Map of message kind -> Pydantic model. Extend here if contracts are added.
_KIND_TO_MODEL: dict[str, type[BaseModel]] = {
    "UserQuery": UserQuery,
    "SchemaGroundedTask": SchemaGroundedTask,
    "SQLResult": SQLResult,
    "RevisionRequest": RevisionRequest,
    "ValidatedResult": ValidatedResult,
    "FinalReport": FinalReport,
    "InvestigationTask": InvestigationTask,
    "InvestigatorFinding": InvestigatorFinding,
    "BoardDecision": BoardDecision,
}
_MODEL_TO_KIND: dict[type[BaseModel], str] = {v: k for k, v in _KIND_TO_MODEL.items()}

_BAND_BLOCK = re.compile(r"```band\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(slots=True)
class RawText:
    """A message with no band payload — typically a human-typed question."""
    text: str


@dataclass(slots=True)
class DecodedPayload:
    """Result of decoding a message body."""
    kind: str
    message: Optional[BaseModel] = None   # parsed contract, if kind is known
    raw: Optional[RawText] = None         # set when no band block was found
    parse_error: Optional[str] = None     # set when a block was found but invalid


def encode(message: BaseModel, *, prefix: str = "") -> str:
    """
    Serialize a Pydantic Band contract into a message body with an optional
    human-readable prefix. Raises if the model type is not registered.
    """
    kind = _MODEL_TO_KIND.get(type(message))
    if kind is None:
        raise ValueError(f"Unregistered message type: {type(message).__name__}")
    envelope = {"kind": kind, "data": json.loads(message.model_dump_json())}
    block = "```band\n" + json.dumps(envelope) + "\n```"
    if prefix:
        return f"{prefix.rstrip()}\n{block}"
    return block


def decode(body: str) -> DecodedPayload:
    """
    Parse a message body. If it contains a ```band block, return the typed
    contract; otherwise return a RawText payload.
    """
    match = _BAND_BLOCK.search(body or "")
    if not match:
        return DecodedPayload(kind="RawText", raw=RawText(text=(body or "").strip()))

    try:
        envelope = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return DecodedPayload(kind="Unknown", parse_error=f"invalid JSON: {exc}")

    kind = str(envelope.get("kind", ""))
    model_cls = _KIND_TO_MODEL.get(kind)
    if model_cls is None:
        return DecodedPayload(kind=kind, parse_error=f"unknown kind: {kind!r}")

    data = envelope.get("data")
    if not isinstance(data, dict):
        return DecodedPayload(kind=kind, parse_error="missing or invalid 'data'")

    try:
        message = model_cls.model_validate(data)
    except Exception as exc:  # pydantic ValidationError or similar
        return DecodedPayload(kind=kind, parse_error=f"validation failed: {exc}")

    return DecodedPayload(kind=kind, message=message)


def human_prefix(kind: str, detail: str = "") -> str:
    """Build a short, readable lead-in line for a handoff message."""
    label = {
        "SchemaGroundedTask": "Grounded task ready",
        "SQLResult": "SQL generated and executed",
        "RevisionRequest": "Revision requested",
        "ValidatedResult": "Review passed",
        "FinalReport": "Final report",
    }.get(kind, kind)
    return f"{label}. {detail}".strip()
