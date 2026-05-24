"""Verification agent package: builds an auditable graded verdict for a single claim.

Public surface:
  Claim, EvidenceItem, EvidenceBundle, Verdict   — typed input/output models
  verify, verify_from_dict                       — run the agent on one claim

``verify`` / ``verify_from_dict`` are exposed lazily (PEP 562 ``__getattr__``):
importing them eagerly would load the agent stack (deepagents, faiss) on every
``import verifier.*``, including lightweight, agent-free submodules such as
``verifier.label`` and ``verifier.gold`` that must not depend on it.
``from verifier import verify`` still works -- it triggers the lazy import.
"""

from schemas import Claim, EvidenceBundle, EvidenceItem, Verdict

__all__ = [
    "Claim",
    "EvidenceItem",
    "EvidenceBundle",
    "Verdict",
    "verify",
    "verify_from_dict",
]


def __getattr__(name):
    """Lazily expose the agent entry points so importing a light submodule of
    this package does not pull in the agent stack (deepagents, faiss)."""
    if name in ("verify", "verify_from_dict"):
        from verifier.agent import verify, verify_from_dict
        return {"verify": verify, "verify_from_dict": verify_from_dict}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
