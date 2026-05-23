"""Tests for the SearchIndex retriever."""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from verifier.corpus import SearchIndex
from verifier.index import build_index, IndexNotBuiltError, PULLED_DATA_ROOT


@pytest.fixture
def built_index(tmp_path, mock_embeddings, monkeypatch):
    """Build a real on-disk MINI index using the fixture filings + mock embeds."""
    src_dir = Path(__file__).parent / "fixtures" / "mini_filings"
    ticker_dir = tmp_path / "pulled_data" / "MINI"
    sec_dir = ticker_dir / "SEC"
    sec_dir.mkdir(parents=True)
    for f in ["sample_10K.htm", "sample_10Q.htm", "sample_8K.htm"]:
        shutil.copy(src_dir / f, sec_dir / f)
    shutil.copy(
        src_dir / "sec_filings_index.parquet",
        ticker_dir / "MINI_sec_filings_index.parquet",
    )
    import verifier.index as idx
    import verifier.corpus as corp
    monkeypatch.setattr(idx, "PULLED_DATA_ROOT", tmp_path / "pulled_data")
    monkeypatch.setattr(corp, "PULLED_DATA_ROOT", tmp_path / "pulled_data")
    # Reset the SearchIndex memoization cache so each test gets a fresh load.
    monkeypatch.setattr(SearchIndex, "_cache", {}, raising=False)
    build_index("MINI")
    return ticker_dir


def test_search_index_load_returns_instance(built_index):
    idx = SearchIndex.load("MINI")
    assert isinstance(idx, SearchIndex)


def test_search_index_load_is_memoized(built_index):
    a = SearchIndex.load("MINI")
    b = SearchIndex.load("MINI")
    assert a is b


def test_search_index_raises_if_not_built(tmp_path, monkeypatch):
    import verifier.corpus as corp
    monkeypatch.setattr(corp, "PULLED_DATA_ROOT", tmp_path / "nope")
    monkeypatch.setattr(SearchIndex, "_cache", {}, raising=False)
    with pytest.raises(IndexNotBuiltError):
        SearchIndex.load("NOPE")


from datetime import date

from schemas import EvidenceItem


def test_search_index_query_returns_evidence_items(built_index):
    idx = SearchIndex.load("MINI")
    items = idx.query("share repurchase", after_date=date(2020, 1, 1))
    assert len(items) >= 1
    for item in items:
        assert isinstance(item, EvidenceItem)
        assert item.filing_date >= date(2020, 1, 1)


def test_search_index_query_respects_after_date(built_index):
    idx = SearchIndex.load("MINI")
    # The fixture's 10-K is filed 2024-02-20; setting after_date to 2024-05-01
    # must exclude it.
    items = idx.query("share repurchase", after_date=date(2024, 5, 1))
    for item in items:
        assert item.filing_date >= date(2024, 5, 1)
    # And confirm at least one fixture filing survives that floor (the 8-K
    # filed 2024-06-14):
    assert any(item.form == "8-K" for item in items)


def test_search_index_query_respects_before_date(built_index):
    idx = SearchIndex.load("MINI")
    items = idx.query("share repurchase",
                      after_date=date(2020, 1, 1),
                      before_date=date(2024, 3, 1))
    for item in items:
        assert item.filing_date <= date(2024, 3, 1)


def test_search_index_query_respects_forms_filter(built_index):
    idx = SearchIndex.load("MINI")
    items = idx.query("share repurchase",
                      after_date=date(2020, 1, 1),
                      forms=["8-K"])
    assert items, "expected at least one 8-K hit on the fixture"
    for item in items:
        assert item.form == "8-K"


def test_search_index_query_no_results_returns_empty_list(built_index):
    idx = SearchIndex.load("MINI")
    # Future floor excludes every fixture filing.
    items = idx.query("share repurchase", after_date=date(2099, 1, 1))
    assert items == []


def test_search_index_query_embedding_is_cached_in_memory(built_index, mock_embeddings):
    """Two identical queries on the same SearchIndex instance must hit the
    embedding client only once (per-process LRU cache around _embed_query)."""
    idx = SearchIndex.load("MINI")
    idx.query("share repurchase", after_date=date(2020, 1, 1))
    first = mock_embeddings.embed_query_calls
    idx.query("share repurchase", after_date=date(2020, 1, 1))
    assert mock_embeddings.embed_query_calls == first
