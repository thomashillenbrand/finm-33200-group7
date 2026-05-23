"""Tests for the figure-required scope filter (workstream B).

Per the workstream-B scope decision, numerical-guidance claims must state a
specific figure; capital-allocation claims are kept regardless of whether an
amount is given.
"""

from datetime import date

from extractor.extract import filter_unquantified_guidance
from schemas import Claim


def _claim(claim_type: str, quote: str) -> Claim:
    """A minimal valid Claim with a caller-chosen type and verbatim quote."""
    return Claim(
        claim_id="x",
        ticker="TSLA",
        company="Tesla, Inc.",
        call_date=date(2024, 1, 24),
        fiscal_period="Q4 2023",
        source_call="Tesla, Inc., Q4 2023 Earnings Call, Jan 24, 2024",
        claim_type=claim_type,
        verbatim_quote=quote,
        summary="A claim.",
        transcript_id=1,
        component_id=100,
    )


def test_keeps_numerical_guidance_with_a_dollar_figure():
    claims = [_claim("numerical_guidance", "We expect Q4 revenue of $24 billion.")]
    assert len(filter_unquantified_guidance(claims)) == 1


def test_keeps_numerical_guidance_with_a_percentage():
    claims = [_claim("numerical_guidance", "We expect revenue to grow about 8%.")]
    assert len(filter_unquantified_guidance(claims)) == 1


def test_drops_directional_numerical_guidance_with_no_figure():
    claims = [_claim("numerical_guidance", "We expect revenue to keep growing.")]
    assert filter_unquantified_guidance(claims) == []


def test_drops_numerical_guidance_whose_only_digits_are_a_year():
    claims = [_claim("numerical_guidance", "Full year 2024 should be a strong year.")]
    assert filter_unquantified_guidance(claims) == []


def test_drops_guidance_whose_only_digit_is_a_model_number():
    """Regression for the pilot bug: a directional margin claim survived only
    because it mentioned 'Model 3' -- a model number is not a figure."""
    claims = [_claim(
        "numerical_guidance",
        "we're forecasting higher gross margins on Model Y compared to the Model 3",
    )]
    assert filter_unquantified_guidance(claims) == []


def test_drops_guidance_whose_only_digit_is_a_quarter_label():
    """A quarter tag like 'Q4' is a label, not a financial figure."""
    claims = [_claim("numerical_guidance", "We expect Q4 to be a strong quarter.")]
    assert filter_unquantified_guidance(claims) == []


def test_drops_guidance_whose_only_digit_is_an_sec_form_name():
    """Regression for a v4 pilot bug: a procedural non-claim survived only
    because it mentioned 'the 10-K' -- a form name is not a figure."""
    claims = [_claim(
        "numerical_guidance",
        "we will have additional detail on CapEx in the 10-K",
    )]
    assert filter_unquantified_guidance(claims) == []


def test_keeps_capital_allocation_claims_without_a_figure():
    """An announced capital-allocation action is verifiable against a later
    filing even with no amount stated, so these are never dropped."""
    claims = [
        _claim("capital_allocation", "We plan to repurchase shares."),
        _claim("capital_allocation", "The board intends to raise the dividend."),
        _claim("capital_allocation", "We plan to pay down debt."),
    ]
    assert len(filter_unquantified_guidance(claims)) == 3


def test_mixed_batch_keeps_quantified_guidance_and_all_capital_allocation():
    claims = [
        _claim("numerical_guidance", "Revenue will be $24 billion."),   # keep
        _claim("numerical_guidance", "Revenue will grow."),             # drop
        _claim("capital_allocation", "We will buy back stock."),        # keep
    ]
    kept = filter_unquantified_guidance(claims)
    assert [c.claim_type for c in kept] == ["numerical_guidance", "capital_allocation"]
    assert kept[0].verbatim_quote == "Revenue will be $24 billion."
