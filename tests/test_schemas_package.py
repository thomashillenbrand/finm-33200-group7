"""Tests for the src/schemas/ package: per-file definitions + re-exports."""

from datetime import date

import pytest
from pydantic import ValidationError

import schemas
from schemas import Claim, EvidenceBundle, EvidenceItem, Verdict
from schemas.claim import Claim as ClaimDirect
from schemas.evidence_bundle import EvidenceBundle as EvidenceBundleDirect
from schemas.evidence_item import EvidenceItem as EvidenceItemDirect
from schemas.verdict import Verdict as VerdictDirect

# --- Re-export integrity ---------------------------------------------------

def test_reexports_are_same_object():
    """`from schemas import X` must be the same class object as the per-file def."""
    assert Claim is ClaimDirect
    assert EvidenceItem is EvidenceItemDirect
    assert EvidenceBundle is EvidenceBundleDirect
    assert Verdict is VerdictDirect


def test_package_all_lists_public_surface():
    assert set(schemas.__all__) >= {
        "Claim", "ClaimType", "EvidenceItem", "EvidenceBundle", "Verdict"
    }


# --- Claim shape -----------------------------------------------------------

def _sample_claim_kwargs(**overrides):
    base = {
        "claim_id": "AMZN_20240201_abc12345",
        "ticker": "AMZN",
        "call_date": "2024-02-01",
        "company": "Amazon.com, Inc.",
        "fiscal_period": "Q4 2023",
        "source_call": "Amazon Q4 2023 Earnings Call",
        "claim_type": "capital_allocation",
        "verbatim_quote": "We expect to repurchase approximately $5 billion in 2024.",
        "summary": "Management plans ~$5B buyback in 2024.",
        "transcript_id": 1234567,
        "component_id": 89012345,
    }
    base.update(overrides)
    return base


def test_claim_constructs_with_required_fields():
    c = Claim(**_sample_claim_kwargs())
    assert c.ticker == "AMZN"
    assert c.call_date == date(2024, 2, 1)
    assert c.claim_type == "capital_allocation"


def test_claim_rejects_unknown_claim_type():
    with pytest.raises(ValidationError):
        Claim(**_sample_claim_kwargs(claim_type="something_else"))


def test_claim_rejects_retired_subtype():
    """buyback/dividend/capex/debt collapsed into capital_allocation in v4."""
    with pytest.raises(ValidationError):
        Claim(**_sample_claim_kwargs(claim_type="buyback"))


def test_claim_resolves_horizon_end_date_from_iso():
    c = Claim(**_sample_claim_kwargs(horizon_end_date="2024-12-31"))
    assert c.horizon_end_date == date(2024, 12, 31)


# --- EvidenceItem shape ----------------------------------------------------

def _sample_evidence_kwargs(**overrides):
    base = {
        "source": "10-Q filed 2024-04-30, accession 0001018724-24-000010",
        "excerpt": "During the three months ended March 31, 2024, the Company repurchased ...",
        "accession_no": "0001018724-24-000010",
        "form": "10-Q",
        "filing_date": "2024-04-30",
        "chunk_id": "abc123def456",
        "score": 0.81,
    }
    base.update(overrides)
    return base


def test_evidence_item_has_citation_fields():
    """Iter-2 schema change: citation metadata must be present and required."""
    fields = EvidenceItem.model_fields
    for required in ("accession_no", "form", "filing_date", "chunk_id", "score"):
        assert required in fields, f"EvidenceItem missing field: {required}"


def test_evidence_item_constructs():
    e = EvidenceItem(**_sample_evidence_kwargs())
    assert e.form == "10-Q"
    assert e.score == 0.81
    assert e.edgar_url is None


def test_evidence_item_rejects_unknown_form():
    with pytest.raises(ValidationError):
        EvidenceItem(**_sample_evidence_kwargs(form="DEF 14A"))


def test_evidence_item_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        EvidenceItem(**_sample_evidence_kwargs(score=1.7))


# --- EvidenceBundle / Verdict invariants -----------------------------------

def test_evidence_bundle_has_no_verdict_field():
    """Load-bearing labeling guarantee — kept from iter 1."""
    assert "items" in EvidenceBundle.model_fields
    assert "verdict" not in EvidenceBundle.model_fields
    assert "reasoning" not in EvidenceBundle.model_fields


def test_verdict_accepts_known_labels():
    for label in ("verified", "partially_verified", "contradicted", "not_yet_resolvable"):
        v = Verdict(items=[], verdict=label, reasoning="r")
        assert v.verdict == label


def test_verdict_rejects_unknown_label():
    with pytest.raises(ValidationError):
        Verdict(items=[], verdict="maybe", reasoning="r")
