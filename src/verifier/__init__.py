"""Verification agent package: builds an auditable graded verdict for a single claim.

Public surface:
  Claim, EvidenceItem, EvidenceBundle, Verdict   — typed input/output models
  verify, verify_from_dict                       — run the agent on one claim
"""

from schemas import Claim, EvidenceItem, EvidenceBundle, Verdict
from verifier.agent import verify, verify_from_dict

__all__ = [
    "Claim",
    "EvidenceItem",
    "EvidenceBundle",
    "Verdict",
    "verify",
    "verify_from_dict",
]
