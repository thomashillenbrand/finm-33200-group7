"""Verdict — the verdict-mode output. Carries the label and reasoning."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from schemas.evidence_item import EvidenceItem

# The four canonical verdict buckets. Single source of truth shared by the
# agent's `Verdict` output and the gold-set `GoldLabel` — the scorer compares
# the two by equality, so they must never drift apart.
VerdictLabel = Literal[
    "verified", "partially_verified", "contradicted", "not_yet_resolvable"
]


class Verdict(BaseModel):
    items: list[EvidenceItem]
    verdict: VerdictLabel
    reasoning: str
