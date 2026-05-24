"""Tests for the per-claim rate-limit retry wrapping verifier.agent.verify."""

from datetime import date
from types import SimpleNamespace

import httpx
import openai
import pytest

from schemas import Claim, EvidenceBundle
from verifier import agent as agent_mod


def _claim(**overrides):
    base = {
        "claim_id": "X_20240201_a",
        "ticker": "AMZN",
        "call_date": date(2024, 2, 1),
        "company": "Amazon.com, Inc.",
        "fiscal_period": "Q4 2023",
        "source_call": "Amazon Q4 2023 Earnings Call",
        "claim_type": "capital_allocation",
        "verbatim_quote": "We expect ~$5B in buybacks in 2024.",
        "summary": "Management expects ~$5B buyback in 2024.",
        "horizon_raw": "in 2024",
        "horizon_period": "FY2024",
        "horizon_end_date": date(2024, 12, 31),
        "speaker_name": "Brian Olsavsky",
        "speaker_type": "Executives",
        "transcript_id": 1234567,
        "component_id": 89012345,
    }
    base.update(overrides)
    return Claim(**base)


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError("rate limited", response=response, body=None)


@pytest.fixture
def stub_agent_stack(monkeypatch):
    """Stub verify()'s heavy seams and neutralize backoff sleeps.

    Returns a counter dict; the caller installs a fake agent via `set_invoke`.
    """
    # No real backoff in tests — the wait policy is exercised in production only.
    monkeypatch.setattr(agent_mod.verify.retry, "sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(agent_mod, "_configure_cache", lambda enabled: None)
    monkeypatch.setattr(agent_mod, "bind_search_filings", lambda ticker, after: object())
    sentinel = EvidenceBundle(items=[])
    monkeypatch.setattr(agent_mod, "_extract_structured", lambda text, mode: sentinel)

    state = {"calls": 0, "sentinel": sentinel}

    def set_invoke(invoke_fn):
        monkeypatch.setattr(
            agent_mod, "build_agent",
            lambda mode, tools: SimpleNamespace(invoke=invoke_fn),
        )

    state["set_invoke"] = set_invoke
    return state


def test_verify_retries_then_succeeds_on_rate_limit(stub_agent_stack):
    """Two RateLimitErrors then a success → verify returns the parsed result."""
    state = stub_agent_stack

    def invoke(_payload):
        state["calls"] += 1
        if state["calls"] < 3:
            raise _rate_limit_error()
        return {"messages": [SimpleNamespace(content="final agent answer")]}

    state["set_invoke"](invoke)

    out = agent_mod.verify(_claim(), mode="evidence", trace=False, cache=False)
    assert out is state["sentinel"]
    assert state["calls"] == 3  # 2 failures + 1 success


def test_verify_reraises_rate_limit_after_exhausting_attempts(stub_agent_stack):
    """Persistent rate limits → the original RateLimitError surfaces (not RetryError)."""
    state = stub_agent_stack

    def invoke(_payload):
        state["calls"] += 1
        raise _rate_limit_error()

    state["set_invoke"](invoke)

    with pytest.raises(openai.RateLimitError):
        agent_mod.verify(_claim(), mode="evidence", trace=False, cache=False)
    assert state["calls"] == 6  # stop_after_attempt(6)


def test_verify_does_not_retry_non_rate_limit_errors(stub_agent_stack):
    """A non-RateLimitError must propagate immediately, with no retry."""
    state = stub_agent_stack

    def invoke(_payload):
        state["calls"] += 1
        raise ValueError("boom")

    state["set_invoke"](invoke)

    with pytest.raises(ValueError):
        agent_mod.verify(_claim(), mode="evidence", trace=False, cache=False)
    assert state["calls"] == 1  # no retry on non-rate-limit errors
