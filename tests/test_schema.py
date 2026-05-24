"""Legacy iter-1 schema tests, updated for the iter-2 Claim shape.

This file uses `verifier.schema` (the shim) on purpose, to keep one explicit
exerciser of the legacy import path until the shim is removed. Tests for the
canonical `schemas` import path live in `tests/test_schemas_package.py`.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from verifier.agent import _output_schema
from verifier.schema import Claim, EvidenceBundle, EvidenceItem, Verdict


def _claim_kwargs(**overrides):
    base = {
        "claim_id": "TSLA_20240124_test",
        "ticker": "TSLA",
        "call_date": "2024-01-24",
        "company": "Tesla, Inc.",
        "fiscal_period": "Q4 2023",
        "source_call": "Tesla Q4 2023 Earnings Call",
        "claim_type": "capital_allocation",
        "verbatim_quote": "We expect capex above $10B in 2024.",
        "summary": "Management expects 2024 capex above $10B.",
        "transcript_id": 1382970,
        "component_id": 55282263,
    }
    base.update(overrides)
    return base


def test_claim_constructs_from_iso_date_string():
    c = Claim(**_claim_kwargs())
    assert c.ticker == "TSLA"
    assert c.call_date == date(2024, 1, 24)


def test_claim_rejects_empty_ticker():
    with pytest.raises(ValidationError):
        Claim(**_claim_kwargs(ticker=""))


def test_claim_rejects_unparseable_date():
    with pytest.raises(ValidationError):
        Claim(**_claim_kwargs(call_date="not-a-date"))


def test_evidence_item_requires_source_and_excerpt():
    e = EvidenceItem(
        source="TSLA 10-Q filed 2024-04-23",
        excerpt="...",
        accession_no="0001318605-24-000050",
        form="10-Q",
        filing_date="2024-04-23",
        chunk_id="abc123",
        score=0.7,
    )
    assert e.source == "TSLA 10-Q filed 2024-04-23"
    assert e.excerpt == "..."


def test_evidence_bundle_has_no_verdict_field():
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


def test_output_schema_mode_mapping():
    """Lock down which schema each mode produces — load-bearing labeling guarantee."""
    assert _output_schema("evidence") is EvidenceBundle
    assert _output_schema("verdict") is Verdict
