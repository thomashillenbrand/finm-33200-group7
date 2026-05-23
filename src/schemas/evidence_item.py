"""EvidenceItem — one filing excerpt, with the citation metadata the labeler
needs to join back to the source filing.

`source` is built deterministically from the structured fields; it's the human
string the LLM sees in tool results and the labeler sees in the bundle, so it
is load-bearing as a human-facing identifier.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    accession_no: str = Field(min_length=1)
    form: Literal["10-K", "10-Q", "8-K"]
    filing_date: date
    chunk_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    edgar_url: Optional[str] = None
