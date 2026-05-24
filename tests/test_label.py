"""Tests for the agent-free gold-set labeling helper (`verifier.label`).

Offline only -- no network, no LLM. A fixture builds a tiny pulled-data tree
(SEC filing index + a couple of HTML files) and points the helper at it.
"""

import csv
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from schemas import CSV_FIELDS
from verifier import label
from verifier.gold import GoldEvidence, load_gold_labels

# A claim row with every CSV_FIELDS column. extracted_at is "" (the extractor
# writes empty for absent optionals) to exercise the optional-field handling.
_CLAIM_ROW = {
    "claim_id": "FAKE_20240115_test0001",
    "ticker": "FAKE",
    "company": "Fake Corp, Inc.",
    "call_date": "2024-01-15",
    "fiscal_period": "Q4 2023",
    "claim_type": "capital_allocation",
    "verbatim_quote": "we plan to repurchase $5 million of common stock",
    "quote_verbatim": "True",
    "summary": "Management plans a $5M buyback.",
    "horizon_raw": "next year",
    "horizon_period": "FY2024",
    "horizon_end_date": "2024-12-31",
    "speaker_name": "Jane Doe",
    "speaker_type": "Executives",
    "transcript_id": "999",
    "component_id": "12",
    "source_call": "Fake Corp, Inc., Q4 2023 Earnings Call",
    "extraction_model": "openai:gpt-4o-mini",
    "prompt_version": "b-extract-v4",
    "extracted_at": "",
}

_CLAIM_ID = _CLAIM_ROW["claim_id"]

# Four filings: two after the call in scope, one pre-call, one wrong form.
_FILINGS = [
    {"accessionNumber": "ACC-Q", "filingDate": "2024-04-30", "form": "10-Q",
     "localPath": "q.htm"},
    {"accessionNumber": "ACC-K", "filingDate": "2024-02-20", "form": "8-K",
     "localPath": "k.htm"},
    {"accessionNumber": "ACC-PRE", "filingDate": "2023-11-01", "form": "10-Q",
     "localPath": "pre.htm"},
    {"accessionNumber": "ACC-AMD", "filingDate": "2024-05-01", "form": "10-K/A",
     "localPath": "amd.htm"},
]

