"""Per-claim search_filings closure.

The bound tool's LLM-visible signature contains only `query`, `before_date`,
and `forms`. `ticker` and `after_date` are closed over in the factory so the
LLM can never widen them backwards.
"""

from __future__ import annotations

from datetime import date

from langchain_core.tools import tool

from schemas import EvidenceItem
from verifier.corpus import SearchIndex


def _stringify_evidence(items: list[EvidenceItem]) -> str:
    """Render a list of evidence items into the string the LLM sees."""
    if not items:
        return "[no matching filings]"
    parts: list[str] = []
    for it in items:
        header = f"[{it.source}] (score {it.score:.2f})"
        parts.append(f"{header}\n{it.excerpt}")
    return "\n\n---\n\n".join(parts)


def bind_search_filings(ticker: str, after_date: date):
    """Return a LangChain `@tool`-decorated closure for one claim.

    Closing over `(ticker, after_date)` means the LLM cannot pass either as a
    tool argument — they're not in the visible signature. This is the
    load-bearing no-time-leakage guarantee.
    """
    index = SearchIndex.load(ticker)

    @tool
    def search_filings(
        query: str,
        before_date: date | None = None,
        forms: list[str] | None = None,
    ) -> str:
        """Search this firm's SEC filings for evidence about a claim.

        Args:
            query: Free-form text describing what to look for. Examples:
                "share repurchase amount Q1 2024", "capex 2024 actual spend".
            before_date: Optional upper bound on filing date (inclusive).
                Must be strictly later than the call date that floors the
                search; values at or before the floor are non-useful and are
                ignored (treated as open-ended).
            forms: Optional restriction to filing forms (e.g. ["10-Q", "8-K"]).

        Returns:
            Up to 8 matching excerpts, each preceded by a bracketed
            `[form filed YYYY-MM-DD, accession ...]` header.
        """
        if before_date is not None and before_date <= after_date:
            before_date = None
        items = index.query(query, after_date=after_date,
                            before_date=before_date, forms=forms, k=8)
        return _stringify_evidence(items)

    return search_filings
