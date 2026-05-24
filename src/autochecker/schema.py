"""Pydantic schemas for the autochecker pipeline.

Scoped to this package — they describe stage-1 / stage-2 LLM outputs and the
per-claim record written to disk. They deliberately do not reuse
``schemas/verdict.py`` because autochecker's verdict carries Compustat
citations (datadate + field code), not SEC filing accessions.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Stage-1 returns one of these to describe how the claim talks about a figure.
# "direction": "we expect revenue to grow"; "magnitude": "we expect $5B revenue";
# "both": "we expect revenue to grow ~20%"; "none": claim is qualitative /
# operational / non-Compustat (delays, product launches, market share).
AssertionKind = Literal["direction", "magnitude", "both", "none"]


class ScreenResult(BaseModel):
    """Stage-1 output: is this claim about a Compustat figure, and which one?"""
    is_compustat_relevant: bool = Field(
        description="True only if the claim asserts something — direction or "
        "magnitude — about a figure that appears in Compustat quarterly "
        "fundamentals."
    )
    candidate_fields: list[str] = Field(
        default_factory=list,
        description="Compustat codes (e.g. 'saleq', 'capx_q') the claim refers "
        "to. Empty when is_compustat_relevant is False.",
    )
    assertion_kind: AssertionKind = Field(
        description="Whether the claim names a magnitude, just a direction, "
        "both, or neither (qualitative)."
    )
    screen_reasoning: str = Field(
        description="One- or two-sentence justification for the screen decision."
    )


class CompustatCitation(BaseModel):
    """One row-and-field reference back to the post-call panel."""
    datadate: date = Field(description="Compustat row's fiscal quarter end.")
    field: str = Field(description="Compustat code from the FIELD_LABELS codebook.")
    value: Optional[float] = Field(
        default=None,
        description="Numeric value seen in that cell, or null if missing.",
    )


class EvidenceResult(BaseModel):
    """Stage-2 evidence-mode output (no verdict)."""
    citations: list[CompustatCitation]
    comparison_notes: str = Field(
        description="Plain-language description of what the cited Compustat "
        "values show, framed around the claim. No verdict language."
    )


class VerdictResult(BaseModel):
    """Stage-2 verdict-mode output."""
    citations: list[CompustatCitation]
    verdict: Literal[
        "verified",
        "partially_verified",
        "contradicted",
        "not_yet_resolvable",
        "insufficient_data",
    ]
    reasoning: str


class AutocheckRecord(BaseModel):
    """One row of the autochecker's disk output (JSONL)."""
    claim_id: str
    ticker: str
    call_date: date
    horizon_end_date: Optional[date]
    claim_type: str
    verbatim_quote: str
    summary: str
    mode: Literal["evidence", "verdict"]
    model: str
    # Stage 1
    screen: ScreenResult
    # Stage 2 (one of the two depending on mode; both null if screen=False or
    # horizon is missing)
    evidence: Optional[EvidenceResult] = None
    verdict: Optional[VerdictResult] = None
    # Bookkeeping
    skipped_reason: Optional[str] = Field(
        default=None,
        description="Set when stage 2 is intentionally not run: "
        "'screen_false', 'no_horizon', 'empty_panel', 'unknown_ticker'.",
    )
