"""Shared pytest fixtures.

The `mock_embeddings` fixture replaces the real OpenAI embeddings client with
a deterministic numpy-based stand-in for every test that depends on it.
Keeps offline tests fast and free. Live tests opt in by skipping this
fixture (or by running with `-m live` and a real OPENAI_API_KEY).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest


class _MockEmbeddings:
    """Deterministic embeddings: hash → 384-dim float32 unit vector.

    Two distinct strings map to two different vectors. Identical strings map
    to identical vectors (so caching tests are meaningful).
    """

    dim = 384

    def __init__(self) -> None:
        self.embed_documents_calls = 0
        self.embed_query_calls = 0

    def _vec(self, s: str) -> np.ndarray:
        h = hashlib.sha256(s.encode("utf-8")).digest()
        # Stretch 32 hash bytes into `dim` floats via a repeating cycle.
        reps = (self.dim // 32) + 1
        raw = np.frombuffer((h * reps)[: self.dim * 4], dtype=np.uint32)
        v = raw.astype(np.float32) / np.float32(np.iinfo(np.uint32).max)
        v -= 0.5
        norm = np.linalg.norm(v)
        return v / norm if norm else v

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embed_documents_calls += 1
        return [self._vec(t).tolist() for t in texts]

    def embed_query(self, text: str) -> list[float]:
        self.embed_query_calls += 1
        return self._vec(text).tolist()


@pytest.fixture
def mock_embeddings(monkeypatch):
    """Replace the OpenAI embeddings factory with a deterministic mock.

    `_make_embeddings_client` is referenced in two places — `verifier.index`
    (where it's defined, used by build_index) and `verifier.corpus` (which
    re-imports it for SearchIndex). Patching both bindings is necessary
    because `from … import` binds a separate reference in each module.
    """
    from verifier import index

    mock = _MockEmbeddings()
    monkeypatch.setattr(index, "_make_embeddings_client", lambda: mock)
    try:
        from verifier import corpus
        monkeypatch.setattr(corpus, "_make_embeddings_client", lambda: mock,
                            raising=False)
    except ImportError:
        pass
    return mock


@pytest.fixture
def built_index(tmp_path, mock_embeddings, monkeypatch):
    """Build a real on-disk MINI index using the fixture filings + mock embeds.

    Shared by tests in test_corpus.py and test_tools.py.
    """
    src_dir = Path(__file__).parent / "fixtures" / "mini_filings"
    ticker_dir = tmp_path / "pulled_data" / "MINI"
    sec_dir = ticker_dir / "SEC"
    sec_dir.mkdir(parents=True)
    for f in ["sample_10K.htm", "sample_10Q.htm", "sample_8K.htm"]:
        shutil.copy(src_dir / f, sec_dir / f)
    shutil.copy(
        src_dir / "sec_filings_index.parquet",
        sec_dir / "MINI_sec_filings_index.parquet",
    )
    import verifier.index as idx
    import verifier.corpus as corp
    from verifier.corpus import SearchIndex
    monkeypatch.setattr(idx, "PULLED_DATA_ROOT", tmp_path / "pulled_data")
    monkeypatch.setattr(corp, "PULLED_DATA_ROOT", tmp_path / "pulled_data")
    monkeypatch.setattr(SearchIndex, "_cache", {}, raising=False)
    from verifier.index import build_index
    build_index("MINI")
    return ticker_dir
