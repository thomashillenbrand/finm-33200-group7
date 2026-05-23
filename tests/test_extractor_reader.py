"""Transcript-reader tests for the claim-extraction pipeline (workstream B).

The reader consumes the WRDS transcript parquet written by ``data_pull.py``;
these tests build a small parquet in a tmp dir and exercise the loader.
"""

from datetime import date

import pandas as pd
import pytest

from extractor.reader import build_call_input, load_calls

_COLUMNS = [
    "companyid", "companyname", "keydevid", "transcriptid", "headline",
    "mostimportantdateutc", "transcriptcomponentid", "componentorder",
    "transcriptcomponenttypename", "transcriptpersonname", "speaker_company",
    "speakertypename", "componenttext",
]

_META_COLUMNS = [
    "transcriptid", "transcriptpresentationtypename", "transcriptcreationdate_utc",
]

# Two calls, deliberately written out of date order. transcriptid is stored as
# a float string ('222.0') to exercise the id-casting path. Each call here has
# a single transcript version (one transcriptid per keydevid).
_ROWS = [
    # --- Call 2 (later date) written first, to test date sorting ---
    ["27444752.0", "Tesla, Inc.", "5002.0", "222.0",
     "Tesla, Inc., Q1 2022 Earnings Call, Apr 20, 2022", "2022-04-20",
     "2001", "0", "Presentation Operator Message", "Operator", "",
     "Operator", "Welcome to the call."],
    ["27444752.0", "Tesla, Inc.", "5002.0", "222.0",
     "Tesla, Inc., Q1 2022 Earnings Call, Apr 20, 2022", "2022-04-20",
     "2002", "1", "Presenter Speech", "Elon Musk", "",
     "Executives", "We expect strong delivery growth this year."],
    ["27444752.0", "Tesla, Inc.", "5002.0", "222.0",
     "Tesla, Inc., Q1 2022 Earnings Call, Apr 20, 2022", "2022-04-20",
     "2003", "2", "Question", "Some Analyst", "",
     "Analysts", "What about margins?"],
    ["27444752.0", "Tesla, Inc.", "5002.0", "222.0",
     "Tesla, Inc., Q1 2022 Earnings Call, Apr 20, 2022", "2022-04-20",
     "2004", "3", "Answer", "Zachary Kirkhorn", "",
     "Executives", "Margins should expand next quarter."],
    # --- Call 1 (earlier date) ---
    ["27444752.0", "Tesla, Inc.", "5001.0", "111.0",
     "Tesla, Inc., Q4 2021 Earnings Call, Jan 26, 2022", "2022-01-26",
     "1001", "0", "Presenter Speech", "Elon Musk", "",
     "Executives", "We plan record production in 2022."],
]


def _write_parquet(path, rows):
    pd.DataFrame(rows, columns=_COLUMNS).to_parquet(path, index=False)


def test_load_calls_groups_and_sorts_by_date(tmp_path):
    pq = tmp_path / "tesla_transcripts.parquet"
    _write_parquet(pq, _ROWS)

    calls = load_calls(pq)

    assert len(calls) == 2
    # Earlier call first, despite being written last in the file.
    assert calls[0].call_date == date(2022, 1, 26)
    assert calls[1].call_date == date(2022, 4, 20)


def test_load_calls_parses_metadata(tmp_path):
    pq = tmp_path / "tesla_transcripts.parquet"
    _write_parquet(pq, _ROWS)

    q1 = load_calls(pq)[1]
    assert q1.ticker == "TSLA"
    assert q1.company == "Tesla, Inc."
    assert q1.transcript_id == 222  # float string '222.0' -> int
    assert q1.fiscal_period == "Q1 2022"
    assert len(q1.turns) == 4


def test_management_turns_keeps_only_executives(tmp_path):
    pq = tmp_path / "tesla_transcripts.parquet"
    _write_parquet(pq, _ROWS)

    q1 = load_calls(pq)[1]
    mgmt = q1.management_turns()

    assert len(mgmt) == 2  # presenter speech + answer; operator/analyst dropped
    assert {t.speaker_type for t in mgmt} == {"Executives"}
    assert {t.speaker_name for t in mgmt} == {"Elon Musk", "Zachary Kirkhorn"}


def test_build_call_input_labels_speakers_and_excludes_non_management(tmp_path):
    pq = tmp_path / "tesla_transcripts.parquet"
    _write_parquet(pq, _ROWS)

    q1 = load_calls(pq)[1]
    text = build_call_input(q1)

    assert "Elon Musk (Presenter Speech):" in text       # executive turn
    assert "Zachary Kirkhorn (Answer):" in text          # executive turn
    assert "We expect strong delivery growth" in text
    assert "Margins should expand" in text
    assert "[#" not in text                              # no turn ids exposed
    assert "Welcome to the call." not in text            # operator turn dropped
    assert "What about margins?" not in text             # analyst turn dropped


def test_unknown_company_raises(tmp_path):
    bad = [r[:] for r in _ROWS[:1]]
    bad[0][1] = "Unknown Holdings, Inc."
    pq = tmp_path / "bad_transcripts.parquet"
    _write_parquet(pq, bad)

    with pytest.raises(KeyError, match="No ticker mapping"):
        load_calls(pq)


def test_collapses_versions_to_latest_final_with_metadata(tmp_path):
    """One earnings call stored as three transcript versions collapses to a
    single EarningsCall -- the latest 'Final' version."""
    rows = []
    for tid in ("301", "302", "303"):   # all keydevid 700, one call
        rows.append(
            ["27", "Tesla, Inc.", "700.0", tid,
             "Tesla, Inc., Q1 2024 Earnings Call, Apr 23, 2024", "2024-04-23",
             f"{tid}01", "0", "Presenter Speech", "Elon Musk", "",
             "Executives", f"Version {tid} remarks."]
        )
    pq = tmp_path / "tv_transcripts.parquet"
    _write_parquet(pq, rows)
    pd.DataFrame(
        [["301", "Preliminary", "2024-04-23"],
         ["302", "Final", "2024-04-24"],
         ["303", "Final", "2024-04-26"]],
        columns=_META_COLUMNS,
    ).to_parquet(tmp_path / "tv_metadata.parquet", index=False)

    calls = load_calls(pq)

    assert len(calls) == 1                   # three versions -> one call
    assert calls[0].transcript_id == 303     # latest Final, not Preliminary


def test_collapses_versions_fallback_most_complete_without_metadata(tmp_path):
    """With no metadata parquet, the most-complete transcript version wins."""
    rows = [
        ["27", "Tesla, Inc.", "800.0", "401",
         "Tesla, Inc., Q2 2024 Earnings Call, Jul 23, 2024", "2024-07-23",
         "40101", "0", "Presenter Speech", "Elon Musk", "",
         "Executives", "Short version."],
        ["27", "Tesla, Inc.", "800.0", "402",
         "Tesla, Inc., Q2 2024 Earnings Call, Jul 23, 2024", "2024-07-23",
         "40201", "0", "Presenter Speech", "Elon Musk", "",
         "Executives", "Full version, part one."],
        ["27", "Tesla, Inc.", "800.0", "402",
         "Tesla, Inc., Q2 2024 Earnings Call, Jul 23, 2024", "2024-07-23",
         "40202", "1", "Answer", "Vaibhav Taneja", "",
         "Executives", "Full version, part two."],
    ]
    pq = tmp_path / "fb_transcripts.parquet"   # no fb_metadata.parquet sibling
    _write_parquet(pq, rows)

    calls = load_calls(pq)

    assert len(calls) == 1                   # two versions -> one call
    assert calls[0].transcript_id == 402     # more components than 401
