"""Agent-facing tools.

Iteration 1 ships one stubbed tool. The signature mirrors what the real
EDGAR-backed version will need, so iteration 2 swaps the body, not the
interface.

Note for human readers: the function docstring for `search_filings` is
LLM-facing and is kept aspirational — it documents the filter parameters
(after_date, before_date, forms) as if they work. In iteration 1 the body
*accepts but ignores* those filters. This is deliberate: the agent's
tool-call traces should show it reasoning about ticker, dates, and forms
even before real filtering is wired in, so we know it's targeting the
right filings when iteration 2 lands.
"""

from __future__ import annotations

from datetime import date

from verifier.corpus import load_stub_excerpts


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
    """
    # Iteration 1: ignore filter args, return all canned excerpts.
    # Note: load_stub_excerpts() returns a list of EvidenceItem objects,
    # so access .source and .excerpt as attributes (not dict keys).
    excerpts = load_stub_excerpts()
    return "\n\n---\n\n".join(f"[{e.source}]\n{e.excerpt}" for e in excerpts)
