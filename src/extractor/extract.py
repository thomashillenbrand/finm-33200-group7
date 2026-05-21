"""Post-processing utilities: deduplication and result enrichment.

Enrichment wires together horizon resolution and provenance matching
so the saved JSON has resolved dates and speaker attribution.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from extractor.horizon import resolve_horizon
from extractor.provenance import find_speaker
from extractor.schema import (
    CapitalAllocationClaim,
    ExtractionResult,
    NumericalGuidanceClaim,
)


# ── Filtering ─────────────────────────────────────────────────────────────────

import re as _re

def _has_number(text: str) -> bool:
    """Return True if text contains a non-year number (dollar, %, basis points, etc.)."""
    # Strip calendar years (2000–2099) — a year alone is not a financial figure
    stripped = _re.sub(r"\b20\d{2}\b", "", text)
    return bool(_re.search(r"\d", stripped))


def filter_vague(result: ExtractionResult) -> ExtractionResult:
    """Drop claims that have no value_or_amount AND no digits in the source_span.

    These are pure directional statements ("CapEx will increase") that slipped
    through the prompt. Nothing to verify against Compustat without a figure.
    """
    kept = [
        c for c in result.claims
        if c.value_or_amount is not None or _has_number(c.source_span)
    ]
    return result.model_copy(update={"claims": kept})


# ── Deduplication ──────────────────────────────────────────────────────────────

def deduplicate(result: ExtractionResult) -> ExtractionResult:
    """Remove claims with identical or near-identical source_spans."""
    seen: set[str] = set()
    unique = []
    for claim in result.claims:
        key = claim.source_span.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(claim)
    return result.model_copy(update={"claims": unique})


# ── Enrichment ─────────────────────────────────────────────────────────────────

def _enrich_claim(
    claim: NumericalGuidanceClaim | CapitalAllocationClaim,
    call_date: date,
    transcript_df: pd.DataFrame,
) -> dict:
    """Return a dict representation of the claim enriched with horizon dates + speaker."""
    data = claim.model_dump()

    # Resolved horizon dates
    bounds = resolve_horizon(call_date, claim.horizon)
    data["horizon_start"] = str(bounds[0]) if bounds else None
    data["horizon_end"] = str(bounds[1]) if bounds else None

    # Speaker provenance
    prov = find_speaker(claim.source_span, transcript_df)
    data["speaker"] = prov["speaker"]
    data["speaker_type"] = prov["speaker_type"]
    data["component_order"] = prov["component_order"]

    return data


def enrich_result(result: ExtractionResult, transcript_df: pd.DataFrame) -> dict:
    """Return a JSON-serialisable dict of the result with all enrichment fields."""
    enriched_claims = [
        _enrich_claim(c, result.call_date, transcript_df) for c in result.claims
    ]
    return {
        "ticker": result.ticker,
        "transcript_id": result.transcript_id,
        "call_date": str(result.call_date),
        "claims": enriched_claims,
    }