_Q_HTML = ("<html><body><p>The company repurchased $5 million of common stock "
           "during the quarter.</p></body></html>")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Build the fixture pulled-data tree + claims CSV; patch PULLED_DATA_ROOT."""
    root = tmp_path / "Pulled_data"
    sec = root / "FAKE" / "SEC"
    sec.mkdir(parents=True)
    (sec / "q.htm").write_text(_Q_HTML, encoding="utf-8")
    (sec / "k.htm").write_text(
        "<html><body><p>An unrelated corporate update.</p></body></html>",
        encoding="utf-8")
    (sec / "pre.htm").write_text("<html><body><p>old</p></body></html>",
                                 encoding="utf-8")
    (sec / "amd.htm").write_text("<html><body><p>amended</p></body></html>",
                                 encoding="utf-8")
    pd.DataFrame(_FILINGS).to_parquet(sec / "FAKE_sec_filings_index.parquet")
    monkeypatch.setattr(label, "PULLED_DATA_ROOT", root)

    claims_csv = tmp_path / "claims.csv"
    with claims_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        writer.writerow(_CLAIM_ROW)
    return {"root": root, "claims_csv": claims_csv}


def _filing_row(accession: str):
    idx = label._load_filing_index("FAKE")
    sub = idx[idx["accessionNumber"] == accession]
    return next(sub.itertuples(index=False))


# ── claim loading ──────────────────────────────────────────────────────────

def test_load_claim_reads_the_row(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    assert claim.ticker == "FAKE"
    assert claim.call_date == date(2024, 1, 15)
    assert claim.claim_type == "capital_allocation"
    assert claim.quote_verbatim is True          # "True" coerced to bool
    assert claim.extracted_at is None            # "" restored to None


def test_load_claim_unknown_id_exits(env):
    with pytest.raises(SystemExit):
        label.load_claim(env["claims_csv"], "no_such_claim")


# ── candidate filings ──────────────────────────────────────────────────────

def test_candidate_filings_filters_pre_call_and_wrong_form(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    cands = label.candidate_filings(claim, label._load_filing_index("FAKE"))
    # pre-call 10-Q and the 10-K/A amendment are dropped.
    assert set(cands["accessionNumber"]) == {"ACC-Q", "ACC-K"}


def test_candidate_filings_respects_forms_arg(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    cands = label.candidate_filings(
        claim, label._load_filing_index("FAKE"), forms=("10-Q",))
    assert list(cands["accessionNumber"]) == ["ACC-Q"]


def test_candidate_filings_sorted_by_date(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    cands = label.candidate_filings(claim, label._load_filing_index("FAKE"))
    assert list(cands["accessionNumber"]) == ["ACC-K", "ACC-Q"]  # Feb before Apr


# ── keyword search ─────────────────────────────────────────────────────────

def test_search_filing_finds_keyword(env):
    text = label._html_to_text(_Q_HTML.encode())
    matches = label.search_filing(text, "repurchased", context=40)
    assert len(matches) == 1
    assert "repurchased" in matches[0].snippet.lower()


def test_search_filing_regex_mode(env):
    text = label._html_to_text(_Q_HTML.encode())
    matches = label.search_filing(text, r"repurchas\w+", regex=True, context=20)
    assert len(matches) == 1


def test_search_filing_no_match_returns_empty():
    assert label.search_filing("nothing relevant here", "buyback", context=10) == []


# ── evidence fragments ─────────────────────────────────────────────────────

def test_render_evidence_emits_valid_goldevidence(env):
    text = label._html_to_text(_Q_HTML.encode())
    match = label.search_filing(text, "repurchased", context=80)[0]
    out = label._render_evidence(_filing_row("ACC-Q"), match)
    fragment = out.split("fragment: ", 1)[1].splitlines()[0]
    ev = GoldEvidence.model_validate_json(fragment)
    assert ev.accession_no == "ACC-Q"
    assert ev.form == "10-Q"
    assert "repurchased" in ev.quote.lower()


def test_render_evidence_truncates_quote_to_500(env):
    big = "repurchase " + "x" * 2000
    text = label._html_to_text(f"<html><body><p>{big}</p></body></html>".encode())
    match = label.search_filing(text, "repurchase", context=1500)[0]
    out = label._render_evidence(_filing_row("ACC-Q"), match)
    fragment = out.split("fragment: ", 1)[1].splitlines()[0]
    ev = GoldEvidence.model_validate_json(fragment)
    assert len(ev.quote) <= 500


# ── filing-path resolution ─────────────────────────────────────────────────

def test_resolve_filing_path_normalizes_windows_separators():
    p = label._resolve_filing_path(Path("/x/SEC"), "10-Q\\sub\\file.htm")
    assert p == Path("/x/SEC/10-Q/sub/file.htm")


# ── skeleton ───────────────────────────────────────────────────────────────

def test_skeleton_has_placeholder_verdict(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    row = json.loads(label._render_skeleton(claim, "tester"))
    assert row["verdict"].startswith("<FILL")
    assert row["confidence"].startswith("<FILL")
    assert row["expected_evidence"] == []
    assert row["labeler"] == "tester"
    assert row["claim_id"] == _CLAIM_ID


def test_skeleton_rejected_until_filled(env, tmp_path):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    line = label._render_skeleton(claim, "tester")

    raw = tmp_path / "raw.jsonl"
    raw.write_text(line + "\n", encoding="utf-8")
    with pytest.raises(ValueError):           # placeholder verdict is invalid
        load_gold_labels(raw)

    row = json.loads(line)                    # fill it with a valid verdict
    row["verdict"] = "not_yet_resolvable"     # allows empty expected_evidence
    row["confidence"] = "low"
    filled = tmp_path / "filled.jsonl"
    filled.write_text(json.dumps(row) + "\n", encoding="utf-8")
    labels = load_gold_labels(filled)
    assert len(labels) == 1
    assert labels[0].verdict == "not_yet_resolvable"


# ── independence guarantee ─────────────────────────────────────────────────

def test_label_module_imports_nothing_from_agent_or_index():
    """The gold set must stay independent of the agent it grades: label.py may
    not import the agent, faiss, embeddings, the tools, or the FAISS index."""
    src = Path(label.__file__).read_text(encoding="utf-8")
    import_lines = [ln.strip() for ln in src.splitlines()
                    if ln.strip().startswith(("import ", "from "))]
    forbidden = ("faiss", "verifier.agent", "OpenAIEmbeddings",
                 "verifier.tools", "verifier.index")
    for line in import_lines:
        for bad in forbidden:
            assert bad not in line, f"forbidden import in label.py: {line}"
