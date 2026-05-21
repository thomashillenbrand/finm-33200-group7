from verifier.corpus import load_stub_excerpts
from verifier.schema import EvidenceItem


def test_load_stub_excerpts_returns_list_of_evidence_items():
    excerpts = load_stub_excerpts()
    assert isinstance(excerpts, list)
    assert len(excerpts) >= 1
    for item in excerpts:
        assert isinstance(item, EvidenceItem)
        assert item.source
        assert item.excerpt
