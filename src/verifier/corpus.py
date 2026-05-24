"""SearchIndex — loads a per-ticker FAISS index + chunks parquet, exposes
filtered semantic search returning EvidenceItem rows.

Iter-2 replaces iter-1's `load_stub_excerpts`. There is no silent fallback to
canned excerpts; a missing index raises IndexNotBuiltError so broken state is
visible at the seam.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

import faiss
import numpy as np
import pandas as pd

from schemas import EvidenceItem
from verifier.index import (
    PULLED_DATA_ROOT,
    IndexCorruptError,
    IndexNotBuiltError,
    _make_embeddings_client,
)

# Re-export PULLED_DATA_ROOT so tests can monkeypatch one location.
__all__ = ["SearchIndex", "PULLED_DATA_ROOT"]


def _index_dir(ticker: str) -> Path:
    return PULLED_DATA_ROOT / ticker / "index"


class SearchIndex:
    """One per-ticker FAISS index + chunks dataframe, with filtered query()."""

    _cache: ClassVar[dict[str, "SearchIndex"]] = {}

    def __init__(self, ticker: str, chunks: pd.DataFrame, faiss_index) -> None:
        self.ticker = ticker
        self._chunks = chunks.reset_index(drop=True)
        self._faiss = faiss_index
        # Pre-parse filing_date column for fast filtering. Chunks parquet may
        # store this as `date`, `Timestamp`, or `object`; normalize to datetime64.
        if not pd.api.types.is_datetime64_any_dtype(self._chunks["filing_date"]):
            self._chunks["filing_date"] = pd.to_datetime(self._chunks["filing_date"])

    @classmethod
    def load(cls, ticker: str) -> "SearchIndex":
        if ticker in cls._cache:
            return cls._cache[ticker]
        d = _index_dir(ticker)
        chunks_path = d / "chunks.parquet"
        faiss_path = d / "faiss.index"
        if not chunks_path.exists() or not faiss_path.exists():
            raise IndexNotBuiltError(
                f"No index for {ticker} at {d}. "
                f"Run `python -m verifier.index {ticker}` first."
            )
        chunks = pd.read_parquet(chunks_path)
        idx = faiss.read_index(str(faiss_path))
        if idx.ntotal != len(chunks):
            raise IndexCorruptError(
                f"faiss/parquet length mismatch for {ticker}: "
                f"FAISS={idx.ntotal}, parquet={len(chunks)}. Rebuild with --refresh."
            )
        inst = cls(ticker, chunks, idx)
        cls._cache[ticker] = inst
        return inst

    @lru_cache(maxsize=512)
    def _embed_query_cached(self, text: str) -> tuple[float, ...]:
        """Per-instance LRU around the embedding call.

        Returns a tuple (not a list) because `lru_cache` requires hashable
        returns AND its hashing of `(self, text)` makes the cache instance-
        scoped — different SearchIndex instances don't share keys. That's the
        right scope: a query embedding is bound to the corpus it was issued
        against, and corpora don't share namespaces.
        """
        client = _make_embeddings_client()
        return tuple(client.embed_query(text))

    def _embed_query(self, text: str) -> list[float]:
        return list(self._embed_query_cached(text))

    def query(
        self,
        text: str,
        *,
        after_date: date,
        before_date: date | None = None,
        forms: list[str] | None = None,
        k: int = 8,
    ) -> list[EvidenceItem]:
        """Filtered semantic search. Returns up to `k` EvidenceItem rows.

        Filters are applied as a whitelist over chunks.parquet; FAISS is
        searched with `k * 5` over-fetch so that post-filter has enough hits
        in the whitelist to reach `k`.
        """
        # 1. Build the whitelist of row indices that pass the metadata filters.
        mask = self._chunks["filing_date"].dt.date >= after_date
        if before_date is not None:
            mask &= self._chunks["filing_date"].dt.date <= before_date
        if forms:
            mask &= self._chunks["form"].isin(forms)
        whitelist = np.flatnonzero(mask.to_numpy())
        if whitelist.size == 0:
            return []

        # 2. Embed the query (per-instance LRU keeps identical queries free).
        q = np.array(self._embed_query(text), dtype=np.float32)
        n = np.linalg.norm(q)
        if n:
            q = q / n

        # 3. Oversample, then post-filter by whitelist.
        k_inner = min(k * 5, self._faiss.ntotal)
        scores, ids = self._faiss.search(q.reshape(1, -1), k_inner)
        scores, ids = scores[0], ids[0]

        whitelist_set = set(whitelist.tolist())
        hits: list[tuple[int, float]] = [
            (int(row_id), float(score))
            for row_id, score in zip(ids, scores)
            if row_id != -1 and int(row_id) in whitelist_set
        ]
        hits = hits[:k]

        # 4. Build EvidenceItem rows.
        items: list[EvidenceItem] = []
        for row_id, score in hits:
            row = self._chunks.iloc[row_id]
            filing_date_val = row["filing_date"]
            if hasattr(filing_date_val, "date"):
                filing_date_val = filing_date_val.date()
            items.append(EvidenceItem(
                source=_format_source(row["form"], filing_date_val, row["accession_no"]),
                excerpt=row["text"],
                accession_no=row["accession_no"],
                form=row["form"],
                filing_date=filing_date_val,
                chunk_id=row["chunk_id"],
                # Cosine similarity is in [-1, 1] for unit vectors; remap to
                # [0, 1] for the EvidenceItem schema's ge=0,le=1 constraint.
                score=max(0.0, min(1.0, (score + 1.0) / 2.0)),
                edgar_url=_edgar_url(self.ticker, row["form"]),
            ))
        return items


def _format_source(form: str, filing_date: date, accession_no: str) -> str:
    return f"{form} filed {filing_date.isoformat()}, accession {accession_no}"


def _edgar_url(ticker: str, form: str) -> str | None:
    """Lightweight EDGAR deep-link best-effort.

    We don't have the CIK on hand at query time (the chunks parquet doesn't
    carry it). For iter-2 we return a `browse-edgar` URL keyed by ticker and
    form; iter-3 can plumb the CIK through from the SEC filings index if
    stronger guarantees are needed.
    """
    return (
        f"https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={ticker}&type={form}"
    )
