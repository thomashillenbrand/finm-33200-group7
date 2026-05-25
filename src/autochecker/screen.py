"""Stage-1: Compustat-relevance screen."""

from __future__ import annotations

from datetime import date

from autochecker.llm import build_structured_llm, retry_on_rate_limit
from autochecker.prompts import SCREEN_SYSTEM, build_screen_user_prompt
from autochecker.schema import ScreenResult


def build_screener(*, model_name: str | None = None):
    """Return an LLM bound to ``ScreenResult``."""
    return build_structured_llm(ScreenResult, model_name=model_name)


@retry_on_rate_limit
def screen_claim(
    *,
    ticker: str,
    company: str,
    call_date: date,
    claim_type: str,
    verbatim_quote: str,
    summary: str,
    screener=None,
) -> ScreenResult:
    """Run stage 1 on one claim.

    Pass ``screener`` to reuse a client across many claims; otherwise one is
    built per call.
    """
    if screener is None:
        screener = build_screener()
    user = build_screen_user_prompt(
        ticker=ticker,
        company=company,
        call_date=call_date,
        claim_type=claim_type,
        verbatim_quote=verbatim_quote,
        summary=summary,
    )
    result = screener.invoke(
        [
            {"role": "system", "content": SCREEN_SYSTEM},
            {"role": "user", "content": user},
        ]
    )
    return _normalise(result)


def _normalise(result: ScreenResult) -> ScreenResult:
    """Enforce the schema's cross-field invariants the LLM may violate.

    Belt-and-braces on top of the prompt: if the model says irrelevant but
    still emits fields/assertion_kind, clear them; if it says relevant but
    forgets the assertion_kind, default to 'both'.
    """
    if not result.is_compustat_relevant:
        return result.model_copy(
            update={"candidate_fields": [], "assertion_kind": "none"}
        )
    kind = result.assertion_kind
    if kind == "none":
        kind = "both"
    return result.model_copy(update={"assertion_kind": kind})
