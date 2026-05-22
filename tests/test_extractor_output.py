import csv
import json
from pathlib import Path

import pytest

from extractor.output import write_csv, write_json


@pytest.fixture()
def sample_enriched() -> dict:
    return {
        "ticker": "AMZN",
        "transcript_id": 3368103,
        "call_date": "2025-02-06",
        "claims": [
            {
                "claim_id": "abc123",
                "type": "numerical",
                "category": "revenue",
                "metric": "quarterly revenue",
                "subcategory": None,
                "source_span": "Net sales expected between $151B and $155.5B.",
                "horizon": "next_quarter",
                "horizon_start": "2025-01-01",
                "horizon_end": "2025-03-31",
                "value_or_amount": "$151–155.5B",
                "confidence_language": "certain",
                "speaker": "CFO",
                "speaker_type": "Corporate Participant",
                "component_order": 5,
            }
        ],
    }


def test_write_json_creates_file(tmp_path: Path, sample_enriched: dict):
    out = tmp_path / "out.json"
    write_json(sample_enriched, out)
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["ticker"] == "AMZN"
    assert len(loaded["claims"]) == 1


def test_write_csv_creates_file(tmp_path: Path, sample_enriched: dict):
    out = tmp_path / "out.csv"
    write_csv(sample_enriched, out)
    assert out.exists()
    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AMZN"
    assert rows[0]["source_span"] == "Net sales expected between $151B and $155.5B."


def test_write_csv_includes_horizon_dates(tmp_path: Path, sample_enriched: dict):
    out = tmp_path / "out.csv"
    write_csv(sample_enriched, out)
    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert rows[0]["horizon_start"] == "2025-01-01"
    assert rows[0]["horizon_end"] == "2025-03-31"
