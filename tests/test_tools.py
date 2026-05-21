from datetime import date

from verifier.tools import search_filings


def test_search_filings_returns_string_with_sources():
    result = search_filings(
        query="production growth",
        ticker="TSLA",
        after_date=date(2024, 1, 24),
        before_date=None,
        forms=None,
    )
    assert isinstance(result, str)
    # Stub should at minimum include source citations from the canned set.
    assert "TSLA" in result
