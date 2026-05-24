"""Tests for the source-context column (workstream B).

``_source_context`` gives workstream C the source turn plus the turns
immediately before and after it (same call), so a sparse ``verbatim_quote``
can be read in context -- notably, a Q&A answer's preceding turn is the
analyst's question. ``_enrich`` writes the result to ``Claim.source_context``.
"""

from datetime import date, datetime, timezone

from extractor.extract import _enrich, _source_context
from extractor.reader import EarningsCall, Turn
from schemas import ExtractedClaim

# A four-turn call: operator boilerplate, an analyst question, the executive's
# answer (the usual claim-bearing turn), then a second analyst question.
_TURNS = [
    Turn(
        component_id=10,
        component_order=1,
        component_type="Operator",
        speaker_name="Operator",
        speaker_type="Operator",
        text="Our first question comes from the line of Pat Lee.",
    ),
    Turn(
        component_id=20,
        component_order=2,
        component_type="Question",
        speaker_name="Pat Lee",
        speaker_type="Analysts",
        text="What are you expecting for capital expenditure next year?",
    ),
    Turn(
        component_id=30,
        component_order=3,
        component_type="Answer",
        speaker_name="Jane Doe",
        speaker_type="Executives",
        text="We plan to spend about $4 billion on capex in 2025.",
    ),
    Turn(
        component_id=40,
        component_order=4,
        component_type="Question",
        speaker_name="Sam Roe",
        speaker_type="Analysts",
        text="And how should we think about the dividend?",
    ),
]


def _call(turns: list[Turn] | None = None) -> EarningsCall:
    return EarningsCall(
        ticker="TSLA",
        company="Tesla, Inc.",
        transcript_id=999,
        headline="Tesla, Inc., Q1 2024 Earnings Call, Apr 23, 2024",
        call_date=date(2024, 4, 23),
        fiscal_period="Q1 2024",
        turns=list(_TURNS if turns is None else turns),
    )


def test_source_context_includes_previous_and_next_turn():
    """For a mid-call turn, the context is the previous, source, and next turn."""
    context = _source_context(_call(), component_id=30)
    assert "What are you expecting for capital expenditure" in context  # previous
    assert "$4 billion on capex" in context                            # source
    assert "how should we think about the dividend" in context         # next


def test_source_context_clamps_at_call_start():
    """The first turn has no predecessor -- context is just it and its successor."""
    context = _source_context(_call(), component_id=10)
    assert "first question comes from the line" in context   # source (turn 1)
    assert "capital expenditure next year" in context        # next (turn 2)
    assert "$4 billion" not in context                       # turn 3 excluded


def test_source_context_clamps_at_call_end():
    """The last turn has no successor -- context is its predecessor and it."""
    context = _source_context(_call(), component_id=40)
    assert "$4 billion on capex" in context                  # previous (turn 3)
    assert "how should we think about the dividend" in context  # source (turn 4)
    assert "first question comes from the line" not in context  # turn 1 excluded


def test_source_context_empty_for_unlocated_claim():
    """component_id 0 means the quote could not be located -- no context."""
    assert _source_context(_call(), component_id=0) == ""


def test_source_context_empty_for_unknown_component_id():
    """A component_id absent from the call yields an empty context, not an error."""
    assert _source_context(_call(), component_id=99999) == ""


def test_source_context_labels_each_turn_with_speaker_and_type():
    """Each turn in the context is prefixed with its speaker and component type."""
    context = _source_context(_call(), component_id=30)
    assert "Pat Lee (Question):" in context
    assert "Jane Doe (Answer):" in context
    assert "Sam Roe (Question):" in context


def test_enrich_populates_source_context_with_the_question_turn():
    """A claim located to the executive's answer carries the analyst question
    that prompted it in ``source_context``."""
    extracted = ExtractedClaim(
        claim_type="numerical_guidance",
        verbatim_quote="We plan to spend about $4 billion on capex in 2025.",
        summary="The company expects roughly $4B of 2025 capex.",
        horizon_raw="2025",
    )
    claim = _enrich(
        extracted,
        _call(),
        model_name="openai:gpt-4o-mini",
        extracted_at=datetime.now(timezone.utc),
    )
    assert claim.component_id == 30                                   # located
    assert "capital expenditure next year" in claim.source_context    # the question
    assert "$4 billion on capex" in claim.source_context             # the answer


def test_enrich_leaves_source_context_empty_for_an_unlocatable_quote():
    """A quote that matches no management turn has component_id 0 and so an
    empty source_context."""
    extracted = ExtractedClaim(
        claim_type="numerical_guidance",
        verbatim_quote="A sentence that appears nowhere in the transcript at all.",
        summary="An unlocatable claim.",
        horizon_raw="2025",
    )
    claim = _enrich(
        extracted,
        _call(),
        model_name="openai:gpt-4o-mini",
        extracted_at=datetime.now(timezone.utc),
    )
    assert claim.component_id == 0
    assert claim.source_context == ""
