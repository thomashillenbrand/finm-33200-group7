from pathlib import Path

import pandas as pd
import pytest

from extractor.loader import TranscriptLoader


@pytest.fixture()
def sample_parquet(tmp_path: Path) -> Path:
    """Minimal WRDS-format transcript parquet for offline testing."""
    df = pd.DataFrame(
        {
            "transcriptid": [1, 1, 1, 2, 2],
            "headline": [
                "TSLA Q4 2023 Earnings Call",
                "TSLA Q4 2023 Earnings Call",
                "TSLA Q4 2023 Earnings Call",
                "TSLA Q3 2023 Earnings Call",
                "TSLA Q3 2023 Earnings Call",
            ],
            "mostimportantdateutc": [
                "2024-01-24",
                "2024-01-24",
                "2024-01-24",
                "2023-10-18",
                "2023-10-18",
            ],
            "componentorder": [1, 2, 3, 1, 2],
            "transcriptpersonname": [
                "Elon Musk",
                "Elon Musk",
                "Analyst A",
                "Elon Musk",
                "CFO",
            ],
            "componenttext": [
                "Welcome to Tesla Q4 earnings.",
                "We expect to grow revenue significantly.",
                "What is your capex plan?",
                "Thank you for joining Q3 call.",
                "Margins are expected to improve.",
            ],
        }
    )
    path = tmp_path / "TSLA_transcripts.parquet"
    df.to_parquet(path, index=False)
    return path


def test_loader_rejects_missing_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        TranscriptLoader(tmp_path / "nonexistent.parquet")


def test_loader_accepts_str_and_pathlib(sample_parquet: Path):
    loader_str = TranscriptLoader(str(sample_parquet))
    loader_path = TranscriptLoader(sample_parquet)
    assert len(loader_str.list_calls()) == len(loader_path.list_calls())


def test_list_calls_returns_expected_columns(sample_parquet: Path):
    calls = TranscriptLoader(sample_parquet).list_calls()
    assert "transcriptid" in calls.columns
    assert "headline" in calls.columns
    assert "mostimportantdateutc" in calls.columns


def test_list_calls_unique_per_transcript(sample_parquet: Path):
    calls = TranscriptLoader(sample_parquet).list_calls()
    assert len(calls) == 2
    assert calls["transcriptid"].nunique() == 2


def test_get_transcript_assembles_text(sample_parquet: Path):
    text = TranscriptLoader(sample_parquet).get_transcript(1)
    assert "Welcome to Tesla Q4 earnings." in text
    assert "We expect to grow revenue significantly." in text
    assert "What is your capex plan?" in text


def test_get_transcript_respects_component_order(sample_parquet: Path):
    text = TranscriptLoader(sample_parquet).get_transcript(1)
    assert text.index("Welcome") < text.index("We expect") < text.index("What is your")


def test_get_transcript_raises_for_unknown_id(sample_parquet: Path):
    with pytest.raises(KeyError):
        TranscriptLoader(sample_parquet).get_transcript(9999)
