"""Transcript-reader tests for the claim-extraction pipeline (workstream B)."""

import csv
from datetime import date

import pytest

from extractor.reader import build_call_input, load_calls

_COLUMNS = [
    "companyid", "companyname", "keydevid", "transcriptid", "headline",
    "mostimportantdateutc", "transcriptcomponentid", "componentorder",
    "transcriptcomponenttypename", "transcriptpersonname", "speaker_company",
    "speakertypename", "componenttext",
]

# Two calls, deliberately written out of date order. transcriptid is stored as
# a float string ('222.0') to exercise the id-casting path.
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


def _write_csv(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_COLUMNS)
        writer.writerows(rows)


def test_load_calls_groups_and_sorts_by_date(tmp_path):
    csv_path = tmp_path / "tesla.csv"
    _write_csv(csv_path, _ROWS)

    calls = load_calls(csv_path)

    assert len(calls) == 2
    # Earlier call first, despite being written last in the file.
    assert calls[0].call_date == date(2022, 1, 26)
    assert calls[1].call_date == date(2022, 4, 20)


def test_load_calls_parses_metadata(tmp_path):
    csv_path = tmp_path / "tesla.csv"
    _write_csv(csv_path, _ROWS)

    q1 = load_calls(csv_path)[1]
    assert q1.ticker == "TSLA"
    assert q1.company == "Tesla, Inc."
    assert q1.transcript_id == 222  # float string '222.0' -> int
    assert q1.fiscal_period == "Q1 2022"
    assert len(q1.turns) == 4


def test_management_turns_keeps_only_executives(tmp_path):
    csv_path = tmp_path / "tesla.csv"
    _write_csv(csv_path, _ROWS)

    q1 = load_calls(csv_path)[1]
    mgmt = q1.management_turns()

    assert len(mgmt) == 2  # presenter speech + answer; operator/analyst dropped
    assert {t.speaker_type for t in mgmt} == {"Executives"}
    assert {t.speaker_name for t in mgmt} == {"Elon Musk", "Zachary Kirkhorn"}


def test_build_call_input_labels_speakers_and_excludes_non_management(tmp_path):
    csv_path = tmp_path / "tesla.csv"
    _write_csv(csv_path, _ROWS)

    q1 = load_calls(csv_path)[1]
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
    csv_path = tmp_path / "bad.csv"
    _write_csv(csv_path, bad)

    with pytest.raises(KeyError, match="No ticker mapping"):
        load_calls(csv_path)
