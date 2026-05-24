"""Per-claim search_filings closure.

The bound tool's LLM-visible signature contains only `query` and `forms`.
`ticker`, `after_date`, and `horizon_end` are closed over in the factory so the
LLM can neither widen the search before the call date nor past the claim's
horizon — both time bounds are enforced at the tool layer, not trusted to the
model.
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


def bind_search_filings(ticker: str, after_date: date, horizon_end: date | None = None):
    """Return a LangChain `@tool`-decorated closure for one claim.

    Closing over `(ticker, after_date, horizon_end)` means the LLM cannot pass
    any of them as a tool argument — they're not in the visible signature. The
    search window is floored at the call date (`after_date`) and ceilinged at
    the claim's resolved horizon (`horizon_end`, or open-ended when unresolved).
    This is the load-bearing no-time-leakage guarantee.
    """
    index = SearchIndex.load(ticker)

    @tool
    def search_filings(
        query: str,
        forms: list[str] | None = None,
    ) -> str:
        """Search this firm's SEC filings for evidence about a claim.

        The search is automatically restricted to filings within the claim's
        time window (filed after the call date, fiscal period within the
        claim's horizon); you do not control the date range.

        Args:
            query: Free-form text describing what to look for. Examples:
                "share repurchase amount Q1 2024", "capex 2024 actual spend".
            forms: Optional restriction to filing forms (e.g. ["10-Q", "8-K"]).

        Returns:
            Up to 8 matching excerpts, each preceded by a bracketed
            `[form filed YYYY-MM-DD, accession ...]` header.
        """
        items = index.query(query, after_date=after_date,
                            horizon_end=horizon_end, forms=forms, k=8)
        return _stringify_evidence(items)

    return search_filings
