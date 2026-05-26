"""Tests for the claim-type gate and user-message formatter."""

from datetime import date

import pytest

from schemas import Claim
from verifier.agent import (
    SUPPORTED_CLAIM_TYPES,
    UnsupportedClaimTypeError,
    _format_claim_for_agent,
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


# --- horizon / no date knob ------------------------------------------------

def test_format_claim_for_agent_states_resolved_horizon_for_context():
    """The resolved horizon end is shown for context, but only as context —
    the tool enforces it, so there's no `before_date` knob to instruct."""
    c = _claim(horizon_end_date=date(2024, 12, 31))
    msg = _format_claim_for_agent(c)
    assert "2024-12-31" in msg


def test_format_claim_for_agent_gives_llm_no_date_knob():
    """The message must not instruct the LLM to set any date argument — the
    window is enforced inside the tool binding (closed-over after_date +
    horizon_end), not driven by the model."""
    c = _claim(horizon_end_date=date(2024, 12, 31))
    msg = _format_claim_for_agent(c)
    assert "before_date" not in msg


def test_format_claim_for_agent_handles_unresolved_horizon():
    c = _claim(horizon_end_date=None)
    msg = _format_claim_for_agent(c)
    assert "resolved end: unknown" in msg


# --- claim content ---------------------------------------------------------

def test_format_claim_for_agent_includes_quote_and_summary():
    c = _claim()
    msg = _format_claim_for_agent(c)
    assert c.verbatim_quote in msg
    assert c.summary in msg


def test_format_claim_includes_open_coverage_warning():
    c = _claim(horizon_end_date=date(2026, 12, 31))
    msg = _format_claim_for_agent(c, coverage_date=date(2024, 12, 31), fully_covered=False)
    assert "2024-12-31" in msg                      # coverage ceiling stated
    assert "do not assume" in msg.lower()           # don't infer unpublished filings
    assert "beyond" in msg.lower()


def test_format_claim_includes_covered_note_when_within_coverage():
    c = _claim(horizon_end_date=date(2024, 12, 31))
    msg = _format_claim_for_agent(c, coverage_date=date(2025, 2, 20), fully_covered=True)
    assert "within" in msg.lower()


def test_format_claim_omits_coverage_line_when_not_provided():
    c = _claim()
    msg = _format_claim_for_agent(c)               # no coverage args -> backwards compatible
    assert "available through" not in msg.lower()


def test_format_claim_allow_unsupported_bypasses_gate():
    c = _claim(claim_type="numerical_guidance")
    msg = _format_claim_for_agent(c, allow_unsupported=True)   # must NOT raise
    assert "numerical_guidance" in msg
