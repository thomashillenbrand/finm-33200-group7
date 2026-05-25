"""EvidenceItem — one filing excerpt, with the citation metadata the labeler
needs to join back to the source filing.

`source` is built deterministically from the structured fields; it's the human
string the LLM sees in tool results and the labeler sees in the bundle, so it
is load-bearing as a human-facing identifier.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class EvidenceItem(BaseModel):
    source: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)
    accession_no: str = Field(min_length=1)
    form: Literal["10-K", "10-Q", "8-K"]
    filing_date: Optional[date] = None
    chunk_id: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    edgar_url: Optional[str] = None

    @field_validator("filing_date", mode="before")
    @classmethod
    def _tolerate_unknown_date(cls, v: object) -> object:
        """Coerce an unparseable / out-of-range date to None instead of raising.

        The verdict parser occasionally emits a year-0 placeholder
        ("0000-01-01") for a citation whose filing date it cannot determine.
        That must not crash the whole run — scoring joins on ``accession_no``,
        not the date — so an invalid date string becomes an unknown (None) date.
        Dates built from the filing index (always valid) pass through unchanged.
        """
        if isinstance(v, str):
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
        return v
