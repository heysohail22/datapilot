from datetime import date
import pytest
from ..helpers import decision
from app.business.periods import resolve_plan


def plan(today, **kwargs):
    return resolve_plan(decision(**kwargs), today, "Asia/Kolkata", "INR")


def test_previous_month_year_boundary():
    p = plan(date(2026, 1, 15))
    assert (p.period_start, p.period_end_exclusive) == (
        date(2025, 12, 1),
        date(2026, 1, 1),
    )


def test_current_month_short_previous_month():
    p = plan(
        date(2024, 3, 31),
        period_request={"kind": "current_month"},
        comparison="previous_period",
    )
    assert p.comparison_start == date(2024, 2, 1)
    assert p.comparison_end_exclusive == date(2024, 3, 1)
    assert p.period_end_exclusive == date(2024, 3, 31)


def test_complete_month_compares_complete_month():
    p = plan(date(2025, 3, 15), comparison="previous_period")
    assert (p.comparison_start, p.comparison_end_exclusive) == (
        date(2025, 1, 1),
        date(2025, 2, 1),
    )


def test_ytd_leap_year_alignment():
    p = plan(
        date(2024, 3, 1),
        period_request={"kind": "current_year"},
        comparison="previous_year",
    )
    assert p.comparison_end_exclusive == date(2023, 3, 1)


def test_five_completed_years():
    p = plan(
        date(2026, 10, 21),
        metric_id="five_year_trend",
        period_request={"kind": "five_complete_years"},
        granularity="year",
    )
    assert (p.period_start, p.period_end_exclusive) == (
        date(2021, 1, 1),
        date(2026, 1, 1),
    )


def test_no_completed_days():
    with pytest.raises(ValueError):
        plan(date(2026, 10, 1), period_request={"kind": "current_month"})
