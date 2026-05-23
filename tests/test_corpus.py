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
