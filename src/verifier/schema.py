from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    """Forward-looking claim to verify.

    Workstream C owns this schema. If workstream B's extraction output has a
    different shape, write a converter at the seam; do not couple this model
    to B's choices.
    """

    ticker: str = Field(min_length=1)
    call_date: date
    text: str = Field(min_length=1)


class EvidenceItem(BaseModel):
    source: str
    excerpt: str


class EvidenceBundle(BaseModel):
    """Output of `mode='evidence'`. Has no verdict field, by design."""

    items: list[EvidenceItem]


class Verdict(BaseModel):
    """Output of `mode='verdict'`. Carries the verdict label and reasoning."""

    items: list[EvidenceItem]
    verdict: Literal["verified", "partially_verified", "contradicted", "not_yet_resolvable"]
    reasoning: str
