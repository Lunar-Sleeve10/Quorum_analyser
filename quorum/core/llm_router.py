"""
core/llm_router.py — LLM routing abstraction.

Explicit provider selection (no inference from model-name substrings). One LLMRouter
instance handles Ollama (local), Groq, AI/ML API, Featherless, and OpenAI.

Both sync and async call paths are provided. Token usage is returned with
every call so SessionContext can track cost. litellm is the underlying
transport; the router only decides provider/api_base/api_key.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import litellm

from config import LLMProvider, settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LLMResponse:
    """Structured result of an LLM call, including usage for cost tracking."""
    content: str
    model: str
    provider: LLMProvider
    tokens_in: int
    tokens_out: int
    latency_ms: float


@dataclass(slots=True)
class LLMError(Exception):
    """Raised when an LLM call fails after exhausting retries."""
    message: str
    model: str
    provider: LLMProvider

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"LLMError[{self.provider.value}/{self.model}]: {self.message}"


class LLMRouter:
    """
    Routes completion requests to the correct provider.

    Provider is passed explicitly per call; no inference from model name.
    Retries on rate-limit with backoff parsed from the provider error.
    """

    def __init__(
        self,
        *,
        ollama_base_url: Optional[str] = None,
        default_temperature: Optional[float] = None,
        default_max_tokens: Optional[int] = None,
        max_retries: int = 2,
    ) -> None:
        self.ollama_base_url = ollama_base_url or settings.ollama_base_url
        self.default_temperature = (
            default_temperature
            if default_temperature is not None
            else settings.llm_temperature
        )
        self.default_max_tokens = default_max_tokens or settings.llm_max_tokens
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Provider-specific kwargs assembly
    # ------------------------------------------------------------------

    def _build_kwargs(
        self,
        *,
        provider: LLMProvider,
        model: str,
        prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        messages = [{"role": "user", "content": prompt}]
        base: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if provider == LLMProvider.OLLAMA:
            base["custom_llm_provider"] = "ollama"
            base["api_base"] = self.ollama_base_url
        elif provider in (LLMProvider.AIML, LLMProvider.FEATHERLESS):
            # AI/ML API and Featherless are OpenAI-compatible: route through the
            # openai transport with a custom base_url + key. A redundant
            # "openai/" prefix on the model id is stripped for the endpoint.
            base["custom_llm_provider"] = "openai"
            base["api_base"] = settings.base_url_for(provider)
            base["api_key"] = settings.api_key_for(provider)
            if base["model"].startswith("openai/"):
                base["model"] = base["model"].split("/", 1)[1]
        else:
            api_key = settings.api_key_for(provider)
            if api_key:
                base["api_key"] = api_key
        return base

    # ------------------------------------------------------------------
    # Usage extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_usage(response: object) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0
        return int(tokens_in), int(tokens_out)

    @staticmethod
    def _extract_content(response: object) -> str:
        try:
            return response.choices[0].message.content or ""  # type: ignore[attr-defined]
        except (AttributeError, IndexError, KeyError):
            return ""

    @staticmethod
    def _parse_retry_wait(error_text: str) -> float:
        import re

        match = re.search(r"try again in ([\d.]+)\s*(ms|s)", error_text)
        if not match:
            return 6.0
        value = float(match.group(1))
        unit = match.group(2)
        seconds = value / 1000.0 if unit == "ms" else value
        return seconds + 1.0

    # ------------------------------------------------------------------
    # Sync call
    # ------------------------------------------------------------------

    def complete(
        self,
        *,
        provider: LLMProvider,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        temp = temperature if temperature is not None else self.default_temperature
        max_tok = max_tokens or self.default_max_tokens
        kwargs = self._build_kwargs(
            provider=provider,
            model=model,
            prompt=prompt,
            temperature=temp,
            max_tokens=max_tok,
        )

        last_error = ""
        for attempt in range(self.max_retries):
            start = time.perf_counter()
            try:
                logger.info(
                    "LLM call provider=%s model=%s attempt=%d",
                    provider.value, model, attempt + 1,
                )
                response = litellm.completion(**kwargs)
                latency_ms = (time.perf_counter() - start) * 1000.0
                tokens_in, tokens_out = self._extract_usage(response)
                return LLMResponse(
                    content=self._extract_content(response),
                    model=model,
                    provider=provider,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                last_error = str(exc)
                if "rate_limit" in last_error.lower() and attempt < self.max_retries - 1:
                    wait = self._parse_retry_wait(last_error)
                    logger.warning("Rate limit hit, waiting %.1fs", wait)
                    time.sleep(wait)
                    continue
                if attempt < self.max_retries - 1:
                    logger.warning("LLM error: %s; retrying", last_error)
                    time.sleep(6.0)
                    continue
                break

        raise LLMError(message=last_error, model=model, provider=provider)

    # ------------------------------------------------------------------
    # Async call (runs sync litellm in a thread to stay non-blocking)
    # ------------------------------------------------------------------

    async def acomplete(
        self,
        *,
        provider: LLMProvider,
        model: str,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        temp = temperature if temperature is not None else self.default_temperature
        max_tok = max_tokens or self.default_max_tokens
        kwargs = self._build_kwargs(
            provider=provider,
            model=model,
            prompt=prompt,
            temperature=temp,
            max_tokens=max_tok,
        )

        last_error = ""
        for attempt in range(self.max_retries):
            start = time.perf_counter()
            try:
                logger.info(
                    "Async LLM call provider=%s model=%s attempt=%d",
                    provider.value, model, attempt + 1,
                )
                response = await litellm.acompletion(**kwargs)
                latency_ms = (time.perf_counter() - start) * 1000.0
                tokens_in, tokens_out = self._extract_usage(response)
                return LLMResponse(
                    content=self._extract_content(response),
                    model=model,
                    provider=provider,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                last_error = str(exc)
                if "rate_limit" in last_error.lower() and attempt < self.max_retries - 1:
                    wait = self._parse_retry_wait(last_error)
                    logger.warning("Rate limit hit, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                if attempt < self.max_retries - 1:
                    logger.warning("Async LLM error: %s; retrying", last_error)
                    await asyncio.sleep(6.0)
                    continue
                break

        raise LLMError(message=last_error, model=model, provider=provider)


# Module-level singleton
router = LLMRouter()
