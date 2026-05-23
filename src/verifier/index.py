"""Offline indexer: parses SEC HTML, chunks it, embeds, and writes
chunks.parquet + faiss.index per ticker.

Public surface:
  chunk_text(text, window_tokens=600, overlap_tokens=100) -> list[Chunk]
  build_index(ticker, *, refresh=False) -> None
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


class IndexNotBuiltError(Exception):
    """Raised when SearchIndex.load is called on a ticker with no index/."""


class IndexCorruptError(Exception):
    """Raised when chunks.parquet and faiss.index are out of sync or unreadable."""


def chunk_id(accession_no: str, char_start: int, char_end: int) -> str:
    """Deterministic 16-char hash. Identical (accession, span) → identical id.

    Stable across reruns so the incremental indexer can diff against the
    existing chunks.parquet by id rather than re-embedding.
    """
    digest = hashlib.sha1(
        f"{accession_no}:{char_start}-{char_end}".encode("utf-8")
    ).hexdigest()
    return digest[:16]

import tiktoken
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Chunk:
    """One fixed-token text window with byte-spans into the source text."""
    text: str
    char_start: int
    char_end: int


_MULTI_WHITESPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def extract_text_from_html(html: bytes) -> str:
    """Convert SEC primary-doc HTML to plain text.

    Naive — we do not parse 10-K item structure. We get tags stripped,
    paragraph boundaries preserved as newlines, and whitespace squeezed. That
    is enough for capital-allocation prose retrieval; section-aware parsing is
    deferred to iter 3 (see spec Out of Scope).
    """
    soup = BeautifulSoup(html, "lxml")
    # Drop scripts/styles up front; they're noise.
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Whitespace normalize: collapse runs of spaces/tabs, then collapse 3+ newlines.
    text = _MULTI_WHITESPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


_ENCODER = tiktoken.get_encoding("cl100k_base")


def chunk_text(
    text: str,
    *,
    window_tokens: int = 600,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    """Slide a fixed-token window over `text`, returning Chunks with char spans.

    `cl100k_base` is the GPT-4 / text-embedding-3-* tokenizer; we use it both
    for window sizing (the embedding model's true cost driver) and to derive
    char spans (via per-token offset reconstruction).

    Raises ValueError if `overlap_tokens >= window_tokens` (would loop forever).
    """
    if overlap_tokens >= window_tokens:
        raise ValueError(
            f"overlap_tokens ({overlap_tokens}) must be < window_tokens ({window_tokens})"
        )
    if not text:
        return []

    # token-id list + char offsets, one entry per token
    token_ids = _ENCODER.encode(text)
    if len(token_ids) <= window_tokens:
        return [Chunk(text=text, char_start=0, char_end=len(text))]

    # Build per-token char-start offsets by decoding incrementally. We accept
    # the O(n) cost — corpora are small per ticker, and tiktoken is fast.
    offsets: list[int] = [0]
    cursor = 0
    for i in range(1, len(token_ids)):
        cursor = len(_ENCODER.decode(token_ids[:i]))
        offsets.append(cursor)
    # final offset = full string length
    offsets.append(len(text))

    chunks: list[Chunk] = []
    step = window_tokens - overlap_tokens
    start = 0
    while start < len(token_ids):
        end = min(start + window_tokens, len(token_ids))
        char_start = offsets[start]
        char_end = offsets[end]  # offsets[len] = len(text)
        chunks.append(Chunk(text=text[char_start:char_end],
                            char_start=char_start, char_end=char_end))
        if end == len(token_ids):
            break
        start += step
    return chunks


import os
import shutil
import tempfile
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from langchain_openai import OpenAIEmbeddings

# Repo-relative default; tests monkeypatch this.
PULLED_DATA_ROOT = Path("pulled_data")

EMBED_MODEL = "text-embedding-3-small"


def _make_embeddings_client():
    """Embedding client factory — patchable in tests."""
    return OpenAIEmbeddings(model=EMBED_MODEL)


def _ticker_dir(ticker: str) -> Path:
    return PULLED_DATA_ROOT / ticker


def _sec_index_path(ticker: str) -> Path:
    return _ticker_dir(ticker) / f"{ticker}_sec_filings_index.parquet"


def _index_dir(ticker: str) -> Path:
    return _ticker_dir(ticker) / "index"


def _atomic_write(target: Path, write_fn) -> None:
    """Write via a temp file in the same directory, then atomic rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".tmp")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        write_fn(tmp)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_existing_chunks(ticker: str) -> pd.DataFrame:
    p = _index_dir(ticker) / "chunks.parquet"
    if not p.exists():
        return pd.DataFrame(columns=[
            "chunk_id", "accession_no", "form", "filing_date",
            "local_path", "char_start", "char_end", "text",
        ])
    return pd.read_parquet(p)


def _chunk_filing(row: pd.Series, sec_root: Path) -> list[dict]:
    """Read one filing's HTML, return a list of chunk-row dicts (no embeddings yet)."""
    html_path = sec_root / row["localPath"]
    if not str(html_path).lower().endswith((".htm", ".html")):
        return []  # Non-HTML primary docs are logged-and-skipped at the call site.
    html = html_path.read_bytes()
    text = extract_text_from_html(html)
    chunks = chunk_text(text, window_tokens=600, overlap_tokens=100)
    return [
        {
            "chunk_id": chunk_id(row["accessionNumber"], c.char_start, c.char_end),
            "accession_no": row["accessionNumber"],
            "form": row["form"],
            "filing_date": pd.to_datetime(row["filingDate"]).date(),
            "local_path": row["localPath"],
            "char_start": c.char_start,
            "char_end": c.char_end,
            "text": c.text,
        }
        for c in chunks
    ]


