"""Tests for the fixed-token chunker in verifier.index."""

import pytest

from verifier.index import Chunk, chunk_text


def _join_with_spaces(words: list[str]) -> str:
    return " ".join(words)


def test_chunker_short_text_emits_one_chunk():
    text = "this is a short text."
    chunks = chunk_text(text, window_tokens=600, overlap_tokens=100)
    assert len(chunks) == 1
    assert chunks[0].text == text
    assert chunks[0].char_start == 0
    assert chunks[0].char_end == len(text)


def test_chunker_emits_multiple_windows_for_long_text():
    # 5000 short tokens -> definitely multiple 600-token windows
    text = _join_with_spaces(["token"] * 5000)
    chunks = chunk_text(text, window_tokens=600, overlap_tokens=100)
    assert len(chunks) >= 8  # roughly 5000 / (600 - 100)
    # adjacent chunks should overlap by ~100 tokens (i.e. char_start of next < char_end of prev)
    for i in range(1, len(chunks)):
        assert chunks[i].char_start < chunks[i - 1].char_end


def test_chunker_chunks_are_contiguous_in_text():
    """Every chunk's text must be exactly text[char_start:char_end]."""
    text = _join_with_spaces(["lorem", "ipsum", "dolor"] * 1000)
    chunks = chunk_text(text, window_tokens=600, overlap_tokens=100)
    for c in chunks:
        assert c.text == text[c.char_start:c.char_end]


def test_chunker_returns_chunk_dataclass_with_expected_fields():
    text = "hello world."
    [chunk] = chunk_text(text, window_tokens=600, overlap_tokens=100)
    # field presence:
    assert hasattr(chunk, "text")
    assert hasattr(chunk, "char_start")
    assert hasattr(chunk, "char_end")


def test_chunker_rejects_overlap_geq_window():
    with pytest.raises(ValueError):
        chunk_text("x", window_tokens=100, overlap_tokens=100)
    with pytest.raises(ValueError):
        chunk_text("x", window_tokens=100, overlap_tokens=150)


def test_chunker_is_subquadratic_on_realistic_filing_size():
    """Regression guard: a SEC 10-K can be ~50k tokens. The original O(n^2)
    offset-construction loop made TSLA's index build run for >14 minutes on
    CPU. The current O(n) implementation must finish a 20k-token chunk in well
    under a second."""
    import time

    text = "lorem ipsum dolor sit amet " * 4000   # ~20k tokens
    t0 = time.time()
    chunks = chunk_text(text, window_tokens=600, overlap_tokens=100)
    elapsed = time.time() - t0
    assert len(chunks) > 30
    assert elapsed < 1.0, f"chunk_text took {elapsed:.2f}s — likely O(n^2) regression"


# --- HTML extraction -------------------------------------------------------

from pathlib import Path

from verifier.index import extract_text_from_html

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "mini_filings"


def test_extract_text_from_html_strips_tags():
    html = b"<html><body><p>Hello <b>world</b>.</p></body></html>"
    text = extract_text_from_html(html)
    assert "<p>" not in text
    assert "<b>" not in text
    assert "Hello" in text
    assert "world" in text


def test_extract_text_from_html_preserves_paragraph_breaks():
    html = b"<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>"
    text = extract_text_from_html(html)
    # Paragraph boundaries should produce a newline, not a run-together string.
    assert "First paragraph." in text
    assert "Second paragraph." in text
    # There should be at least one newline between the two:
    first_end = text.index("First paragraph.") + len("First paragraph.")
    second_start = text.index("Second paragraph.")
    assert "\n" in text[first_end:second_start]


def test_extract_text_from_real_fixture():
    """Round-trips one of the mini fixture filings."""
    html = (FIXTURE_DIR / "sample_10K.htm").read_bytes()
    text = extract_text_from_html(html)
    assert "repurchased 12.5 million shares" in text
    assert "<p>" not in text


# --- chunk_id / exceptions -------------------------------------------------

from verifier.index import IndexCorruptError, IndexNotBuiltError, chunk_id


def test_chunk_id_is_deterministic():
    a = chunk_id("0001018724-24-000010", 0, 1234)
    b = chunk_id("0001018724-24-000010", 0, 1234)
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 16


def test_chunk_id_changes_with_inputs():
    base = chunk_id("0001018724-24-000010", 0, 1234)
    assert chunk_id("0001018724-24-000011", 0, 1234) != base
    assert chunk_id("0001018724-24-000010", 1, 1234) != base
    assert chunk_id("0001018724-24-000010", 0, 1235) != base


def test_custom_exceptions_are_distinct_value_subclasses():
    # Distinct types so callers can `except IndexNotBuiltError` without
    # accidentally also catching IndexCorruptError.
    assert issubclass(IndexNotBuiltError, Exception)
    assert issubclass(IndexCorruptError, Exception)
    assert IndexNotBuiltError is not IndexCorruptError


# --- build_index -----------------------------------------------------------

import shutil
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
import pytest

from verifier.index import build_index


