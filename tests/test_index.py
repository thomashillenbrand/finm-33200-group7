"""Tests for the fixed-token chunker in verifier.index."""

import pytest

from verifier.index import chunk_text, Chunk


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

from verifier.index import chunk_id, IndexNotBuiltError, IndexCorruptError


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
