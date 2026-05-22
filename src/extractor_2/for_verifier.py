"""Loader for workstream C: converts extraction results to verifier.schema.Claim objects.

Usage:
    from extractor.for_verifier import load_claims_for_verifier
    claims = load_claims_for_verifier("data/extraction_runs/manifest.json")
"""

from __future__ import annotations

import json
from pathlib import Path

from verifier.schema import Claim as VerifierClaim

from extractor.schema import ExtractionResult


def load_claims_for_verifier(manifest_path: str | Path) -> list[VerifierClaim]:
    """Read manifest.json and return all extracted claims as VerifierClaim objects."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    claims: list[VerifierClaim] = []
    for entry in manifest["files"]:
        result_path = Path(entry["path"])
        result = ExtractionResult.model_validate_json(
            result_path.read_text(encoding="utf-8")
        )
        for claim in result.claims:
            claims.append(claim.to_verifier_claim(result.ticker, result.call_date))
    return claims
