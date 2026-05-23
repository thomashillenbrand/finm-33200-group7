from datetime import date

from verifier.tools import search_filings


def test_search_filings_stub_returns_empty_string():
    """Between iter-1 (canned excerpts) and iter-2 Task 16 (per-claim closure),
    `search_filings` is a deliberate no-op stub. Task 16 replaces this whole
    test file with closure-signature + stringify tests."""
    result = search_filings(
        query="production growth",
        ticker="TSLA",
        after_date=date(2024, 1, 24),
        before_date=None,
        forms=None,
    )
    assert isinstance(result, str)
    assert result == ""
