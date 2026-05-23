"""Shim guarantees: `from verifier.schema import X` returns the same class as
`from schemas import X`. The whole point of the shim is identity, not just
equivalence — extractor_2's existing imports work without code change.

Delete this file when the shim is removed (iter-2 Open Items #6).
"""

import schemas
import verifier.schema as legacy


def test_shim_reexports_are_identical_to_schemas():
    assert legacy.Claim is schemas.Claim
    assert legacy.EvidenceItem is schemas.EvidenceItem
    assert legacy.EvidenceBundle is schemas.EvidenceBundle
    assert legacy.Verdict is schemas.Verdict


def test_shim_supports_legacy_extractor2_imports():
    """Exact import line used in src/extractor_2/{schema,for_verifier}.py."""
    from verifier.schema import Claim as VerifierClaim  # noqa: F401
    assert VerifierClaim is schemas.Claim