def build_index(ticker: str, *, refresh: bool = False) -> None:
    """Build (or incrementally update) the FAISS index for a single ticker.

    Inputs (produced by data_pull.py):
      pulled_data/<TICKER>/<TICKER>_sec_filings_index.parquet
      pulled_data/<TICKER>/SEC/<form>/<filename>.htm

    Outputs:
      pulled_data/<TICKER>/index/chunks.parquet
      pulled_data/<TICKER>/index/faiss.index

    Atomic writes via .tmp + rename; crash mid-build leaves the prior pair
    intact. If `refresh` is True, the index/ dir is wiped first.
    """
    sec_index_path = _sec_index_path(ticker)
    if not sec_index_path.exists():
        raise FileNotFoundError(
            f"No SEC filings index for {ticker} at {sec_index_path}. "
            f"Run `python -m data_pull {ticker}` first."
        )
    sec_root = _ticker_dir(ticker) / "SEC"
    index_dir = _index_dir(ticker)
    if refresh and index_dir.exists():
        shutil.rmtree(index_dir)

    filings = pd.read_parquet(sec_index_path)
    filings = filings[filings["localPath"].astype(bool)].reset_index(drop=True)

    skipped_non_html = 0
    all_rows: list[dict] = []
    for _, row in filings.iterrows():
        rows = _chunk_filing(row, sec_root)
        if not rows:
            skipped_non_html += 1
        all_rows.extend(rows)
    if skipped_non_html:
        print(f"[index] skipped {skipped_non_html} non-HTML primary docs")

    new_df = pd.DataFrame(all_rows)
    existing = _load_existing_chunks(ticker)

    # Load existing vectors (if any) and validate the faiss/parquet pair is in sync.
    existing_with_vecs = existing.copy()
    existing_faiss = index_dir / "faiss.index"
    if not existing.empty and existing_faiss.exists():
        faiss_idx = faiss.read_index(str(existing_faiss))
        if faiss_idx.ntotal != len(existing):
            raise IndexCorruptError(
                f"chunks.parquet/{ticker} row count ({len(existing)}) does not match "
                f"faiss.index vector count ({faiss_idx.ntotal}). Rebuild with --refresh."
            )
        vecs = np.zeros((faiss_idx.ntotal, faiss_idx.d), dtype=np.float32)
        faiss_idx.reconstruct_n(0, faiss_idx.ntotal, vecs)
        existing_with_vecs["_vec"] = list(vecs)
    elif not existing.empty:
        raise IndexCorruptError(
            f"chunks.parquet present but faiss.index missing for {ticker}; "
            f"rerun with --refresh."
        )

    # Drop any existing chunks whose chunk_id is no longer present in new_df
    # (e.g. a filing was removed from the SEC index). Keeping them would let
    # the index grow monotonically with stale references.
    new_ids: set[str] = set(new_df["chunk_id"]) if not new_df.empty else set()
    if not existing_with_vecs.empty:
        before = len(existing_with_vecs)
        existing_with_vecs = existing_with_vecs[
            existing_with_vecs["chunk_id"].isin(new_ids)
        ].reset_index(drop=True)
        dropped = before - len(existing_with_vecs)
        if dropped:
            print(f"[index] {ticker}: dropped {dropped} stale chunks no longer in SEC index")

    # Embed only the chunks that aren't already in the (filtered) existing set.
    surviving_existing_ids: set[str] = (
        set(existing_with_vecs["chunk_id"]) if not existing_with_vecs.empty else set()
    )
    if new_df.empty:
        to_embed = new_df
    else:
        to_embed = new_df[~new_df["chunk_id"].isin(surviving_existing_ids)].reset_index(drop=True)

    client = _make_embeddings_client()
    if not to_embed.empty:
        vectors = np.array(client.embed_documents(to_embed["text"].tolist()),
                           dtype=np.float32)
        # Normalize for cosine similarity via IndexFlatIP.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors = vectors / norms
        new_embedded = to_embed.copy()
        new_embedded["_vec"] = list(vectors)
    else:
        new_embedded = to_embed.copy()
        new_embedded["_vec"] = []

    combined = pd.concat([existing_with_vecs, new_embedded], ignore_index=True)

    # If the corpus produced no chunks (e.g. all primary docs are non-HTML and
    # there's no prior index), skip writing entirely. Subsequent SearchIndex.load
    # will raise IndexNotBuiltError, which is the correct semantics — no usable
    # data is a load-time problem, not a silent-empty-index problem.
    if combined.empty:
        print(f"[index] {ticker}: no chunks produced. Skipping write (no HTML filings indexed).")
        return

    # Drop the vector column before writing parquet:
    out_df = combined.drop(columns=["_vec"])
    matrix = np.array(combined["_vec"].tolist(), dtype=np.float32)

    chunks_target = index_dir / "chunks.parquet"
    faiss_target = index_dir / "faiss.index"
    _atomic_write(chunks_target, lambda tmp: out_df.to_parquet(tmp, index=False))

    def _write_faiss(tmp: Path) -> None:
        new_idx = faiss.IndexFlatIP(matrix.shape[1])
        new_idx.add(matrix)
        faiss.write_index(new_idx, str(tmp))

    _atomic_write(faiss_target, _write_faiss)
    print(f"[index] {ticker}: {len(out_df)} chunks total, {len(to_embed)} newly embedded")
