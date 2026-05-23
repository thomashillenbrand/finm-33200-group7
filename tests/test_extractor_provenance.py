"""Quote back-matching tests for the claim-extraction pipeline (workstream B)."""

from extractor.provenance import locate_quote
from extractor.reader import Turn


def _turn(component_id: int, text: str) -> Turn:
    return Turn(
        component_id=component_id,
        component_order=component_id,
        component_type="Answer",
        speaker_name="Exec",
        speaker_type="Executives",
        text=text,
    )


TURNS = [
    _turn(10, "Thanks for the question. We are very pleased with progress."),
    _turn(11, "We expect full year 2024 revenue to grow about ten percent, "
              "driven by strong demand."),
    _turn(12, "On capital allocation, we plan to repurchase shares next year."),
]


def test_exact_match():
    m = locate_quote(TURNS, "We expect full year 2024 revenue to grow about ten percent")
    assert m.method == "exact"
    assert m.verbatim is True
    assert m.turn.component_id == 11


def test_exact_match_ignores_whitespace_and_case():
    m = locate_quote(TURNS, "  we EXPECT full year 2024   revenue to grow  ")
    assert m.method == "exact"
    assert m.verbatim is True
    assert m.turn.component_id == 11


def test_fuzzy_match_for_lightly_paraphrased_quote():
    # Most of the quote is a contiguous run of turn 11, with a garbled tail --
    # the failure mode the pilot exposed.
    m = locate_quote(
        TURNS,
        "We expect full year 2024 revenue to grow about ten percent in sight",
    )
    assert m.method == "fuzzy"
    assert m.verbatim is False
    assert m.turn.component_id == 11


def test_unmatched_quote_returns_no_turn():
    m = locate_quote(TURNS, "Our mascot won the regional pie eating contest on Tuesday.")
    assert m.method == "unmatched"
    assert m.verbatim is False
    assert m.turn is None


def test_empty_quote_is_unmatched():
    m = locate_quote(TURNS, "   ")
    assert m.method == "unmatched"
    assert m.turn is None
