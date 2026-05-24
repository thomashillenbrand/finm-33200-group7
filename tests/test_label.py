"""Tests for the interactive agent-free gold-set labeling helper (`verifier.label`).

Offline only -- no network, no LLM. The interactive session is driven through
an injected ``ask`` callable fed a scripted list of responses.
"""

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from schemas import CSV_FIELDS
from verifier import label
from verifier.gold import GoldEvidence, GoldLabel, load_gold_labels

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
    "horizon_raw": "this year",
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

# q.htm hits sweep terms 'repurchase' and 'dividend'; k.htm hits none of them
# (but contains 'factory', used to exercise the interactive 'more' command).
_Q_HTML = ("<html><body><p>During the quarter the company repurchased $5 million "
           "of common stock and paid a quarterly dividend.</p></body></html>")
_K_HTML = "<html><body><p>During the period we expanded our main factory.</p></body></html>"


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "Pulled_data"
    sec = root / "FAKE" / "SEC"
    sec.mkdir(parents=True)
    (sec / "q.htm").write_text(_Q_HTML, encoding="utf-8")
    (sec / "k.htm").write_text(_K_HTML, encoding="utf-8")
    (sec / "pre.htm").write_text("<html><body><p>old</p></body></html>", encoding="utf-8")
    (sec / "amd.htm").write_text("<html><body><p>amended</p></body></html>", encoding="utf-8")
    pd.DataFrame(_FILINGS).to_parquet(sec / "FAKE_sec_filings_index.parquet")
    monkeypatch.setattr(label, "PULLED_DATA_ROOT", root)

    claims_csv = tmp_path / "claims.csv"
    with claims_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CSV_FIELDS))
        writer.writeheader()
        writer.writerow(_CLAIM_ROW)
    return {"root": root, "sec": sec, "claims_csv": claims_csv}


def _scripted(*responses):
    """An ``ask`` callable that returns the scripted responses in order."""
    it = iter(responses)
    return lambda prompt="": next(it)


