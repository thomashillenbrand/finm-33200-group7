"""Tests for the claim-type gate and user-message formatter."""

from datetime import date

import pytest

from schemas import Claim
from verifier.agent import (
    UnsupportedClaimTypeError,
    _format_claim_for_agent,
    SUPPORTED_CLAIM_TYPES,
)


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


# --- gate ------------------------------------------------------------------

def test_supported_claim_types_is_capital_allocation_only():
    assert SUPPORTED_CLAIM_TYPES == {"capital_allocation"}


def test_format_claim_for_agent_rejects_numerical_guidance():
    c = _claim(claim_type="numerical_guidance")
    with pytest.raises(UnsupportedClaimTypeError):
        _format_claim_for_agent(c)


# --- ticker hiding ---------------------------------------------------------

def test_format_claim_for_agent_omits_ticker():
    """The user message must not name the ticker — the LLM should learn it
    only via the tool binding (closed over). Naming it in prose would re-leak
    it into a place the LLM could try to override."""
    c = _claim(ticker="AMZN")
    msg = _format_claim_for_agent(c)
    assert "AMZN" not in msg


# --- horizon hint ----------------------------------------------------------

def test_format_claim_for_agent_appends_horizon_hint_when_past_date():
    """Horizon end date in the past → hint mentioning it."""
    c = _claim(horizon_end_date=date(2024, 12, 31))
    msg = _format_claim_for_agent(c, today=date(2026, 5, 22))
    assert "2024-12-31" in msg
    assert "horizon ends" in msg.lower() or "horizon end" in msg.lower()


def test_format_claim_for_agent_no_hint_when_horizon_unknown():
    c = _claim(horizon_end_date=None)
    msg = _format_claim_for_agent(c, today=date(2026, 5, 22))
    assert "horizon end" not in msg.lower()


def test_format_claim_for_agent_no_hint_when_horizon_in_future():
    c = _claim(horizon_end_date=date(2099, 1, 1))
    msg = _format_claim_for_agent(c, today=date(2026, 5, 22))
    assert "horizon ends" not in msg.lower()


# --- claim content ---------------------------------------------------------

def test_format_claim_for_agent_includes_quote_and_summary():
    c = _claim()
    msg = _format_claim_for_agent(c)
    assert c.verbatim_quote in msg
    assert c.summary in msg
