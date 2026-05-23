"""Agent-facing tools.

Iteration 2 stubs out `search_filings` with a no-op pending the real
SearchIndex-backed implementation in Task 16. The interface (signature +
return type) is stable; only the body changes between iterations.

Note for human readers: the function docstring for `search_filings` is
LLM-facing and is kept aspirational — it documents the filter parameters
(after_date, before_date, forms) as if they work. Task 16 wires them to
SearchIndex.query; until then the body returns an empty result.
"""

from __future__ import annotations

from datetime import date


def search_filings(
    query: str,
    ticker: str,
    after_date: date | None = None,
    before_date: date | None = None,
    forms: list[str] | None = None,
) -> str:
    """Search a firm's SEC filings for evidence about a claim.

    Args:
        query: Free-form text describing what to look for. Examples:
            "2024 production growth vs 50% target", "buyback execution Q2 2024".
        ticker: The firm's ticker (e.g. "TSLA").
        after_date: Only consider filings on or after this date.
        before_date: Only consider filings on or before this date.
        forms: Restrict to these filing forms (e.g. ["10-Q", "8-K"]). None = any.

    Returns:
        Matching excerpts with source citations, joined into one string.
        (Task 16 will wire this to SearchIndex.query; currently returns empty.)
    """
    # Iteration 2 stub: real SearchIndex.query integration in Task 16.
    return ""
