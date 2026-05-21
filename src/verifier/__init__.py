"""Verification agent package: builds an auditable graded verdict for a single claim.

Public surface (use these; the submodule layout may shift in iteration 2):
  Claim, EvidenceItem, EvidenceBundle, Verdict   — typed input/output models
  verify, verify_from_dict                       — run the agent on one claim
"""

from verifier.schema import Claim, EvidenceItem, EvidenceBundle, Verdict
from verifier.agent import verify, verify_from_dict

__all__ = [
    "Claim",
    "EvidenceItem",
    "EvidenceBundle",
    "Verdict",
    "verify",
    "verify_from_dict",
]
