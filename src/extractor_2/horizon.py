"""Resolve a claim's horizon label into an absolute date range.

For earnings calls the convention is:
  next_quarter  → the calendar quarter the call falls in (the one being guided for)
  next_year     → the full next calendar year
  multi_year    → next year through 3 years out
  unspecified   → no date range (returns None)
"""

from __future__ import annotations

import calendar
from datetime import date


def _quarter_bounds(d: date) -> tuple[date, date]:
    """Return (start, end) of the calendar quarter containing d."""
    q = (d.month - 1) // 3        # 0 = Q1, 1 = Q2, 2 = Q3, 3 = Q4
    start_month = q * 3 + 1
    end_month = start_month + 2
    end_day = calendar.monthrange(d.year, end_month)[1]
    return date(d.year, start_month, 1), date(d.year, end_month, end_day)


def resolve_horizon(
    call_date: date, horizon: str
) -> tuple[date, date] | None:
    """Return (start, end) absolute date range for a claim horizon.

    Returns None for 'unspecified'.
    """
    if horizon == "next_quarter":
        return _quarter_bounds(call_date)

    if horizon == "next_year":
        y = call_date.year + 1
        return date(y, 1, 1), date(y, 12, 31)

    if horizon == "multi_year":
        y = call_date.year + 1
        return date(y, 1, 1), date(y + 2, 12, 31)

    return None  # unspecified
