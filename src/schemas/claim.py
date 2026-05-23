"""Combined Claim schema — the single source of truth that both the merged
extractor and the verifier consume.

Workstream C owns this seam (per iter-1 design note). The extractor merger PR
conforms to this shape; the verifier does not wait for the merger.

Iter-2 verifier reads: claim_type, verbatim_quote, summary, call_date,
horizon_end_date, ticker. The rest is provenance — passed through into traces
and the labeler UI, never consulted by the retriever.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

ClaimType = Literal["numerical_guidance", "buyback", "dividend", "capex", "debt"]


class Claim(BaseModel):
    # Identity
    claim_id: str = Field(min_length=1)

    # Firm + call provenance
    ticker: str = Field(min_length=1)
    call_date: date
    company: str = Field(min_length=1)
    fiscal_period: str = Field(min_length=1, description="e.g. 'Q4 2023'")
    source_call: str = Field(min_length=1, description="Transcript headline")

    # Claim content
    claim_type: ClaimType
    verbatim_quote: str = Field(min_length=1)
    summary: str = Field(min_length=1)

    # Horizon
    horizon_raw: str = ""
    horizon_period: str = ""
    horizon_end_date: Optional[date] = None

    # Turn-level provenance
    speaker_name: str = ""
    speaker_type: str = ""
    transcript_id: Optional[int] = None
    component_id: Optional[int] = None
