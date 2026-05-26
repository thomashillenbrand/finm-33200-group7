"""Tests for the verdict-agent discipline pieces (coverage, prompt, evidence
net, parser repair). All offline — the parser LLM is injected as a fake."""
from datetime import date

from schemas import EvidenceBundle, EvidenceItem, Verdict
from verifier import agent as A


def test_horizon_within_coverage():
    assert A._horizon_within_coverage(date(2024, 12, 31), date(2025, 2, 20)) is True
    assert A._horizon_within_coverage(date(2026, 12, 31), date(2025, 2, 20)) is False
    assert A._horizon_within_coverage(None, date(2025, 2, 20)) is False
    assert A._horizon_within_coverage(date(2024, 12, 31), None) is False


def test_verdict_prompt_has_grounding_discipline():
    p = A.VERDICT_SYSTEM_PROMPT.lower()
    assert "not_yet_resolvable" in p
    assert "earlier than the stated horizon" in p   # early fulfillment counts
    assert "do not assume" in p                       # no future-filing inference
    assert "search_filings" in p


def test_verdict_prompt_does_not_reference_the_gold_rubric():
    assert "labeling_rubric" not in A.VERDICT_SYSTEM_PROMPT


def _item():
    return EvidenceItem(source="10-K filed 2024-02-20", excerpt="...repurchases...",
                        accession_no="acc-1", form="10-K", filing_date=date(2024, 2, 20),
                        chunk_id="c1", score=0.9)


def test_evidence_net_downgrades_decisive_without_citations():
    v = Verdict(items=[], verdict="verified", reasoning="r")
    assert A._enforce_evidence_grounding(v, "verdict").verdict == "not_yet_resolvable"
    c = Verdict(items=[], verdict="contradicted", reasoning="r")
    assert A._enforce_evidence_grounding(c, "verdict").verdict == "not_yet_resolvable"


def test_evidence_net_keeps_decisive_with_citations():
    v = Verdict(items=[_item()], verdict="verified", reasoning="r")
    assert A._enforce_evidence_grounding(v, "verdict").verdict == "verified"


def test_evidence_net_keeps_not_yet_resolvable_and_evidence_mode():
    v = Verdict(items=[], verdict="not_yet_resolvable", reasoning="r")
    assert A._enforce_evidence_grounding(v, "verdict").verdict == "not_yet_resolvable"
    b = EvidenceBundle(items=[])
    assert A._enforce_evidence_grounding(b, "evidence") is b


class _FlakyExtractor:
    """Returns/raises a scripted sequence across .invoke() calls."""
    def __init__(self, results):
        self._results = list(results)
        self.i = 0
    def invoke(self, _instruction):
        r = self._results[self.i]
        self.i += 1
        if isinstance(r, Exception):
            raise r
        return r


def test_extract_structured_repairs_after_one_failure():
    good = Verdict(items=[], verdict="not_yet_resolvable", reasoning="ok")
    flaky = _FlakyExtractor([ValueError("no parsed field"), good])
    out = A._extract_structured("agent text", "verdict", extractor_factory=lambda: flaky)
    assert out is good and flaky.i == 2


def test_extract_structured_falls_back_when_always_failing():
    flaky = _FlakyExtractor([ValueError("x"), ValueError("y")])
    out = A._extract_structured("agent text", "verdict", extractor_factory=lambda: flaky)
    assert out.verdict == "not_yet_resolvable" and out.items == []


def test_extract_structured_fallback_is_empty_bundle_in_evidence_mode():
    flaky = _FlakyExtractor([ValueError("x"), ValueError("y")])
    out = A._extract_structured("agent text", "evidence", extractor_factory=lambda: flaky)
    assert isinstance(out, EvidenceBundle) and out.items == []


def test_verdict_prompt_encourages_a_second_search_before_abstaining():
    assert "at least one more search" in A.VERDICT_SYSTEM_PROMPT.lower()
