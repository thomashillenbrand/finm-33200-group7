"""Horizon-resolver tests for the claim-extraction pipeline (workstream B)."""

from datetime import date

import pytest

from extractor.horizon import quarter_of, resolve_horizon

# A Q1 call held in April -- the common relative-horizon anchor.
CALL = date(2022, 4, 20)


@pytest.mark.parametrize(
    "raw, call_date, expected",
    [
        # empty / unresolvable
        ("", CALL, ("", None)),
        ("someday maybe", CALL, ("", None)),
        # absolute fiscal year
        ("full year 2024", CALL, ("FY2024", date(2024, 12, 31))),
        ("fiscal 2025", CALL, ("FY2025", date(2025, 12, 31))),
        ("by the end of 2025", CALL, ("FY2025", date(2025, 12, 31))),
        # absolute quarter
        ("Q2 2024", CALL, ("Q2 2024", date(2024, 6, 30))),
        ("third quarter of 2023", CALL, ("Q3 2023", date(2023, 9, 30))),
        # relative quarter (anchored on call date)
        ("next quarter", CALL, ("Q2 2022", date(2022, 6, 30))),
        ("this quarter", CALL, ("Q2 2022", date(2022, 6, 30))),
        # relative year
        ("next year", date(2022, 1, 26), ("FY2023", date(2023, 12, 31))),
        ("the rest of the year", CALL, ("FY2022", date(2022, 12, 31))),
        # relative multi-year
        ("over the next three years", date(2021, 7, 26), ("FY2024", date(2024, 12, 31))),
        # relative months
        ("next 12 months", CALL, ("12 months", date(2023, 4, 20))),
        # half-year
        ("in the second half", CALL, ("H2 2022", date(2022, 12, 31))),
        # bare quarter, no year -- resolves vs the call's own quarter (Q2 2022)
        ("Q3", CALL, ("Q3 2022", date(2022, 9, 30))),
        ("Q1", CALL, ("Q1 2023", date(2023, 3, 31))),
        ("quarter 2", CALL, ("Q2 2022", date(2022, 6, 30))),
        ("the fourth quarter", CALL, ("Q4 2022", date(2022, 12, 31))),
        ("the first quarter", CALL, ("Q1 2023", date(2023, 3, 31))),
        # bare month, no year
        ("by the end of March", CALL, ("Q1 2023", date(2023, 3, 31))),
        ("by the end of May", CALL, ("Q2 2022", date(2022, 5, 31))),
        # current-year shorthands
        ("by end of year", CALL, ("FY2022", date(2022, 12, 31))),
        ("for the year", CALL, ("FY2022", date(2022, 12, 31))),
        # vague
        ("over the long term", CALL, ("long-term", None)),
    ],
)
def test_resolve_horizon(raw, call_date, expected):
    assert resolve_horizon(raw, call_date) == expected


def test_quarter_of():
    assert quarter_of(date(2022, 1, 26)) == 1
    assert quarter_of(date(2022, 4, 20)) == 2
    assert quarter_of(date(2022, 7, 26)) == 3
    assert quarter_of(date(2022, 10, 19)) == 4


def test_resolve_horizon_keeps_raw_auditable():
    """An unresolved horizon returns empty -- the caller still keeps the raw."""
    period, end = resolve_horizon("at some point", CALL)
    assert period == "" and end is None
