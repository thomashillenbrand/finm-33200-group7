"""Gold-set labeling schema and JSONL loader.

The artifact is one JSONL row per labeled claim, written by hand during the
gold-set labeling sprint and consumed by `verifier.eval` for scoring.

Schema invariants (enforced):
- claim_id is non-empty
- verdict is one of the four canonical buckets (shared with the agent's
  `Verdict` via `schemas.VerdictLabel`, so the scorer can compare by equality)
- if verdict in {verified, partially_verified, contradicted}, expected_evidence
  must be non-empty (a claim cannot be "verified" with no evidence pointing to
  it)
- if verdict == not_yet_resolvable, expected_evidence may be empty
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from schemas import VerdictLabel

Confidence = Literal["high", "medium", "low"]

_DECISIVE_VERDICTS = {"verified", "partially_verified", "contradicted"}


class GoldEvidence(BaseModel):
    """One filing excerpt the labeler judged necessary to decide the verdict.

    Matched at `accession_no` granularity by the scorer — labelers point at
    filings, not at the chunker's window cuts.
    """

    accession_no: str = Field(min_length=1)
    form: Literal["10-K", "10-Q", "8-K"]
    filing_date: date
    quote: str = Field(min_length=1, max_length=500)
    section: Optional[str] = None


class GoldLabel(BaseModel):
    """One human-assigned label for one claim."""

    claim_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    labeler: str = Field(min_length=1)
    labeled_at: datetime
    expected_evidence: list[GoldEvidence] = Field(default_factory=list)
    verdict: VerdictLabel
    confidence: Confidence
    labeler_notes: str = ""

    @model_validator(mode="after")
    def evidence_required_for_decisive_verdicts(self) -> "GoldLabel":
        if self.verdict in _DECISIVE_VERDICTS and not self.expected_evidence:
            raise ValueError(
                f"verdict={self.verdict!r} requires non-empty expected_evidence; "
                f"use 'not_yet_resolvable' if no evidence applies."
            )
        return self


def load_gold_labels(path: Path | str) -> list[GoldLabel]:
    """Read a JSONL file, returning one GoldLabel per non-blank line.

    Raises ValueError on the first malformed row, with the row number in the
    message — labelers fix the file rather than silently dropping bad rows.
    """
    labels: list[GoldLabel] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                labels.append(GoldLabel.model_validate_json(line))
            except Exception as e:
                raise ValueError(f"gold label row {i} failed validation: {e}") from e
    return labels
