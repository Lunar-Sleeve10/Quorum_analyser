"""
agents/base.py — Abstract base class for all agents.

Defines the common contract: every agent has a role, consumes a typed input
message, produces a typed output message, and emits telemetry. Business logic
is NOT implemented here — only the shared lifecycle, LLM access, context
access, and telemetry plumbing. Concrete agents implement `_run` (sync) and
`_arun` (async); the public `run`/`arun` wrap them with start/complete
telemetry and timing.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Generic, Optional, TypeVar

from pipeline.models import (
    AgentEvent,
    BandMessage,
    Presence,
    Role,
    make_envelope,
)
from pipeline.session_context import SessionContext, context_store
from config import BandConfig, LLMProvider
from core.llm_router import LLMResponse, LLMRouter, router as default_router

logger = logging.getLogger(__name__)

# Typed input/output message generics
TIn = TypeVar("TIn", bound=BandMessage)
TOut = TypeVar("TOut", bound=BandMessage)


class TelemetrySink(ABC):
    """Abstract telemetry destination. Band client implements this later."""

    @abstractmethod
    def emit(self, event: AgentEvent) -> None: ...

    async def aemit(self, event: AgentEvent) -> None:
        self.emit(event)


class NullTelemetrySink(TelemetrySink):
    """Logs telemetry events instead of sending them over Band."""

    def emit(self, event: AgentEvent) -> None:
        logger.debug(
            "telemetry role=%s type=%s detail=%s",
            event.role, event.event_type, event.detail,
        )


class BaseAgent(ABC, Generic[TIn, TOut]):
    """
    Common base for the four agents.

    Subclasses set `role`, `provider`, and `model`, then implement `_run`
    and `_arun`. The wrapper methods handle telemetry, timing, and LLM-call
    accounting against SessionContext.
    """

    role: Role

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        llm_router: Optional[LLMRouter] = None,
        telemetry: Optional[TelemetrySink] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.router = llm_router or default_router
        self.telemetry = telemetry or NullTelemetrySink()
        self.agent_id = agent_id or f"{self.role}-0"

    # ------------------------------------------------------------------
    # Context access
    # ------------------------------------------------------------------

    def context(self, session_id: str) -> SessionContext:
        return context_store.get(session_id)

    # ------------------------------------------------------------------
    # LLM access with automatic cost tracking
    # ------------------------------------------------------------------

    def call_llm(
        self,
        *,
        session_id: str,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        resp = self.router.complete(
            provider=provider or self.provider,
            model=model or self.model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_call(session_id, resp)
        return resp

    async def acall_llm(
        self,
        *,
        session_id: str,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        resp = await self.router.acomplete(
            provider=provider or self.provider,
            model=model or self.model,
            prompt=prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_call(session_id, resp)
        return resp

    def _record_call(self, session_id: str, resp: LLMResponse) -> None:
        try:
            ctx = context_store.get(session_id)
        except KeyError:
            return
        ctx.record_llm_call(
            agent=self.role,
            model=resp.model,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            latency_ms=resp.latency_ms,
        )
        self._emit(
            session_id,
            event_type="llm_call",
            detail={
                "model": resp.model,
                "provider": resp.provider.value,
                "tokens_in": resp.tokens_in,
                "tokens_out": resp.tokens_out,
                "latency_ms": round(resp.latency_ms, 1),
            },
        )

    # ------------------------------------------------------------------
    # Telemetry helpers
    # ------------------------------------------------------------------

    def _emit(self, session_id: str, *, event_type: str, detail: dict) -> None:
        event = AgentEvent(
            envelope=make_envelope(
                session_id=session_id,
                from_role=self.role,
                channel=BandConfig.CHANNEL_TELEMETRY,
                topic=BandConfig.TOPIC_CONTROL,
            ),
            event_type=event_type,  # type: ignore[arg-type]
            role=self.role,
            detail=detail,
        )
        self.telemetry.emit(event)

    def presence(self) -> Presence:
        return Presence(
            role=self.role,
            agent_id=self.agent_id,
            status="online",
            model_backend=f"{self.model} [{self.provider.value}]",
        )

    # ------------------------------------------------------------------
    # Public entry points — wrap business logic with telemetry + timing
    # ------------------------------------------------------------------

    def run(self, message: TIn) -> TOut:
        session_id = message.envelope.session_id
        self._emit(session_id, event_type="task_started", detail={"role": self.role})
        start = time.perf_counter()
        try:
            result = self._run(message)
        except Exception as exc:
            self._emit(
                session_id,
                event_type="error",
                detail={"role": self.role, "error": str(exc)},
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._emit(
            session_id,
            event_type="task_completed",
            detail={"role": self.role, "latency_ms": round(elapsed_ms, 1)},
        )
        return result

    async def arun(self, message: TIn) -> TOut:
        session_id = message.envelope.session_id
        await self.telemetry.aemit(
            AgentEvent(
                envelope=make_envelope(
                    session_id=session_id,
                    from_role=self.role,
                    channel=BandConfig.CHANNEL_TELEMETRY,
                    topic=BandConfig.TOPIC_CONTROL,
                ),
                event_type="task_started",
                role=self.role,
                detail={"role": self.role},
            )
        )
        start = time.perf_counter()
        try:
            result = await self._arun(message)
        except Exception as exc:
            self._emit(
                session_id,
                event_type="error",
                detail={"role": self.role, "error": str(exc)},
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._emit(
            session_id,
            event_type="task_completed",
            detail={"role": self.role, "latency_ms": round(elapsed_ms, 1)},
        )
        return result

    # ------------------------------------------------------------------
    # Business logic — implemented by concrete agents
    # ------------------------------------------------------------------

    @abstractmethod
    def _run(self, message: TIn) -> TOut:
        """Synchronous business logic. Concrete agents implement this."""
        ...

    async def _arun(self, message: TIn) -> TOut:
        """
        Async business logic. Default delegates to the sync path so agents
        can opt into async incrementally without breaking the interface.
        """
        return self._run(message)
