"""Tests for the gold-set labeling schema + JSONL loader (verifier.gold)."""

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from verifier.gold import GoldEvidence, GoldLabel, load_gold_labels


def _evidence(**overrides) -> GoldEvidence:
    base = {
        "accession_no": "0001564590-20-019931",
        "form": "10-Q",
        "filing_date": "2020-04-30",
        "quote": "Capital expenditures were $455 million.",
        "section": "Cash flow statement",
    }
    base.update(overrides)
    return GoldEvidence(**base)


def _label_kwargs(**overrides) -> dict:
    base = {
        "claim_id": "TSLA_20200129_87696b9b",
        "ticker": "TSLA",
        "labeler": "tom",
        "labeled_at": "2026-05-23T12:00:00",
        "expected_evidence": [_evidence()],
        "verdict": "partially_verified",
        "confidence": "high",
        "labeler_notes": "Tracking below guidance through one quarter.",
    }
    base.update(overrides)
    return base


# --- round-trip ------------------------------------------------------------

def test_gold_label_round_trips_through_json():
    label = GoldLabel(**_label_kwargs())
    reloaded = GoldLabel.model_validate_json(label.model_dump_json())
    assert reloaded.claim_id == "TSLA_20200129_87696b9b"
    assert reloaded.labeled_at == datetime(2026, 5, 23, 12, 0, 0)
    assert reloaded.verdict == "partially_verified"
    assert len(reloaded.expected_evidence) == 1
    assert reloaded.expected_evidence[0].filing_date == date(2020, 4, 30)


# --- evidence-required invariant -------------------------------------------

@pytest.mark.parametrize("verdict", ["verified", "partially_verified", "contradicted"])
def test_decisive_verdict_requires_evidence(verdict):
    with pytest.raises(ValidationError):
        GoldLabel(**_label_kwargs(verdict=verdict, expected_evidence=[]))


def test_not_yet_resolvable_allows_empty_evidence():
    label = GoldLabel(**_label_kwargs(verdict="not_yet_resolvable", expected_evidence=[]))
    assert label.verdict == "not_yet_resolvable"
    assert label.expected_evidence == []


# --- enum rejection --------------------------------------------------------

def test_unknown_verdict_rejected():
    with pytest.raises(ValidationError):
        GoldLabel(**_label_kwargs(verdict="maybe"))


def test_unknown_confidence_rejected():
    with pytest.raises(ValidationError):
        GoldLabel(**_label_kwargs(confidence="certain"))


def test_unknown_form_rejected():
    with pytest.raises(ValidationError):
        _evidence(form="DEF 14A")


def test_quote_length_capped():
    with pytest.raises(ValidationError):
        _evidence(quote="x" * 501)


# --- loader ----------------------------------------------------------------

def test_load_gold_labels_parses_multiple_rows(tmp_path):
    p = tmp_path / "gold.jsonl"
    rows = [
        GoldLabel(**_label_kwargs(claim_id="c1")).model_dump_json(),
        "",  # blank line should be skipped
        GoldLabel(**_label_kwargs(claim_id="c2", verdict="not_yet_resolvable",
                                  expected_evidence=[])).model_dump_json(),
    ]
    p.write_text("\n".join(rows) + "\n", encoding="utf-8")
    labels = load_gold_labels(p)
    assert [l.claim_id for l in labels] == ["c1", "c2"]


def test_load_gold_labels_reports_row_number_on_bad_row(tmp_path):
    p = tmp_path / "gold.jsonl"
    good = GoldLabel(**_label_kwargs(claim_id="c1")).model_dump_json()
    bad = '{"claim_id": "c2", "verdict": "verified"}'  # missing required fields
    p.write_text(good + "\n" + bad + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row 2"):
        load_gold_labels(p)
