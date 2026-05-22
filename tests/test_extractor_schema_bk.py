"""Schema tests for the claim-extraction pipeline (workstream B)."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from extractor.schema import (
    CSV_FIELDS,
    Claim,
    ExtractedClaim,
    ExtractionResponse,
    make_claim_id,
)


def _valid_claim_kwargs() -> dict:
    return dict(
        claim_id="TSLA_20220420_abc12345",
        ticker="TSLA",
        company="Tesla, Inc.",
        call_date=date(2022, 4, 20),
        fiscal_period="Q1 2022",
        source_call="Tesla, Inc., Q1 2022 Earnings Call, Apr 20, 2022",
        claim_type="numerical_guidance",
        verbatim_quote="We expect to grow deliveries about 50% in 2022.",
        quote_verbatim=True,
        summary="Management expects ~50% delivery growth in 2022.",
        horizon_raw="in 2022",
        horizon_period="FY2022",
        horizon_end_date=date(2022, 12, 31),
        transcript_id=1382970,
        component_id=55282263,
        speaker_name="Elon Musk",
        speaker_type="Executives",
        extraction_model="openai:gpt-4o-mini",
        prompt_version="b-extract-v1",
        extracted_at=datetime.now(timezone.utc),
    )


def test_extracted_claim_accepts_valid_payload():
    ec = ExtractedClaim(
        claim_type="buyback",
        verbatim_quote="we plan to repurchase $1 billion of stock",
        summary="Management plans a $1B buyback.",
        horizon_raw="next year",
    )
    assert ec.claim_type == "buyback"


def test_extracted_claim_has_no_component_id():
    """The model no longer reports provenance; it is recovered by matching."""
    assert "component_id" not in ExtractedClaim.model_fields


def test_extracted_claim_rejects_empty_quote():
    with pytest.raises(ValidationError):
        ExtractedClaim(
            claim_type="capex",
            verbatim_quote="",
            summary="something",
        )


def test_extracted_claim_rejects_unknown_type():
    with pytest.raises(ValidationError):
        ExtractedClaim(
            claim_type="profit_warning",  # not one of the five types
            verbatim_quote="text",
            summary="summary",
        )


def test_extraction_response_defaults_to_empty():
    assert ExtractionResponse().claims == []


def test_claim_accepts_valid_payload():
    claim = Claim(**_valid_claim_kwargs())
    assert claim.ticker == "TSLA"
    assert claim.horizon_end_date == date(2022, 12, 31)


def test_claim_id_is_deterministic():
    args = ("TSLA", date(2022, 4, 20), 55282263, "We expect ~50% growth.")
    assert make_claim_id(*args) == make_claim_id(*args)


def test_claim_id_changes_with_content():
    base = ("TSLA", date(2022, 4, 20), 55282263, "We expect ~50% growth.")
    other = ("TSLA", date(2022, 4, 20), 55282263, "Different quote.")
    assert make_claim_id(*base) != make_claim_id(*other)


def test_csv_fields_match_claim_model():
    """CSV_FIELDS must cover exactly the Claim model's fields -- no drift."""
    assert set(CSV_FIELDS) == set(Claim.model_fields)


def test_schema_carries_no_verdict_field():
    """B surfaces claims; it must not pre-judge outcomes (see CLAUDE.md).

    Guards the load-bearing labeling workflow: no extraction-stage field may
    express a verdict or whether a claim came true.
    """
    forbidden = ("verdict", "outcome", "realized", "verified", "result", "judgment")
    for model in (ExtractedClaim, Claim):
        for field_name in model.model_fields:
            assert not any(bad in field_name.lower() for bad in forbidden), (
                f"{model.__name__}.{field_name} looks like an outcome field"
            )
