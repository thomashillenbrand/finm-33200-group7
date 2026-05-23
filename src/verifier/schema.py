"""Transitional shim — re-exports the shared `schemas` package types so legacy
imports (`from verifier.schema import Claim`) keep compiling during the
extractor merger.

Remove this file once `src/extractor_2/schema.py` and
`src/extractor_2/for_verifier.py` have switched to `from schemas import …`.
See iter-2 design's Open Items #6.
"""

from schemas import Claim, ClaimType, EvidenceItem, EvidenceBundle, Verdict

__all__ = ["Claim", "ClaimType", "EvidenceItem", "EvidenceBundle", "Verdict"]
