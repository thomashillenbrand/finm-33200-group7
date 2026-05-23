"""Verdict — the verdict-mode output. Carries the label and reasoning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from schemas.evidence_item import EvidenceItem


class Verdict(BaseModel):
    items: list[EvidenceItem]
    verdict: Literal["verified", "partially_verified", "contradicted", "not_yet_resolvable"]
    reasoning: str
