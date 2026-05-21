"""End-to-end smoke test for the claim-extraction pipeline (workstream B).

This test makes a live OpenAI API call. It skips cleanly if OPENAI_API_KEY is
not set. .env is loaded at import time so running `pytest` from a shell that
hasn't sourced .env still picks up the key.

Costs a fraction of a cent on the mini-tier model.
"""

import os
from datetime import date

import pytest
from dotenv import load_dotenv

load_dotenv()

from extractor.reader import EarningsCall, Turn
from extractor.schema import CLAIM_TYPES, Claim

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set; smoke test requires live LLM access.",
)


def _sample_call() -> EarningsCall:
    """A one-turn call with two obvious, in-scope forward-looking claims."""
    turn = Turn(
        component_id=900001,
        component_order=1,
        component_type="Answer",
        speaker_name="Jane Doe",
        speaker_type="Executives",
        text=(
            "We expect full year 2024 revenue to grow about 10%, and we plan "
            "to repurchase $1 billion of stock over the next twelve months."
        ),
    )
    return EarningsCall(
        ticker="TSLA",
        company="Tesla, Inc.",
        transcript_id=999999,
        headline="Tesla, Inc., Q1 2024 Earnings Call, Apr 23, 2024",
        call_date=date(2024, 4, 23),
        fiscal_period="Q1 2024",
        turns=[turn],
    )


@pytest.mark.live
def test_extract_call_runs_end_to_end():
    from extractor.extract import extract_call

    claims = extract_call(_sample_call())

    assert isinstance(claims, list)
    assert len(claims) >= 1
    for claim in claims:
        assert isinstance(claim, Claim)
        assert claim.claim_type in CLAIM_TYPES
        assert claim.ticker == "TSLA"
        assert claim.verbatim_quote                       # non-empty
        assert isinstance(claim.quote_verbatim, bool)
        # provenance is recovered by matching; the call has a single turn, so a
        # located claim must point at it (0 only if the quote was unmatchable).
        assert claim.component_id in (900001, 0)
