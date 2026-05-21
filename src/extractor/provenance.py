"""Locate an extracted quote back to its source transcript turn.

Pilot finding: when the LLM was asked to *report* the component id of the turn
a quote came from, it was wrong ~60% of the time -- it picked a valid but
incorrect turn, and sometimes paraphrased the quote so it matched no turn at
all. Trusting a model-reported id is unreliable.

Instead we make provenance deterministic: the model returns only the quote, and
``locate_quote`` finds the turn it belongs to by string matching.

  - exact     -- the quote is a substring of a turn (whitespace-normalised,
                 case-insensitive). ``verbatim`` is True.
  - fuzzy     -- the quote is not an exact substring, but a long contiguous run
                 of it appears in one turn (the model lightly paraphrased).
                 ``verbatim`` is False; the turn is the best guess.
  - unmatched -- no turn plausibly contains the quote. ``turn`` is None; the
                 claim is kept but flagged (the model likely fabricated wording).

This pure-stdlib module has no LLM dependency and is unit-tested directly.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from extractor.reader import Turn

# Minimum fraction of the quote that must appear as one contiguous run inside a
# turn for a fuzzy match to be accepted.
_FUZZY_MIN_COVERAGE = 0.60


@dataclass
class QuoteMatch:
    """Result of locating a quote: the source turn (or None) and how it matched."""

    turn: Turn | None
    verbatim: bool          # True only for an exact substring match
    method: str             # "exact" | "fuzzy" | "unmatched"


def _normalize(text: str) -> str:
    """Lowercase and collapse all whitespace runs to single spaces."""
    return " ".join(text.split()).lower()


def locate_quote(turns: list[Turn], quote: str) -> QuoteMatch:
    """Find which turn in ``turns`` the ``quote`` was taken from.

    Args:
        turns: Candidate turns (typically a call's management turns).
        quote: The verbatim quote the model returned for a claim.
    """
    needle = _normalize(quote)
    if not needle:
        return QuoteMatch(None, False, "unmatched")

    # --- Exact: quote is a substring of a turn (whitespace/case-normalised) ---
    for turn in turns:
        if needle in _normalize(turn.text):
            return QuoteMatch(turn, True, "exact")

    # --- Fuzzy: longest contiguous shared run covers most of the quote ---
    best_turn: Turn | None = None
    best_coverage = 0.0
    for turn in turns:
        haystack = _normalize(turn.text)
        matcher = difflib.SequenceMatcher(None, needle, haystack, autojunk=False)
        longest = matcher.find_longest_match(0, len(needle), 0, len(haystack))
        coverage = longest.size / len(needle)
        if coverage > best_coverage:
            best_turn, best_coverage = turn, coverage

    if best_turn is not None and best_coverage >= _FUZZY_MIN_COVERAGE:
        return QuoteMatch(best_turn, False, "fuzzy")

    return QuoteMatch(None, False, "unmatched")