def _filings(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    idx = label._load_filing_index("FAKE")
    return claim, label.candidate_filings(
        claim, idx, until_date=label.grading_window(claim))


# ── claim loading ──────────────────────────────────────────────────────────

def test_load_claim_reads_the_row(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    assert claim.ticker == "FAKE"
    assert claim.call_date == date(2024, 1, 15)
    assert claim.claim_type == "capital_allocation"
    assert claim.extracted_at is None


def test_load_claim_unknown_id_exits(env):
    with pytest.raises(SystemExit):
        label.load_claim(env["claims_csv"], "no_such_claim")


# ── grading window ─────────────────────────────────────────────────────────

def test_grading_window_uses_resolved_horizon(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    expected = date(2024, 12, 31) + timedelta(days=label._REPORTING_LAG_DAYS)
    assert label.grading_window(claim) == expected


def test_grading_window_defaults_when_horizon_unresolved(env):
    claim = label.load_claim(env["claims_csv"], _CLAIM_ID)
    claim.horizon_end_date = None
    expected = claim.call_date + timedelta(
        days=label._DEFAULT_WINDOW_DAYS + label._REPORTING_LAG_DAYS)
    assert label.grading_window(claim) == expected


# ── candidate filings + sweep ──────────────────────────────────────────────

def test_candidate_filings_filters_pre_call_and_wrong_form(env):
    claim, cands = _filings(env)
    assert set(cands["accessionNumber"]) == {"ACC-Q", "ACC-K"}


def test_sweep_finds_capital_allocation_terms(env):
    claim, cands = _filings(env)
    found = label.sweep(cands, env["sec"], terms=label._SWEEP_TERMS["capital_allocation"])
    assert found, "sweep should find the repurchase/dividend hits in q.htm"
    assert all(isinstance(c, label.Candidate) for c in found)
    assert {c.term for c in found} & {"repurchase", "dividend"}
    assert found[0].to_evidence().form in ("10-K", "10-Q", "8-K")


def test_resolve_filing_path_normalizes_windows_separators():
    p = label._resolve_filing_path(Path("/x/SEC"), "10-Q\\sub\\file.htm")
    assert p == Path("/x/SEC/10-Q/sub/file.htm")


# ── gold-file I/O ──────────────────────────────────────────────────────────

def test_load_gold_claim_ids_skips_bad_lines(tmp_path):
    gp = tmp_path / "g.jsonl"
    gp.write_text('{"claim_id": "A"}\nnot json\n\n{"claim_id": "B"}\n',
                  encoding="utf-8")
    assert label.load_gold_claim_ids(gp) == {"A", "B"}


def test_load_gold_claim_ids_missing_file(tmp_path):
    assert label.load_gold_claim_ids(tmp_path / "nope.jsonl") == set()


def test_append_gold_label_round_trips(tmp_path):
    gp = tmp_path / "sub" / "gold.jsonl"          # parent dir does not exist
    lbl = GoldLabel(
        claim_id="A", ticker="FAKE", labeler="t",
        labeled_at=date(2024, 6, 1).isoformat() + "T00:00:00",
        expected_evidence=[GoldEvidence(
            accession_no="ACC-Q", form="10-Q", filing_date=date(2024, 4, 30),
            quote="repurchased stock")],
        verdict="verified", confidence="high")
    label.append_gold_label(gp, lbl)
    label.append_gold_label(gp, lbl)
    assert len(load_gold_labels(gp)) == 2


# ── interactive session ────────────────────────────────────────────────────

def test_run_session_writes_a_decisive_label(env):
    claim, cands = _filings(env)
    gold = env["root"].parent / "pilot_fake.jsonl"
    result = label.run_session(
        claim, cands, env["sec"], gold, "tester", label.grading_window(claim),
        ask=_scripted("1", "1", "h", "debt clearly fell"), say=lambda m: None)
    assert result is not None
    labels = load_gold_labels(gold)
    assert len(labels) == 1
    assert labels[0].verdict == "verified"
    assert labels[0].confidence == "high"
    assert len(labels[0].expected_evidence) == 1
    assert labels[0].labeler == "tester"


def test_run_session_none_then_not_yet_resolvable(env):
    claim, cands = _filings(env)
    gold = env["root"].parent / "g.jsonl"
    result = label.run_session(
        claim, cands, env["sec"], gold, "tester", label.grading_window(claim),
        ask=_scripted("none", "4", "l", ""), say=lambda m: None)
    assert result is not None
    labels = load_gold_labels(gold)
    assert labels[0].verdict == "not_yet_resolvable"
    assert labels[0].expected_evidence == []


def test_run_session_quit_writes_nothing(env):
    claim, cands = _filings(env)
    gold = env["root"].parent / "g.jsonl"
    result = label.run_session(
        claim, cands, env["sec"], gold, "tester", label.grading_window(claim),
        ask=_scripted("quit"), say=lambda m: None)
    assert result is None
    assert not gold.exists()


def test_run_session_decisive_without_evidence_reprompts(env):
    """Choosing a decisive verdict with no evidence must re-prompt, not crash."""
    claim, cands = _filings(env)
    gold = env["root"].parent / "g.jsonl"
    # 'none' -> no evidence; verdict '1' (verified) is rejected -> re-prompt;
    # '4' (not_yet_resolvable) accepted.
    result = label.run_session(
        claim, cands, env["sec"], gold, "tester", label.grading_window(claim),
        ask=_scripted("none", "1", "4", "l", ""), say=lambda m: None)
    assert result is not None
    assert load_gold_labels(gold)[0].verdict == "not_yet_resolvable"


def test_run_session_more_command_adds_candidates(env):
    """'more <term>' runs an extra keyword search and surfaces new hits."""
    claim, cands = _filings(env)
    gold = env["root"].parent / "g.jsonl"
    out: list[str] = []
    # 'factory' is not a standard sweep term but appears in k.htm.
    result = label.run_session(
        claim, cands, env["sec"], gold, "tester", label.grading_window(claim),
        ask=_scripted("more factory", "all", "quit"), say=out.append)
    assert result is None                       # quit -> nothing written
    assert any("new hit(s) for 'factory'" in line for line in out)


def test_run_session_appends_not_overwrites(env):
    """A second label appends; the first is preserved."""
    claim, cands = _filings(env)
    gold = env["root"].parent / "g.jsonl"
    label.run_session(claim, cands, env["sec"], gold, "labeler-one",
                      label.grading_window(claim),
                      ask=_scripted("1", "1", "h", ""), say=lambda m: None)
    label.run_session(claim, cands, env["sec"], gold, "labeler-two",
                      label.grading_window(claim),
                      ask=_scripted("1", "3", "m", ""), say=lambda m: None)
    labels = load_gold_labels(gold)
    assert len(labels) == 2
    assert {l.labeler for l in labels} == {"labeler-one", "labeler-two"}


# ── independence guarantee ─────────────────────────────────────────────────

def test_label_module_imports_nothing_from_agent_or_index():
    src = Path(label.__file__).read_text(encoding="utf-8")
    import_lines = [ln.strip() for ln in src.splitlines()
                    if ln.strip().startswith(("import ", "from "))]
    forbidden = ("faiss", "verifier.agent", "OpenAIEmbeddings",
                 "verifier.tools", "verifier.index")
    for line in import_lines:
        for bad in forbidden:
            assert bad not in line, f"forbidden import in label.py: {line}"
