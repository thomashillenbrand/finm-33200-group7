"""Claim extraction pipeline -- workstream B.

Extracts forward-looking management claims from earnings call transcripts and
writes them to a CSV consumed by workstream C (verification) and workstream D
(labeling).
"""

from extractor.extract import (
    build_extractor,
    dedupe_claims,
    extract_call,
    extract_transcript,
)
from extractor.horizon import resolve_horizon
from extractor.output import write_claims_csv
from extractor.provenance import QuoteMatch, locate_quote
from extractor.reader import EarningsCall, Turn, build_call_input, load_calls
from extractor.schema import (
    CSV_FIELDS,
    Claim,
    ClaimType,
    ExtractedClaim,
    ExtractionResponse,
)

__all__ = [
    "Claim",
    "ClaimType",
    "ExtractedClaim",
    "ExtractionResponse",
    "CSV_FIELDS",
    "EarningsCall",
    "Turn",
    "load_calls",
    "build_call_input",
    "resolve_horizon",
    "QuoteMatch",
    "locate_quote",
    "build_extractor",
    "extract_call",
    "extract_transcript",
    "dedupe_claims",
    "write_claims_csv",
]
