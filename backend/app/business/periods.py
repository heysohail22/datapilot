"""Calendar boundaries are calculated in Python, never guessed by an LLM."""

from calendar import monthrange
from datetime import date, timedelta
from app.agent.contracts import BusinessPlan, RouterDecision


def shift_month(day: date, delta: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + delta, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def shift_year(day: date, delta: int) -> date:
    return date(
        day.year + delta,
        day.month,
        min(day.day, monthrange(day.year + delta, day.month)[1]),
    )


def resolve_plan(
    decision: RouterDecision, today: date, timezone: str, currency: str
) -> BusinessPlan:
    p = decision.period_request
    if p is None or decision.metric_id is None:
        raise ValueError("A metric and period are required")
    month_start = today.replace(day=1)
    year_start = date(today.year, 1, 1)
    # Exclude the incomplete current day for stable daily comparisons.
    ranges = {
        "previous_calendar_month": (shift_month(month_start, -1), month_start),
        "current_month": (month_start, today),
        "previous_calendar_year": (date(today.year - 1, 1, 1), year_start),
        "current_year": (year_start, today),
        "five_complete_years": (date(today.year - 5, 1, 1), year_start),
        "custom": (p.start, p.end_exclusive),
    }
    start, end = ranges[p.kind]
    if start is None or end is None or start >= end:
        raise ValueError(
            "There are no completed days in this period; choose a completed period."
        )
    assumptions = [
        "Calendar periods in the business timezone; start inclusive and end exclusive."
    ]
    if p.kind in {"current_month", "current_year"}:
        assumptions.append(
            "Current period includes completed days only; today is excluded."
        )
    cs = ce = None
    if decision.comparison == "previous_year":
        cs = shift_year(start, -1)
        ce = shift_year(end - timedelta(days=1), -1) + timedelta(days=1)
    elif decision.comparison == "previous_period":
        if p.kind in {"current_month", "previous_calendar_month"}:
            cs = shift_month(start, -1)
            previous_end = shift_month(start, 0)
            ce = (
                previous_end
                if p.kind == "previous_calendar_month"
                else min(cs + (end - start), previous_end)
            )
        elif p.kind in {"current_year", "previous_calendar_year"}:
            cs = shift_year(start, -1)
            ce = shift_year(end - timedelta(days=1), -1) + timedelta(days=1)
        else:
            cs, ce = start - (end - start), start
        assumptions.append(
            "Comparison uses equivalent completed days, capped to valid prior-period dates."
        )
    if decision.metric_id == "revenue_growth" and cs is None:
        raise ValueError(
            "Choose the prior period or prior year for the growth comparison."
        )
    return BusinessPlan(
        normalized_question=decision.normalized_question,
        metric_id=decision.metric_id,
        period_start=start,
        period_end_exclusive=end,
        comparison_start=cs,
        comparison_end_exclusive=ce,
        comparison=decision.comparison,
        granularity=decision.granularity,
        filters=decision.filters,
        timezone=timezone,
        currency=currency,
        assumptions=assumptions,
    )
