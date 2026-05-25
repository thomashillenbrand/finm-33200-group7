"""Chat-model wiring for the autochecker (raw OpenAI SDK + Pydantic).

Reuses ``VERIFIER_AGENT_MODEL`` (the user's choice — autochecker piggybacks on
the verifier stage rather than introducing a new env var). The model id may
optionally carry an ``openai:`` prefix to match the project's per-stage
convention; we strip it before calling the SDK. Structured output is enforced
via ``client.chat.completions.parse`` with the Pydantic model passed as
``response_format``; the SDK returns a fully-validated instance.

Why raw SDK instead of LangChain (which the extractor / verifier use)?
Autochecker has no agent loop, no tool-calling, no SQLite-backed completion
cache to integrate with. The two structured calls per claim are simple
enough that the SDK directly is the smaller surface area.
"""

from __future__ import annotations

import functools
import logging
import os
import random
import time
from typing import Callable, Type, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel

_logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
F = TypeVar("F", bound=Callable)

# Models that reject a custom temperature and must run at the default.
_NO_TEMPERATURE_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def retry_on_rate_limit(fn: F) -> F:
    """Coarse retry around ``openai.RateLimitError`` with exponential backoff.

    The SDK retries individual HTTP attempts; this wraps the whole structured
    call so a persistent 429 across SDK retries still recovers. 6 attempts,
    waits 2s, 4s, 8s, 16s, 32s (capped at 60s) with ±50% jitter.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        attempts = 6
        for i in range(attempts):
            try:
                return fn(*args, **kwargs)
            except openai.RateLimitError:
                if i == attempts - 1:
                    raise
                wait = min(60.0, 2.0 * (2 ** i)) * (0.5 + random.random())
                _logger.warning(
                    "RateLimitError; retrying %s in %.1fs (attempt %d/%d)",
                    fn.__name__, wait, i + 1, attempts,
                )
                time.sleep(wait)
    return wrapper  # type: ignore[return-value]


def resolve_model() -> str:
    """Return the raw OpenAI model id from ``VERIFIER_AGENT_MODEL``.

    Strips an optional ``openai:`` provider prefix so the same env value works
    here and in the LangChain-based stages of the project.
    """
    raw = os.environ.get("VERIFIER_AGENT_MODEL")
    if not raw:
        raise RuntimeError(
            "VERIFIER_AGENT_MODEL is not set. Copy .env.example to .env or "
            "export VERIFIER_AGENT_MODEL before running."
        )
    return raw.split(":", 1)[-1] if raw.startswith("openai:") else raw


def _supports_temperature(model_name: str) -> bool:
    return not model_name.lower().startswith(_NO_TEMPERATURE_PREFIXES)


class StructuredCaller:
    """Thin wrapper around ``client.chat.completions.parse`` for one schema.

    Mirrors the LangChain ``.with_structured_output(Schema).invoke(messages)``
    surface the other stages use, so screen.py / verify.py read the same way.
    """

    def __init__(self, schema: Type[T], *, model_name: str | None = None):
        self.schema = schema
        self.model = model_name or resolve_model()
        self.client = OpenAI()  # api key from OPENAI_API_KEY in .env

    def invoke(self, messages: list[dict]) -> T:
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "response_format": self.schema,
        }
        if _supports_temperature(self.model):
            kwargs["temperature"] = 0
        completion = self.client.beta.chat.completions.parse(**kwargs)
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            # The model refused (e.g. safety) — surface a clear error rather
            # than crashing on a None down the line.
            refusal = completion.choices[0].message.refusal
            raise RuntimeError(f"OpenAI returned no parsed output. Refusal: {refusal!r}")
        return parsed


def build_structured_llm(schema: Type[T], *, model_name: str | None = None) -> StructuredCaller:
    """Build a structured-output caller for ``schema``."""
    return StructuredCaller(schema, model_name=model_name)
