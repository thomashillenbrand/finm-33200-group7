"""Deduplication tests for the claim-extraction pipeline (workstream B)."""

from datetime import date

from extractor.extract import dedupe_claims
from extractor.schema import Claim


def _claim(claim_id: str, summary: str = "A claim.") -> Claim:
    """A minimal valid Claim with a caller-chosen id."""
    return Claim(
        claim_id=claim_id,
        ticker="TSLA",
        company="Tesla, Inc.",
        call_date=date(2018, 8, 1),
        fiscal_period="Q2 2018",
        source_call="Tesla, Inc., Q2 2018 Earnings Call, Aug 01, 2018",
        claim_type="numerical_guidance",
        verbatim_quote="we expect to be profitable",
        quote_verbatim=True,
        summary=summary,
        transcript_id=1,
        component_id=100,
    )


def test_dedupe_drops_duplicate_claim_ids():
    result = dedupe_claims([_claim("A"), _claim("B"), _claim("A")])
    assert [c.claim_id for c in result] == ["A", "B"]


def test_dedupe_keeps_first_occurrence():
    result = dedupe_claims([_claim("A", summary="first"), _claim("A", summary="second")])
    assert len(result) == 1
    assert result[0].summary == "first"


def test_dedupe_preserves_order_of_uniques():
    result = dedupe_claims([_claim("X"), _claim("Y"), _claim("Z")])
    assert [c.claim_id for c in result] == ["X", "Y", "Z"]


def test_dedupe_empty_list():
    assert dedupe_claims([]) == []
