"""Stage-2: compare a Compustat-relevant claim against the post-call panel."""

from __future__ import annotations

from datetime import date
from typing import Literal

from autochecker.compustat import CompustatSlice, format_table
from autochecker.llm import build_structured_llm, retry_on_rate_limit
from autochecker.prompts import (
    EVIDENCE_SYSTEM,
    VERDICT_SYSTEM,
    build_stage2_user_prompt,
)
from autochecker.schema import (
    CompustatCitation,
    EvidenceResult,
    ScreenResult,
    VerdictResult,
)

Mode = Literal["evidence", "verdict"]


def build_verifier(mode: Mode, *, model_name: str | None = None):
    """Return an LLM bound to ``EvidenceResult`` or ``VerdictResult``."""
    schema = EvidenceResult if mode == "evidence" else VerdictResult
    return build_structured_llm(schema, model_name=model_name)


@retry_on_rate_limit
def verify_claim(
    *,
    mode: Mode,
    ticker: str,
    company: str,
    call_date: date,
    horizon_end_date: date | None,
    claim_type: str,
    verbatim_quote: str,
    summary: str,
    screen: ScreenResult,
    panel_slice: CompustatSlice,
    verifier=None,
) -> EvidenceResult | VerdictResult:
    """Run stage 2 on one Compustat-relevant claim.

    Caller is responsible for not invoking stage 2 when the screen rejected
    the claim or when ``panel_slice.is_empty`` (horizon missing or all rows
    out of window). Pass ``verifier`` to reuse a client.
    """
    if verifier is None:
        verifier = build_verifier(mode)
    system = EVIDENCE_SYSTEM if mode == "evidence" else VERDICT_SYSTEM
    table = format_table(panel_slice, screen.candidate_fields)
    user = build_stage2_user_prompt(
        ticker=ticker,
        company=company,
        call_date=call_date,
        horizon_end_date=horizon_end_date,
        claim_type=claim_type,
        verbatim_quote=verbatim_quote,
        summary=summary,
        assertion_kind=screen.assertion_kind,
        candidate_fields=screen.candidate_fields,
        table_csv=table,
    )
    result = verifier.invoke(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )
    return _scrub_citations(result, panel_slice)


def _scrub_citations(
    result: EvidenceResult | VerdictResult, panel_slice: CompustatSlice
) -> EvidenceResult | VerdictResult:
    """Drop hallucinated citations: any (datadate, field) the panel doesn't have.

    A defensive layer behind the prompt — the LLM occasionally invents a
    quarter or cites a field that isn't in the slice. We compare each
    citation against the actual sliced rows and drop misses. Citations whose
    value disagrees with the panel are kept (the LLM's value field is for
    its own working — what matters is the (datadate, field) pointer).
    """
    if panel_slice.rows.empty:
        # No data to scrub against; nothing changes.
        return result
    valid_dates = set(panel_slice.rows["datadate"].tolist())
    valid_fields = set(panel_slice.rows.columns)
    kept: list[CompustatCitation] = []
    for c in result.citations:
        if c.datadate in valid_dates and c.field in valid_fields:
            kept.append(c)
    return result.model_copy(update={"citations": kept})
