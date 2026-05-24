"""Deduplication tests for the claim-extraction pipeline (workstream B).

Two dedup passes: ``dedupe_claims`` drops exact ``claim_id`` collisions, and
``dedupe_similar_claims`` drops near-duplicate claims emitted twice from the
same source turn.
"""

from datetime import date

from extractor.extract import dedupe_claims, dedupe_similar_claims
from schemas import Claim


def _claim(
    claim_id: str = "C",
    *,
    component_id: int = 100,
    claim_type: str = "numerical_guidance",
    quote: str = "we expect revenue of about $5 billion this year",
    summary: str = "A claim.",
) -> Claim:
    """A minimal valid Claim with caller-chosen identity and content."""
    return Claim(
        claim_id=claim_id,
        ticker="TSLA",
        company="Tesla, Inc.",
        call_date=date(2018, 8, 1),
        fiscal_period="Q2 2018",
        source_call="Tesla, Inc., Q2 2018 Earnings Call, Aug 01, 2018",
        claim_type=claim_type,
        verbatim_quote=quote,
        quote_verbatim=True,
        summary=summary,
        transcript_id=1,
        component_id=component_id,
    )


# --- dedupe_claims: exact claim_id collisions ---------------------------------

def test_dedupe_drops_duplicate_claim_ids():
    result = dedupe_claims([_claim("A"), _claim("B"), _claim("A")])
    assert [c.claim_id for c in result] == ["A", "B"]


def test_dedupe_keeps_first_occurrence():
    result = dedupe_claims([_claim("A", summary="first"), _claim("A", summary="second")])
    assert len(result) == 1
    assert result[0].summary == "first"


def test_dedupe_preserves_order_of_uniques():
    result = dedupe_claims([_claim("X"), _claim("Y"), _claim("Z")])
    assert [c.claim_id for c in result] == ["X", "Y", "Z"]


def test_dedupe_empty_list():
    assert dedupe_claims([]) == []


# --- dedupe_similar_claims: same-turn near-duplicates -------------------------

# Two quotes from one turn that differ by a single word ("about" vs "around").
_NEAR_A = "we expect to install solar roofs at a rate of about one thousand a week"
_NEAR_B = "we expect to install solar roofs at a rate of around one thousand a week"

# A short claim quote and a longer one that fully contains it -- the model
# emitting one claim as a sub-span of another from the same sentence. The
# length gap keeps their similarity ratio well under the 0.88 threshold, so
# only substring containment catches this pair.
_FRAG_SHORT = "we plan to increase capital spending by two billion dollars"
_FRAG_LONG = (
    "we plan to increase capital spending by two billion dollars, which we "
    "will fund entirely from operating cash flow and existing liquidity"
)


def test_similar_dedup_drops_same_turn_near_identical_quote():
    claims = [
        _claim("A", component_id=200, quote=_NEAR_A),
        _claim("B", component_id=200, quote=_NEAR_B),
    ]
    result = dedupe_similar_claims(claims)
    assert len(result) == 1
    assert result[0].claim_id == "A"          # first occurrence kept


def test_similar_dedup_drops_same_turn_substring_fragment():
    """A quote that is a strict sub-span of another claim's quote from the same
    turn is a fragment duplicate -- a length gap the similarity ratio scores
    too low, so substring containment is what catches it."""
    claims = [
        _claim("A", component_id=200, quote=_FRAG_SHORT),
        _claim("B", component_id=200, quote=_FRAG_LONG),
    ]
    result = dedupe_similar_claims(claims)
    assert len(result) == 1
    assert result[0].claim_id == "A"          # first occurrence kept


def test_similar_dedup_substring_caught_in_either_order():
    """Containment is caught whichever sub-span the model emits first."""
    claims = [
        _claim("A", component_id=200, quote=_FRAG_LONG),
        _claim("B", component_id=200, quote=_FRAG_SHORT),
    ]
    result = dedupe_similar_claims(claims)
    assert len(result) == 1
    assert result[0].claim_id == "A"          # first occurrence kept


def test_similar_dedup_substring_only_merges_within_a_turn():
    """A substring match across two different turns is never merged."""
    claims = [
        _claim("A", component_id=200, quote=_FRAG_SHORT),
        _claim("B", component_id=201, quote=_FRAG_LONG),
    ]
    assert len(dedupe_similar_claims(claims)) == 2


def test_similar_dedup_keeps_distinct_claims_from_same_turn():
    """Two genuinely different claims from one turn (compound split) survive."""
    claims = [
        _claim("A", component_id=200, quote="we expect full year revenue to grow about 8 percent"),
        _claim("B", component_id=200, quote="we plan to repurchase two billion dollars of stock"),
    ]
    assert len(dedupe_similar_claims(claims)) == 2


def test_similar_dedup_keeps_near_identical_quotes_from_different_turns():
    claims = [
        _claim("A", component_id=200, quote=_NEAR_A),
        _claim("B", component_id=201, quote=_NEAR_B),
    ]
    assert len(dedupe_similar_claims(claims)) == 2


def test_similar_dedup_does_not_merge_unlocated_claims():
    """component_id 0 means the quote could not be located -- never merge those."""
    claims = [
        _claim("A", component_id=0, quote=_NEAR_A),
        _claim("B", component_id=0, quote=_NEAR_A),
    ]
    assert len(dedupe_similar_claims(claims)) == 2


def test_similar_dedup_keeps_different_types_from_same_turn():
    claims = [
        _claim("A", component_id=200, claim_type="numerical_guidance", quote=_NEAR_A),
        _claim("B", component_id=200, claim_type="capital_allocation", quote=_NEAR_B),
    ]
    assert len(dedupe_similar_claims(claims)) == 2


def test_similar_dedup_empty_list():
    assert dedupe_similar_claims([]) == []
