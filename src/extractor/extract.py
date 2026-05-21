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
