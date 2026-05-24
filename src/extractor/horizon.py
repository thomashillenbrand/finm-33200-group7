"""Resolve a claim's stated time horizon to an absolute period and end date.

A forward-looking claim points at some future period. The verification agent
(workstream C) uses that period to choose which subsequent SEC filing to check.
Speakers phrase horizons three ways:

  - absolute   -- "full year 2024", "Q2 2024"
  - relative   -- "next quarter", "over the next three years", "next 12 months"
  - vague      -- "long term"

``resolve_horizon`` converts the raw phrasing to a ``(period_label, end_date)``
pair, anchored on the call date. Per the workstream-B design decision, the
*raw* phrasing is always kept by the caller alongside this resolution, so a
wrong or empty resolution here is auditable -- never silently authoritative.

This resolver is intentionally heuristic. It handles the common phrasings; for
anything it cannot parse it returns ``("", None)`` and the raw text stands.

Assumption: all four project firms (TSLA, AMZN, KO, LLY) are calendar-year
fiscal filers, so fiscal year == calendar year and FY ends Dec 31. Revisit this
function before adding a firm with an off-calendar fiscal year.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

_QUARTER_END_MONTH_DAY = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
_WORD_QUARTER = {"first": 1, "second": 2, "third": 3, "fourth": 4}

# Month name (full + common abbreviation) -> month number, for bare-month
# horizons like "by the end of March".
_MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Number words / digit strings -> int, for "next three years", "18 months", etc.
_NUMBERS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "eighteen": 18,
    "twenty-four": 24, "twentyfour": 24, "thirty-six": 36, "thirtysix": 36,
}


def quarter_of(d: date) -> int:
    """Calendar quarter (1-4) containing date ``d``."""
    return (d.month - 1) // 3 + 1


def _quarter_end(year: int, quarter: int) -> date:
    month, day = _QUARTER_END_MONTH_DAY[quarter]
    return date(year, month, day)


def _norm_year(raw: str) -> int:
    """Normalise a 2- or 4-digit year string to a 4-digit year."""
    year = int(raw)
    return year + 2000 if year < 100 else year


def _as_count(token: str) -> int | None:
    """Parse a count token -- a digit string or a number word."""
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _NUMBERS.get(token)


def _add_months(d: date, months: int) -> date:
    """Return ``d`` advanced by ``months`` calendar months (day clamped)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def resolve_horizon(horizon_raw: str, call_date: date) -> tuple[str, date | None]:
    """Resolve a horizon phrase to ``(period_label, end_date)``.

    Returns ``("", None)`` when the phrase is empty or cannot be resolved.

    Args:
        horizon_raw: The speaker's wording, e.g. "next quarter", "full year 2024".
        call_date: Date of the earnings call -- the anchor for relative phrases.
    """
    # Normalise: lowercase, collapse hyphens and runs of whitespace to a space.
    text = re.sub(r"[-\s]+", " ", (horizon_raw or "").strip().lower())
    if not text:
        return ("", None)

    # --- Absolute quarter: "Q2 2024", "second quarter of 2024" ---
    m = re.search(r"q\s*([1-4])\s*'?\s*(\d{2,4})", text)
    if m:
        quarter, year = int(m.group(1)), _norm_year(m.group(2))
        return (f"Q{quarter} {year}", _quarter_end(year, quarter))
    m = re.search(r"(first|second|third|fourth) quarter (?:of )?'?(\d{2,4})", text)
    if m:
        quarter, year = _WORD_QUARTER[m.group(1)], _norm_year(m.group(2))
        return (f"Q{quarter} {year}", _quarter_end(year, quarter))

    # --- Absolute fiscal year: "FY2024", "full year 2024", "fiscal 2024" ---
    m = re.search(
        r"(?:fy|fiscal(?: year)?|full year|calendar year)\s*'?(\d{2,4})", text
    )
    if not m:
        m = re.search(r"\b(20\d{2})\b", text)  # bare 4-digit year
    if m:
        year = _norm_year(m.group(1))
        return (f"FY{year}", date(year, 12, 31))

    # --- Relative span in months: "next 12 months", "over the next 18 months" ---
    m = re.search(r"(\w+) months?", text)
    if m:
        count = _as_count(m.group(1))
        if count:
            end = _add_months(call_date, count)
            return (f"{count} months", end)

    # --- Relative span in years: "next three years", "1.5 year plan" ---
    # A fractional count ("1.5 years") is resolved through months so it is not
    # mistaken for a whole-year span: a plain ``\w+`` capture cannot hold the
    # dot, so it would grab the "5" out of "1.5" and land five years out.
    m = re.search(r"next ([\d.]+|\w+) years?", text) or re.search(
        r"([\d.]+|\w+) years?", text
    )
    if m:
        token = m.group(1)
        if re.fullmatch(r"\d+\.\d+", token):
            months = round(float(token) * 12)
            return (f"{months} months", _add_months(call_date, months))
        count = _as_count(token)
        if count:
            year = call_date.year + count
            return (f"FY{year}", date(year, 12, 31))

    # --- Relative quarter ---
    current_q = quarter_of(call_date)
    if any(p in text for p in ("next quarter", "coming quarter", "following quarter")):
        # A call reports the just-ended quarter; the next reporting period is
        # the quarter the call itself falls in.
        return (f"Q{current_q} {call_date.year}", _quarter_end(call_date.year, current_q))
    if "this quarter" in text or "current quarter" in text:
        return (f"Q{current_q} {call_date.year}", _quarter_end(call_date.year, current_q))

    # --- Bare quarter, no year: "Q2", "quarter 2", "the fourth quarter" ---
    # Resolve to the next calendar QN at or after the call's own quarter (so a
    # call in Q3 that says "Q2" means next year's Q2).
    bare_q: int | None = None
    m = re.search(r"\bq\s*([1-4])\b", text) or re.search(r"\bquarter ([1-4])\b", text)
    if m:
        bare_q = int(m.group(1))
    else:
        m = re.search(r"\b(first|second|third|fourth) quarter\b", text)
        if m:
            bare_q = _WORD_QUARTER[m.group(1)]
    if bare_q is not None:
        year = call_date.year if bare_q >= current_q else call_date.year + 1
        return (f"Q{bare_q} {year}", _quarter_end(year, bare_q))

    # --- Bare month, no year: "by the end of March", "end of February" ---
    # Resolve to the next occurrence of that month-end at or after the call.
    for name, month_num in _MONTHS.items():
        if re.search(rf"\b{name}\b", text):
            year = (call_date.year if month_num >= call_date.month
                    else call_date.year + 1)
            last_day = calendar.monthrange(year, month_num)[1]
            quarter = (month_num - 1) // 3 + 1
            return (f"Q{quarter} {year}", date(year, month_num, last_day))

    # --- Half-year ---
    # A "next year" qualifier shifts the half into the following calendar year
    # ("the first half of next year"); otherwise the half is read in the call's
    # own year.
    half_year = call_date.year + 1 if "next year" in text else call_date.year
    if re.search(r"(second|back|latter) half", text) or "h2" in text:
        return (f"H2 {half_year}", date(half_year, 12, 31))
    if re.search(r"(first|front) half", text) or "h1" in text:
        return (f"H1 {half_year}", date(half_year, 6, 30))

    # --- Relative year ---
    if "next year" in text or "coming year" in text:
        year = call_date.year + 1
        return (f"FY{year}", date(year, 12, 31))
    if any(
        p in text
        for p in (
            "year end", "year-end", "end of the year", "end of this year",
            "end of year", "rest of the year", "remainder of the year",
            "balance of the year", "full year", "this year", "for the year",
        )
    ):
        return (f"FY{call_date.year}", date(call_date.year, 12, 31))

    # --- Vague long-term ---
    if "long" in text and "term" in text:
        return ("long-term", None)

    return ("", None)
