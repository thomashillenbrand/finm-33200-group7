"""Output-writer tests for the claim-extraction pipeline (workstream B)."""

import csv
from datetime import date, datetime, timezone

from extractor.output import write_claims_csv
from schemas import CSV_FIELDS, Claim


def _claim(**overrides) -> Claim:
    kwargs = dict(
        claim_id="TSLA_20240124_abc12345",
        ticker="TSLA",
        company="Tesla, Inc.",
        call_date=date(2024, 1, 24),
        fiscal_period="Q4 2023",
        source_call="Tesla, Inc., Q4 2023 Earnings Call, Jan 24, 2024",
        claim_type="numerical_guidance",
        verbatim_quote="We expect 2024 revenue of about $100 billion.",
        quote_verbatim=True,
        summary="Management expects ~$100B of 2024 revenue.",
        horizon_raw="2024",
        horizon_period="FY2024",
        horizon_end_date=date(2024, 12, 31),
        transcript_id=999,
        component_id=42,
        speaker_name="Elon Musk",
        speaker_type="Executives",
        extraction_model="openai:gpt-4o-mini",
        prompt_version="b-extract-v3",
        extracted_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    kwargs.update(overrides)
    return Claim(**kwargs)


def test_write_claims_csv_creates_file_and_returns_path(tmp_path):
    out = tmp_path / "claims" / "out.csv"   # parent dir does not exist yet
    result = write_claims_csv([_claim()], out)
    assert result == out
    assert out.exists()


def test_write_claims_csv_header_matches_schema(tmp_path):
    out = tmp_path / "out.csv"
    write_claims_csv([_claim()], out)
    with out.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh))
    assert header == list(CSV_FIELDS)


def test_write_claims_csv_round_trips_rows(tmp_path):
    out = tmp_path / "out.csv"
    write_claims_csv([_claim(claim_id="A"), _claim(claim_id="B")], out)
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["claim_id"] for r in rows] == ["A", "B"]
    assert rows[0]["ticker"] == "TSLA"
    assert rows[0]["claim_type"] == "numerical_guidance"
    assert rows[0]["call_date"] == "2024-01-24"      # date rendered ISO


def test_write_claims_csv_empty_list_writes_header_only(tmp_path):
    out = tmp_path / "out.csv"
    write_claims_csv([], out)
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 1
    assert rows[0] == list(CSV_FIELDS)
