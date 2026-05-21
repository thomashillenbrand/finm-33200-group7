"""Claim extraction package — workstream B.

Public surface:
    NumericalGuidanceClaim, CapitalAllocationClaim  — typed claim models
    ExtractionResult                                — full extraction output for one call
    TranscriptLoader                                — load/assemble transcripts from parquet
"""

from extractor.schema import (
    CapitalAllocationClaim,
    ExtractionResult,
    ExtractorClaim,
    NumericalGuidanceClaim,
)
from extractor.loader import TranscriptLoader

__all__ = [
    "NumericalGuidanceClaim",
    "CapitalAllocationClaim",
    "ExtractionResult",
    "ExtractorClaim",
    "TranscriptLoader",
]
