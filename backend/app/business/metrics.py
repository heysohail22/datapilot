"""Versioned business meanings, independent of a provider or graph."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MetricDefinition:
    id: str
    meaning: str
    formula: str
    prerequisites: str
    unit: str
    grain: str = "Aggregate the complete eligible dataset; avoid duplicate order totals in line joins."
    null_behavior: str = (
        "Missing history is unknown, not zero. A zero denominator produces null."
    )
    groupings: tuple[str, ...] = ("total", "day", "month", "year")
    version: str = "1"

    def as_dict(self):
        return asdict(self)


METRICS = {
    m.id: m
    for m in [
        MetricDefinition(
            "revenue",
            "Net eligible sales",
            "Sum sales net of discounts and refunds; exclude tax and cancelled orders.",
            "Document sales grain, discount/refund/tax treatment and date column.",
            "currency",
        ),
        MetricDefinition(
            "order_count",
            "Eligible orders",
            "COUNT(DISTINCT order identifier), excluding cancelled orders.",
            "Order identifier, status, order date.",
            "count",
        ),
        MetricDefinition(
            "average_order_value",
            "Revenue per eligible order",
            "Net revenue / NULLIF(distinct eligible order count, 0).",
            "Mapped revenue and order count.",
            "currency",
        ),
        MetricDefinition(
            "gross_margin",
            "Gross profit as a percent of revenue",
            "100 * (SUM(net revenue) - SUM(historical COGS)) / NULLIF(SUM(net revenue), 0). Never average row margins.",
            "Historical cost at sale, net sales, matching aggregation grain.",
            "percent",
        ),
        MetricDefinition(
            "revenue_growth",
            "Revenue change between comparable periods",
            "100 * (current revenue - prior revenue) / NULLIF(prior revenue, 0). Return both amounts. Negative baselines need explanation.",
            "Mapped net revenue with complete comparable periods.",
            "percent",
        ),
        MetricDefinition(
            "five_year_trend",
            "Annual revenue over five completed calendar years",
            "Group net revenue by year. Annual growth uses LAG; distinguish absent history from zero.",
            "Five years of dated net sales; disclose missing years.",
            "currency",
        ),
        MetricDefinition(
            "net_profit",
            "Profit after costs and operating expenses",
            "Net revenue - historical COGS - applicable operating expenses.",
            "Dated expenses and historical COGS; unavailable without both.",
            "currency",
        ),
    ]
}