@pytest.fixture
def ticker_root(tmp_path):
    """Set up a tmp `pulled_data/MINI/` layout from the fixture filings."""
    src_dir = Path(__file__).parent / "fixtures" / "mini_filings"
    ticker_dir = tmp_path / "pulled_data" / "MINI"
    sec_dir = ticker_dir / "SEC"
    sec_dir.mkdir(parents=True)
    # Copy HTMLs into SEC/.
    for f in ["sample_10K.htm", "sample_10Q.htm", "sample_8K.htm"]:
        shutil.copy(src_dir / f, sec_dir / f)
    # Copy the index parquet to where build_index expects it:
    #   pulled_data/<TICKER>/SEC/<TICKER>_sec_filings_index.parquet
    shutil.copy(
        src_dir / "sec_filings_index.parquet",
        sec_dir / "MINI_sec_filings_index.parquet",
    )
    # Patch the package-level PULLED_DATA_ROOT to our tmp.
    import verifier.index as idx
    old = idx.PULLED_DATA_ROOT
    idx.PULLED_DATA_ROOT = tmp_path / "pulled_data"
    yield ticker_dir
    idx.PULLED_DATA_ROOT = old


def test_build_index_writes_chunks_parquet_and_faiss(ticker_root, mock_embeddings):
    build_index("MINI")
    chunks_path = ticker_root / "index" / "chunks.parquet"
    faiss_path = ticker_root / "index" / "faiss.index"
    assert chunks_path.exists()
    assert faiss_path.exists()
    df = pd.read_parquet(chunks_path)
    # Every fixture filing contributes ≥1 chunk; expect ≥3 rows total.
    assert len(df) >= 3
    # Required columns:
    for col in ("chunk_id", "accession_no", "form", "filing_date",
                "local_path", "char_start", "char_end", "text"):
        assert col in df.columns


def test_build_index_is_idempotent(ticker_root, mock_embeddings):
    """Second run on unchanged corpus → zero new embedding calls."""
    build_index("MINI")
    first = mock_embeddings.embed_documents_calls
    assert first >= 1
    build_index("MINI")
    assert mock_embeddings.embed_documents_calls == first


def test_build_index_refresh_rebuilds_from_scratch(ticker_root, mock_embeddings):
    build_index("MINI")
    first_calls = mock_embeddings.embed_documents_calls
    build_index("MINI", refresh=True)
    # Refresh wipes; we should see at least one new embed batch.
    assert mock_embeddings.embed_documents_calls > first_calls


def test_build_index_raises_if_no_filings_index(tmp_path, mock_embeddings, monkeypatch):
    import verifier.index as idx
    monkeypatch.setattr(idx, "PULLED_DATA_ROOT", tmp_path / "pulled_data")
    with pytest.raises(FileNotFoundError):
        build_index("NOPE")


def test_build_index_handles_all_non_html_corpus(tmp_path, mock_embeddings, monkeypatch):
    """Issue 1 regression: a corpus with only non-HTML primary docs must not crash.
    `build_index` should skip writing files (no usable chunks) and log clearly."""
    import verifier.index as idx
    ticker_dir = tmp_path / "pulled_data" / "NOHTML"
    ticker_dir.mkdir(parents=True)
    # SEC filings index points at a .pdf only — _chunk_filing returns [] for it.
    rows = [{
        "accessionNumber": "0000000000-99-000001",
        "filingDate": "2024-01-15",
        "reportDate": "2024-01-15",
        "form": "8-K",
        "primaryDocument": "doc.pdf",
        "primaryDocDescription": "PDF only",
        "localPath": "doc.pdf",
    }]
    # The .pdf doesn't need real content — _chunk_filing skips non-html extensions
    # before reading the file. (Touch it anyway to be safe.)
    (ticker_dir / "SEC").mkdir()
    (ticker_dir / "SEC" / "doc.pdf").write_bytes(b"")
    pd.DataFrame(rows).to_parquet(ticker_dir / "SEC" / "NOHTML_sec_filings_index.parquet")
    monkeypatch.setattr(idx, "PULLED_DATA_ROOT", tmp_path / "pulled_data")
    # Must not raise. Must not write index/.
    build_index("NOHTML")
    assert not (ticker_dir / "index").exists()


def test_build_index_detects_faiss_parquet_length_mismatch(ticker_root, mock_embeddings):
    """Issue 2 regression: chunks.parquet and faiss.index out of sync must raise
    IndexCorruptError, not a cryptic pandas ValueError."""
    build_index("MINI")
    faiss_path = ticker_root / "index" / "faiss.index"
    bogus = faiss.IndexFlatIP(384)  # mock embed dim
    bogus.add(np.random.rand(99, 384).astype(np.float32))
    faiss.write_index(bogus, str(faiss_path))
    with pytest.raises(IndexCorruptError):
        build_index("MINI")


def test_build_index_drops_stale_chunks_from_removed_filings(ticker_root, mock_embeddings):
    """Issue 3 regression: a chunk that's no longer in the SEC filings index must
    not survive a subsequent build."""
    import verifier.index as idx
    build_index("MINI")
    first_df = pd.read_parquet(ticker_root / "index" / "chunks.parquet")
    accessions_before = set(first_df["accession_no"])
    assert len(accessions_before) == 3  # 10-K, 10-Q, 8-K all present

    # Rewrite the SEC index parquet to drop the 8-K.
    sec_index_path = ticker_root / "SEC" / "MINI_sec_filings_index.parquet"
    df = pd.read_parquet(sec_index_path)
    df = df[df["form"] != "8-K"].reset_index(drop=True)
    df.to_parquet(sec_index_path)

    build_index("MINI")
    second_df = pd.read_parquet(ticker_root / "index" / "chunks.parquet")
    accessions_after = set(second_df["accession_no"])
    assert "0000000000-24-000015" not in accessions_after  # 8-K dropped
    assert len(accessions_after) == 2  # 10-K + 10-Q remain
