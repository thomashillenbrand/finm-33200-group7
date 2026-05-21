"""Typed claim schema for the extraction pipeline (workstream B).

Workstream B extracts forward-looking management claims from earnings call
transcripts and writes them to a CSV that workstream C (verification) and
workstream D (labeling) consume.

Two model layers:
  - ``ExtractedClaim`` / ``ExtractionResponse`` -- the raw structured output the
    LLM returns for one call. Deliberately minimal: only what the model must
    read from the transcript and decide.
  - ``Claim`` -- the enriched record written to the output CSV. Adds firm/call
    provenance, resolved horizon dates, and run metadata that ``extractor``
    fills in deterministically (no model tokens, no hallucination risk).

By design, no field on any of these models expresses a verdict, an outcome, or
a judgment on whether a claim came true. The extractor surfaces claims; the
verification agent surfaces evidence; human labelers assign verdicts. Keeping
outcome language out of B's schema protects that separation (see CLAUDE.md --
the labeling workflow is load-bearing).

``Claim`` reduces cleanly to ``verifier.schema.Claim`` at the seam::

    verifier.schema.Claim(
        ticker=claim.ticker,
        call_date=claim.call_date,
        text=claim.verbatim_quote,
    )
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Five claim types. ``numerical_guidance`` is graded against Compustat; the four
# capital-allocation types are graded against subsequent 10-Q/10-K/8-K filings.
ClaimType = Literal["numerical_guidance", "buyback", "dividend", "capex", "debt"]

CLAIM_TYPES: tuple[str, ...] = (
    "numerical_guidance",
    "buyback",
    "dividend",
    "capex",
    "debt",
)


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
        description="One of: numerical_guidance, buyback, dividend, capex, debt.",
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


class Claim(BaseModel):
    """An enriched, CSV-bound claim record -- one row of the workstream-B output.

    This is the contract handed downstream to workstreams C and D.
    """

    # --- Identity ---
    claim_id: str = Field(min_length=1, description="Stable, deterministic id.")

    # --- Firm + call provenance ---
    ticker: str = Field(min_length=1)
    company: str = Field(min_length=1)
    call_date: date
    fiscal_period: str = Field(description="Fiscal quarter of the call, e.g. 'Q4 2017'.")
    source_call: str = Field(description="Transcript headline of the source call.")

    # --- Claim content (lightweight schema: type + quote + paraphrase) ---
    claim_type: ClaimType
    verbatim_quote: str = Field(min_length=1)
    quote_verbatim: bool = Field(
        default=False,
        description="True if verbatim_quote is an exact substring of the source "
        "turn; False if it was only fuzzy-matched or could not be located.",
    )
    summary: str = Field(min_length=1)

    # --- Horizon: raw wording kept for audit, plus a resolved period/date ---
    horizon_raw: str = ""
    horizon_period: str = Field(
        default="", description="Resolved period label, e.g. 'FY2024' or 'Q2 2022'."
    )
    horizon_end_date: Optional[date] = Field(
        default=None,
        description="Resolved end date of the horizon period, if resolvable.",
    )

    # --- Turn-level provenance (recovered by matching the quote to a turn) ---
    transcript_id: int
    component_id: int = Field(
        description="Source turn id, or 0 if the quote could not be located."
    )
    speaker_name: str = ""
    speaker_type: str = ""

    # --- Run metadata (reproducibility) ---
    extraction_model: str = ""
    prompt_version: str = ""
    extracted_at: Optional[datetime] = None


def make_claim_id(
    ticker: str, call_date: date, component_id: int, quote: str
) -> str:
    """Build a stable, deterministic claim id from a claim's content.

    Deterministic in ``(ticker, call_date, component_id, quote)``, so re-running
    extraction yields the same id for the same claim and workstream C's
    verification results can join back reliably.
    """
    digest = hashlib.sha1(
        f"{ticker}|{call_date.isoformat()}|{component_id}|{quote}".encode("utf-8")
    ).hexdigest()[:8]
    return f"{ticker}_{call_date:%Y%m%d}_{digest}"


# Column order for the output CSV. Kept here so the writer and any downstream
# reader agree on a single source of truth.
CSV_FIELDS: tuple[str, ...] = (
    "claim_id",
    "ticker",
    "company",
    "call_date",
    "fiscal_period",
    "claim_type",
    "verbatim_quote",
    "quote_verbatim",
    "summary",
    "horizon_raw",
    "horizon_period",
    "horizon_end_date",
    "speaker_name",
    "speaker_type",
    "transcript_id",
    "component_id",
    "source_call",
    "extraction_model",
    "prompt_version",
    "extracted_at",
)
