"""Offline tests for the GPT-5.5 gold-set auto-labeler. The LLM is injected as a
fake ``decider`` with an ``.invoke(messages)`` method (mirrors verifier.label's
injected IO), so no network call happens."""
from __future__ import annotations

import importlib
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from verifier import autolabel
from verifier.gold import GoldLabel
from verifier.label import Candidate


def _claim_row(claim_id, ticker, claim_type, quote):
    return {
        "claim_id": claim_id, "ticker": ticker, "company": f"{ticker} Inc",
        "call_date": "2020-01-30", "fiscal_period": "Q4 2019",
        "claim_type": claim_type, "verbatim_quote": quote, "quote_verbatim": True,
        "summary": quote, "horizon_raw": "by 2021", "horizon_period": "FY2021",
        "horizon_end_date": "2021-12-31", "speaker_name": "X",
        "speaker_type": "Executives", "transcript_id": 1, "component_id": 1,
        "source_call": "call", "extraction_model": "openai:gpt-5.5",
        "prompt_version": "b-extract-v5", "extracted_at": "",
    }


def test_claim_has_figure_ignores_year_and_form_digits():
    assert autolabel.claim_has_figure("we will spend $2 billion on capex")
    assert autolabel.claim_has_figure("we will grow capex 15%")
    # bare years / form names / model designations are NOT figures
    assert not autolabel.claim_has_figure("we will keep investing through 2021")
    assert not autolabel.claim_has_figure("see the 10-K for our capex plans")
    assert not autolabel.claim_has_figure("we will add fulfillment capacity")


def test_select_residual_subset_keeps_only_no_figure_capital_allocation():
    df = pd.DataFrame([
        _claim_row("A_num", "AMZN", "numerical_guidance", "revenue up $1 billion"),
        _claim_row("A_fig", "AMZN", "capital_allocation", "buy back $5 billion"),
        _claim_row("A_res", "AMZN", "capital_allocation", "add fulfillment capacity"),
        _claim_row("T_res", "TSLA", "capital_allocation", "build the Berlin factory"),
    ])
    ids = autolabel.select_residual_subset(df, per_ticker_cap=8, seed=0)
    assert ids == ["A_res", "T_res"]  # sorted; figure + numerical dropped


def test_select_residual_subset_respects_per_ticker_cap_and_is_deterministic():
    rows = [_claim_row(f"A_{i}", "AMZN", "capital_allocation", "add capacity") for i in range(10)]
    df = pd.DataFrame(rows)
    a = autolabel.select_residual_subset(df, per_ticker_cap=3, seed=0)
    b = autolabel.select_residual_subset(df, per_ticker_cap=3, seed=0)
    assert len(a) == 3 and a == b              # capped + deterministic


def _cand(i):
    return Candidate(
        accession_no=f"acc-{i}", form="10-Q", filing_date=date(2021, 5, 1),
        local_path=f"10-Q/f{i}.htm", term="capital expenditures",
        snippet=f"... capital expenditures of note {i} ...", report_date=date(2021, 3, 31),
    )


class _FakeDecider:
    """Returns a scripted list of AutoLabelDecision, one per .invoke() call."""
    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0
    def invoke(self, messages):
        d = self._decisions[min(self.calls, len(self._decisions) - 1)]
        self.calls += 1
        return d


def _claim_obj():
    from verifier.label import _row_to_claim
    return _row_to_claim(_claim_row("C1", "AMZN", "capital_allocation", "add fulfillment capacity"))


def test_decision_to_evidence_maps_indices_and_drops_out_of_range():
    cands = [_cand(1), _cand(2)]
    ev = autolabel._decision_to_evidence(cands, [1, 99])  # 99 out of range -> dropped
    assert [e.accession_no for e in ev] == ["acc-1"]


def test_autolabel_claim_builds_label_from_decision():
    cands = [_cand(1), _cand(2)]
    decider = _FakeDecider([autolabel.AutoLabelDecision(
        selected_indices=[2], verdict="verified", confidence="high", notes="ok")])
    label = autolabel._build_label(_claim_obj(), cands, decider, "RUBRIC", labeler="gpt-5.5")
    assert isinstance(label, GoldLabel)
    assert label.verdict == "verified"
    assert [e.accession_no for e in label.expected_evidence] == ["acc-2"]
    assert label.labeler == "gpt-5.5"


