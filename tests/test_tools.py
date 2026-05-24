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

def test_bind_search_filings_hides_time_bounds_from_llm(built_index):
    """LLM-visible signature must omit every time bound — `ticker`,
    `after_date`, `horizon_end`, and the retired `before_date`. Closing them
    over is the load-bearing no-time-leakage guarantee; the LLM gets no date
    knob to widen."""
    tool = bind_search_filings("MINI", date(2024, 1, 1), date(2024, 12, 31))
    # Inspect the underlying function's parameters (handle both bare-function
    # and langchain-Tool wrappers):
    fn = getattr(tool, "func", tool)
    params = inspect.signature(fn).parameters
    assert "query" in params
    assert "ticker" not in params
    assert "after_date" not in params
    assert "horizon_end" not in params
    assert "before_date" not in params


def test_bind_search_filings_callable_returns_string(built_index):
    tool = bind_search_filings("MINI", date(2020, 1, 1))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase")
    assert isinstance(result, str)
    assert "[" in result  # has a bracketed header from at least one hit


def test_bind_search_filings_ceilings_by_closed_over_horizon(built_index):
    """The horizon ceiling is closed over, not an LLM argument. With a horizon
    of 2024-01-31, only the 10-K (reports 2023-12-31) is in window; the 10-Q
    (reports 2024-03-31) and 8-K (reports 2024-06-14) are excluded."""
    tool = bind_search_filings("MINI", date(2020, 1, 1), date(2024, 1, 31))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase")
    assert "2024-06-14" not in result  # 8-K out of horizon
    assert "2024-04-30" not in result  # 10-Q out of horizon
    assert "2024-02-20" in result      # 10-K (period 2023-12-31) in horizon


def test_bind_search_filings_unbounded_horizon_returns_all(built_index):
    """horizon_end defaults to None (unresolved horizon) → no upper bound, so
    every post-call filing is reachable."""
    tool = bind_search_filings("MINI", date(2020, 1, 1))
    fn = getattr(tool, "func", tool)
    result = fn(query="share repurchase")
    assert result != "[no matching filings]"
    assert "2024" in result
