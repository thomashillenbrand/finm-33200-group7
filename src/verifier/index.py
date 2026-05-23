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