def test_decisive_without_evidence_reprompts_then_falls_back():
    cands = [_cand(1)]
    # 1st: decisive but no evidence -> reprompt; 2nd: still decisive, no evidence -> forced n_y_r
    decider = _FakeDecider([
        autolabel.AutoLabelDecision(selected_indices=[], verdict="verified", confidence="high"),
        autolabel.AutoLabelDecision(selected_indices=[], verdict="contradicted", confidence="low"),
    ])
    label = autolabel._build_label(_claim_obj(), cands, decider, "RUBRIC", labeler="gpt-5.5")
    assert decider.calls == 2
    assert label.verdict == "not_yet_resolvable"
    assert label.expected_evidence == []


def test_build_label_messages_includes_rubric_claim_and_numbered_candidates():
    cands = [_cand(1), _cand(2)]
    msgs = autolabel.build_label_messages(_claim_obj(), cands, "THE-RUBRIC-TEXT")
    assert msgs[0]["role"] == "system"
    user = msgs[1]["content"]
    assert "THE-RUBRIC-TEXT" in user                 # rubric is in the labeler prompt
    assert "add fulfillment capacity" in user        # the claim quote
    assert "[1]" in user and "[2]" in user            # 1-based numbered candidates
    assert "acc-1" in user


def test_load_rubric_reads_the_file(tmp_path):
    p = tmp_path / "rubric.md"
    p.write_text("VERDICTS: verified, ...", encoding="utf-8")
    assert "VERDICTS" in autolabel.load_rubric(p)


def test_autolabel_import_graph_excludes_agent_and_faiss():
    """Importing autolabel must not pull in the agent stack / FAISS / tools /
    embeddings — same independence guarantee as verifier.label."""
    for mod in [m for m in list(sys.modules) if "verifier.agent" in m or m == "faiss"]:
        del sys.modules[mod]
    importlib.import_module("verifier.autolabel")
    forbidden = ("faiss", "verifier.agent", "verifier.tools")
    leaked = [m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)]
    assert leaked == [], f"autolabel must not import {forbidden}; leaked: {leaked}"


def test_agent_module_does_not_load_the_rubric():
    """The gpt-5.1 agent must never see docs/labeling_rubric.md."""
    src = Path("src/verifier/agent.py").read_text(encoding="utf-8")
    assert "labeling_rubric" not in src


def test_build_decider_raises_without_env(monkeypatch):
    monkeypatch.delenv("GOLD_LABELER_MODEL", raising=False)
    with pytest.raises(RuntimeError, match="GOLD_LABELER_MODEL"):
        autolabel.build_decider()


def test_cli_select_writes_pinned_id_file(tmp_path, monkeypatch):
    df = pd.DataFrame([
        _claim_row("A_res", "AMZN", "capital_allocation", "add capacity"),
        _claim_row("A_fig", "AMZN", "capital_allocation", "buy back $5 billion"),
    ])
    claims_csv = tmp_path / "claims.csv"
    df.to_csv(claims_csv, index=False)
    out = tmp_path / "subset_ids.txt"
    rc = autolabel.main(["select", "--claims", str(claims_csv), "--out", str(out)])
    assert rc == 0
    assert out.read_text().split() == ["A_res"]   # figure claim excluded


def test_not_yet_resolvable_without_evidence_does_not_reprompt():
    cands = [_cand(1)]
    decider = _FakeDecider([
        autolabel.AutoLabelDecision(selected_indices=[], verdict="not_yet_resolvable", confidence="low"),
    ])
    label = autolabel._build_label(_claim_obj(), cands, decider, "RUBRIC", labeler="gpt-5.5")
    assert decider.calls == 1
    assert label.verdict == "not_yet_resolvable"
    assert label.expected_evidence == []


def test_system_prompt_instructs_evidenced_non_occurrence_is_contradiction():
    """Lock the non-occurrence guidance into the system message against a future
    prompt rewrite: an elapsed-horizon obligatory line showing the action did not
    happen must steer the labeler to contradicted, not not_yet_resolvable."""
    msgs = autolabel.build_label_messages(_claim_obj(), [_cand(1)], "RUBRIC")
    assert msgs[0]["role"] == "system"
    system = msgs[0]["content"].lower()
    assert "non-occurrence" in system
    assert "contradicted" in system and "not_yet_resolvable" in system
