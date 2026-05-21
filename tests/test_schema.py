from datetime import date

import pytest
from pydantic import ValidationError

from verifier.schema import Claim, EvidenceItem, EvidenceBundle, Verdict
from verifier.agent import _output_schema


def test_claim_constructs_from_iso_date_string():
    c = Claim(ticker="TSLA", call_date="2024-01-24", text="growth 50%")
    assert c.ticker == "TSLA"
    assert c.call_date == date(2024, 1, 24)
    assert c.text == "growth 50%"


def test_claim_rejects_empty_ticker():
    with pytest.raises(ValidationError):
        Claim(ticker="", call_date="2024-01-24", text="x")


def test_claim_rejects_unparseable_date():
    with pytest.raises(ValidationError):
        Claim(ticker="TSLA", call_date="not-a-date", text="x")


def test_evidence_item_requires_source_and_excerpt():
    e = EvidenceItem(source="TSLA 10-Q 2024-04-23", excerpt="...")
    assert e.source == "TSLA 10-Q 2024-04-23"
    assert e.excerpt == "..."


def test_evidence_bundle_has_no_verdict_field():
    # Critical: evidence mode must NOT carry a verdict, by construction.
    # We assert against the schema (model_fields), not just an instance —
    # the labeling workflow depends on this field being structurally absent.
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
    """Lock down which schema each mode produces — the load-bearing labeling guarantee.

    If a refactor ever flipped these or made evidence mode return Verdict, the
    labeling workflow would silently start biasing labelers.
    """
    assert _output_schema("evidence") is EvidenceBundle
    assert _output_schema("verdict") is Verdict
