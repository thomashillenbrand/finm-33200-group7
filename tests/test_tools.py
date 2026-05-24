"""Tests for the per-claim search_filings closure + stringify helper."""

import inspect
from datetime import date

import pytest

from schemas import EvidenceItem
from verifier.tools import (
    _stringify_evidence,
    bind_search_filings,
)


def _ev(form="10-Q", filing_date=date(2024, 4, 30), score=0.7,
        accession_no="0001018724-24-000010", text="Repurchased $475M ..."):
    return EvidenceItem(
        source=f"{form} filed {filing_date.isoformat()}, accession {accession_no}",
        excerpt=text,
        accession_no=accession_no,
        form=form,
        filing_date=filing_date,
        chunk_id="abc123",
        score=score,
    )


# --- _stringify_evidence ---------------------------------------------------

def test_stringify_evidence_includes_bracketed_header_per_item():
    s = _stringify_evidence([_ev()])
    assert "[10-Q filed 2024-04-30, accession 0001018724-24-000010]" in s
    assert "Repurchased $475M" in s


def test_stringify_evidence_separates_items_with_divider():
    s = _stringify_evidence([_ev(text="first"), _ev(text="second")])
    assert "first" in s
    assert "second" in s
    assert "---" in s


def test_stringify_evidence_empty_list_message():
    s = _stringify_evidence([])
    assert s == "[no matching filings]"


# --- bind_search_filings ---------------------------------------------------

def test_bind_search_filings_hides_ticker_and_after_date_from_llm(built_index):
    """LLM-visible signature must omit `ticker` and `after_date` — closing
    them over is the load-bearing no-time-leakage guarantee."""
    tool = bind_search_filings("MINI", date(2024, 1, 1))
    # Inspect the underlying function's parameters (handle both bare-function
    # and langchain-Tool wrappers):
    fn = getattr(tool, "func", tool)
    params = inspect.signature(fn).parameters
    assert "query" in params
    assert "ticker" not in params
    assert "after_date" not in params


def test_bind_search_filings_callable_returns_string(built_index):
    tool = bind_search_filings("MINI", date(2020, 1, 1))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase")
    assert isinstance(result, str)
    assert "[" in result  # has a bracketed header from at least one hit


def test_bind_search_filings_call_with_before_date_filter(built_index):
    tool = bind_search_filings("MINI", date(2020, 1, 1))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase", before_date=date(2024, 3, 1))
    # 10-K filed 2024-02-20 is the only filing on/before 2024-03-01.
    # 8-K (2024-06-14) and 10-Q (2024-04-30) should not appear.
    assert "2024-06-14" not in result
    assert "2024-04-30" not in result


def test_search_tool_widens_when_before_date_equals_after_date(built_index):
    """When the agent passes a `before_date` equal to the closed-over
    `after_date`, the window would collapse to a single day and return
    nothing. The tool layer silently widens by treating `before_date` as
    None — the agent gets useful evidence back instead of an empty list."""
    tool = bind_search_filings("MINI", date(2020, 1, 1))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase", before_date=date(2020, 1, 1))
    # Without widen, window is [2020-01-01, 2020-01-01] -> empty.
    # With widen, all three fixture filings (filed 2024) are in range.
    assert result != "[no matching filings]"
    assert "2024" in result


def test_search_tool_widens_when_before_date_less_than_after_date(built_index):
    """Symmetric to the equal case — any `before_date <= after_date` is a
    non-useful upper bound that the tool layer ignores."""
    tool = bind_search_filings("MINI", date(2020, 6, 1))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase", before_date=date(2020, 3, 1))
    # Without widen, window is [2020-06-01, 2020-03-01] -> empty.
    # With widen, after_date=2020-06-01 still floors out, but the upper
    # bound is dropped, so the 2024 filings pass through.
    assert result != "[no matching filings]"
    assert "2024" in result
