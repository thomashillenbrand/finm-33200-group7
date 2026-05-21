from datetime import date

import pytest
from pydantic import ValidationError

from extractor.schema import (
    CapitalAllocationClaim,
    ExtractionResult,
    NumericalGuidanceClaim,
)
from verifier.schema import Claim as VerifierClaim


def test_numerical_guidance_claim_constructs():
    c = NumericalGuidanceClaim(
        source_span="We expect Q4 revenue of $24 billion.",
        category="revenue",
        metric="quarterly revenue",
        value_or_amount="$24B",
        horizon="next_quarter",
        confidence_language="likely",
    )
    assert c.category == "revenue"
    assert c.metric == "quarterly revenue"
    assert c.type == "numerical"


def test_capital_allocation_claim_constructs():
    c = CapitalAllocationClaim(
        source_span="The board authorized a $10 billion share repurchase.",
        subcategory="buyback",
        value_or_amount="$10B",
        horizon="next_year",
        confidence_language="certain",
    )
    assert c.category == "capital_allocation"
    assert c.subcategory == "buyback"
    assert c.type == "capital_allocation"


def test_claim_id_auto_generated_and_unique():
    c1 = NumericalGuidanceClaim(
        source_span="EPS will be $3.90.",
        category="eps",
        metric="EPS",
        horizon="next_year",
        confidence_language="certain",
    )
    c2 = NumericalGuidanceClaim(
        source_span="EPS will be $4.00.",
        category="eps",
        metric="EPS",
        horizon="next_year",
        confidence_language="certain",
    )
    assert c1.claim_id
    assert c1.claim_id != c2.claim_id


def test_to_verifier_claim_numerical():
    c = NumericalGuidanceClaim(
        source_span="We plan to grow revenue 20% next year.",
        category="revenue_growth",
        metric="revenue growth",
        horizon="next_year",
        confidence_language="likely",
    )
    vc = c.to_verifier_claim(ticker="TSLA", call_date=date(2024, 1, 24))
    assert isinstance(vc, VerifierClaim)
    assert vc.ticker == "TSLA"
    assert vc.call_date == date(2024, 1, 24)
    assert vc.text == c.source_span


def test_to_verifier_claim_capital_allocation():
    c = CapitalAllocationClaim(
        source_span="We will pay a $1.20 per share dividend.",
        subcategory="dividend",
        value_or_amount="$1.20",
        horizon="next_quarter",
        confidence_language="certain",
    )
    vc = c.to_verifier_claim(ticker="KO", call_date=date(2023, 7, 26))
    assert isinstance(vc, VerifierClaim)
    assert vc.ticker == "KO"
    assert vc.text == c.source_span


def test_numerical_rejects_invalid_category():
    with pytest.raises(ValidationError):
        NumericalGuidanceClaim(
            source_span="Revenue will be $5B.",
            category="product_launch",
            metric="revenue",
            horizon="next_quarter",
            confidence_language="likely",
        )


def test_numerical_rejects_invalid_horizon():
    with pytest.raises(ValidationError):
        NumericalGuidanceClaim(
            source_span="Revenue will be $5B.",
            category="revenue",
            metric="revenue",
            horizon="soon",
            confidence_language="likely",
        )


def test_extraction_result_holds_mixed_claims():
    n = NumericalGuidanceClaim(
        source_span="Full-year EPS guidance raised to $4.00.",
        category="eps",
        metric="full-year EPS",
        horizon="next_year",
        confidence_language="certain",
    )
    k = CapitalAllocationClaim(
        source_span="We authorized a $5 billion buyback.",
        subcategory="buyback",
        value_or_amount="$5B",
        horizon="next_year",
        confidence_language="certain",
    )
    result = ExtractionResult(
        ticker="TSLA",
        transcript_id=12345,
        call_date=date(2024, 1, 24),
        claims=[n, k],
    )
    assert len(result.claims) == 2
    assert result.claims[0].type == "numerical"
    assert result.claims[1].type == "capital_allocation"
