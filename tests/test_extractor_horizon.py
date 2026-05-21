from datetime import date

from extractor.horizon import resolve_horizon


def test_next_quarter_q4_earnings_call():
    # Q4 earnings call in Feb → guidance is for Q1 (Jan–Mar)
    start, end = resolve_horizon(date(2025, 2, 6), "next_quarter")
    assert start == date(2025, 1, 1)
    assert end == date(2025, 3, 31)


def test_next_quarter_q1_earnings_call():
    # Q1 earnings call in April → guidance is for Q2 (Apr–Jun)
    start, end = resolve_horizon(date(2024, 4, 30), "next_quarter")
    assert start == date(2024, 4, 1)
    assert end == date(2024, 6, 30)


def test_next_year_returns_full_calendar_year():
    start, end = resolve_horizon(date(2024, 4, 30), "next_year")
    assert start == date(2025, 1, 1)
    assert end == date(2025, 12, 31)


def test_multi_year_spans_three_years():
    start, end = resolve_horizon(date(2023, 10, 26), "multi_year")
    assert start == date(2024, 1, 1)
    assert end == date(2026, 12, 31)


def test_unspecified_returns_none():
    assert resolve_horizon(date(2024, 1, 30), "unspecified") is None
