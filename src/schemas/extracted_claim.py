"""Intermediate LLM-output schema for the extraction pipeline (workstream B).

These are the raw types the structured-output LLM returns for a single call.
They differ from `Claim` in that they hold only what the model must decide --
no firm/call provenance, no resolved horizon dates, no run metadata. The
extractor enriches one of these into a full `Claim` deterministically.

Kept as siblings of `Claim` in this package because they share `ClaimType` and
the same load-bearing invariant: no verdict, no outcome, no judgment language
on any field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.claim import ClaimType


class ExtractedClaim(BaseModel):
    """One forward-looking claim, as returned by the LLM for a single call.

    Every field here is something the model must read from the transcript and
    decide. The source turn is *not* asked of the model -- the pilot showed
    model-reported ids are unreliable -- it is recovered afterwards by matching
    ``verbatim_quote`` back to a turn (see ``extractor.provenance``). Resolved
    dates and run metadata are likewise added deterministically by
    ``extractor.extract``.
    """

    claim_type: ClaimType = Field(
        description="One of: numerical_guidance, capital_allocation.",
    )
    verbatim_quote: str = Field(
        min_length=1,
        description="Exact substring of the transcript stating the claim.",
    )
    summary: str = Field(
        min_length=1,
        description="One plain sentence paraphrasing what is being claimed.",
    )
    horizon_raw: str = Field(
        default="",
        description="Exact wording of the claim's time horizon, or '' if none stated.",
    )


class ExtractionResponse(BaseModel):
    """Structured-output wrapper: all claims the LLM found in one call."""

    claims: list[ExtractedClaim] = Field(default_factory=list)
