"""Tests for the pure scoring functions in verifier.eval.

The CLI (which runs the agent live) is exercised separately; these cover the
metric math with constructed objects so they stay offline.
"""

from datetime import date, datetime

import pytest

from schemas import EvidenceBundle, EvidenceItem, Verdict
from verifier.eval import PerClaimResult, aggregate, score_retrieval, score_verdict
from verifier.gold import GoldEvidence, GoldLabel


def _gold(claim_id="c1", verdict="verified", accessions=("acc-1", "acc-2")) -> GoldLabel:
    return GoldLabel(
        claim_id=claim_id,
        ticker="TSLA",
        labeler="test",
        labeled_at=datetime(2026, 5, 23),
        expected_evidence=[
            GoldEvidence(accession_no=a, form="10-Q", filing_date=date(2024, 1, 1),
                         quote=f"q-{a}")
            for a in accessions
        ],
        verdict=verdict,
        confidence="high",
    )


def _bundle(accessions) -> EvidenceBundle:
    return EvidenceBundle(items=[
        EvidenceItem(source=f"src-{a}", excerpt=f"e-{a}", accession_no=a,
                     form="10-Q", filing_date=date(2024, 1, 1),
                     chunk_id=f"chunk-{a}", score=0.5)
        for a in accessions
    ])


def test_recall_at_k_exact_hit():
    result = score_retrieval(_gold(accessions=("acc-1", "acc-2")),
                             _bundle(["acc-1", "acc-2", "acc-3"]), k=3)
    assert result.recall_at_k == 1.0
    assert result.precision == 2 / 3


def test_recall_at_k_partial_hit():
    result = score_retrieval(_gold(accessions=("acc-1", "acc-2", "acc-3")),
                             _bundle(["acc-1", "acc-4"]), k=2)
    assert result.recall_at_k == 1 / 3
    assert result.precision == 0.5


def test_k_truncates_retrieved_before_scoring():
    # Gold wants acc-3; agent retrieves it only at rank 3, but k=2 cuts it off.
    result = score_retrieval(_gold(accessions=("acc-3",)),
                             _bundle(["acc-1", "acc-2", "acc-3"]), k=2)
    assert result.recall_at_k == 0.0


def test_recall_when_gold_has_no_evidence():
    """not_yet_resolvable claims have empty expected_evidence; recall is None."""
    result = score_retrieval(_gold(verdict="not_yet_resolvable", accessions=()),
                             _bundle([]), k=3)
    assert result.recall_at_k is None
    assert result.precision is None


def test_verdict_exact_match():
    verdict = Verdict(items=[], verdict="verified", reasoning="r")
    assert score_verdict(_gold(verdict="verified"), verdict) is True


def test_verdict_mismatch():
    verdict = Verdict(items=[], verdict="partially_verified", reasoning="r")
    assert score_verdict(_gold(verdict="verified"), verdict) is False


def test_aggregate_summary_stats():
    results = [
        PerClaimResult("c1", recall_at_k=1.0, precision=0.5, verdict_match=True),
        PerClaimResult("c2", recall_at_k=0.5, precision=0.25, verdict_match=False),
        PerClaimResult("c3", recall_at_k=None, precision=None, verdict_match=True),
    ]
    summary = aggregate(results)
    assert summary["mean_recall_at_k"] == pytest.approx(0.75)
    assert summary["mean_precision"] == pytest.approx(0.375)
    assert summary["verdict_accuracy"] == pytest.approx(2 / 3)
    assert summary["n_claims"] == 3
    assert summary["n_recall_scored"] == 2


def test_aggregate_empty_results():
    summary = aggregate([])
    assert summary["n_claims"] == 0
    assert summary["mean_recall_at_k"] is None
    assert summary["verdict_accuracy"] is None
