import pandas as pd

from extractor.provenance import find_speaker, is_management_speaker


@staticmethod
def _make_df():
    return pd.DataFrame({
        "transcriptid": [1, 1, 1],
        "componentorder": [1, 2, 3],
        "transcriptpersonname": ["CEO", "CFO", "Analyst"],
        "speakertypename": ["Corporate Participant", "Corporate Participant", "Analyst"],
        "componenttext": [
            "We expect Q1 revenue between $24 and $25 billion.",
            "Capital expenditure will be approximately $10 billion.",
            "Can you elaborate on your margin outlook?",
        ],
    })


def test_find_speaker_exact_match():
    df = _make_df()
    result = find_speaker("We expect Q1 revenue between $24 and $25 billion.", df)
    assert result["speaker"] == "CEO"
    assert result["speaker_type"] == "Corporate Participant"


def test_find_speaker_partial_match():
    df = _make_df()
    result = find_speaker("Capital expenditure will be approximately $10 billion.", df)
    assert result["speaker"] == "CFO"


def test_find_speaker_no_match_returns_none():
    df = _make_df()
    result = find_speaker("This text does not appear anywhere in the transcript.", df)
    assert result["speaker"] is None
    assert result["speaker_type"] is None
    assert result["component_order"] is None


def test_is_management_speaker_corporate():
    assert is_management_speaker("Corporate Participant") is True


def test_is_management_speaker_analyst():
    assert is_management_speaker("Analyst") is False


def test_is_management_speaker_none():
    assert is_management_speaker(None) is False
