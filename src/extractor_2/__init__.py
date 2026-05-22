"""Claim extraction package — workstream B.

Public surface:
    NumericalGuidanceClaim, CapitalAllocationClaim  — typed claim models
    ExtractionResult                                — full extraction output for one call
    TranscriptLoader                                — load/assemble transcripts from parquet
    resolve_horizon                                 — convert horizon label to date range
    find_speaker                                    — link claim to transcript speaker
    deduplicate, enrich_result                      — post-processing
    write_json, write_csv                           — output writers
"""

from extractor.extract import deduplicate, enrich_result
from extractor.horizon import resolve_horizon
from extractor.loader import TranscriptLoader
from extractor.output import write_csv, write_json
from extractor.provenance import find_speaker
from extractor.schema import (
    CapitalAllocationClaim,
    ExtractionResult,
    ExtractorClaim,
    NumericalGuidanceClaim,
)

__all__ = [
    "NumericalGuidanceClaim",
    "CapitalAllocationClaim",
    "ExtractionResult",
    "ExtractorClaim",
    "TranscriptLoader",
    "resolve_horizon",
    "find_speaker",
    "deduplicate",
    "enrich_result",
    "write_json",
    "write_csv",
]
