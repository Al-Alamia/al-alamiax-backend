from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Optional

from apps.subscriptions.reports import marketing_subscription_counts, sales_totals
from apps.teams.types import PlanMetric
from apps.users.models import Lead
from apps.users.types import StockMarkets

ZERO = Decimal("0")


def _share(part, whole) -> Optional[Decimal]:
    whole = Decimal(whole)
    if not whole:
        return None
    return Decimal(part) * 100 / whole


def metric_values(user, start: date, end: date) -> dict:
    leads = Lead.objects.filter(user=user, is_hidden=False,
                                date__date__gte=start, date__date__lte=end)
    lead_dates = list(leads.values_list("date", "stock_market"))
    leads_by_day = dict(Counter(d.date() for d, _ in lead_dates))
    lead_count = len(lead_dates)
    american_lead_count = sum(1 for _, m in lead_dates if m == StockMarkets.AMERICAN)

    sales = sales_totals(user, start, end)
    subs = marketing_subscription_counts(user, start, end)

    values = {
        PlanMetric.LEAD_COUNT.value: Decimal(lead_count),
        PlanMetric.DEAL_COUNT.value: Decimal(sales["deal_count"]),
        PlanMetric.SALES_AMOUNT.value: Decimal(sales["sales_amount"]),
        PlanMetric.SALES_AMERICAN_AMOUNT.value: Decimal(sales["american_sales_amount"]),
        PlanMetric.SUBSCRIPTION_COUNT.value: Decimal(subs["subscription_count"]),
        PlanMetric.AMERICAN_SUBSCRIPTION_COUNT.value: Decimal(subs["american_subscription_count"]),
    }
    shares = {
        PlanMetric.LEAD_COUNT.value: _share(american_lead_count, lead_count),
        PlanMetric.DEAL_COUNT.value: _share(sales["american_deal_count"], sales["deal_count"]),
        PlanMetric.SALES_AMOUNT.value: _share(sales["american_sales_amount"], sales["sales_amount"]),
        PlanMetric.SALES_AMERICAN_AMOUNT.value: None,
        PlanMetric.SUBSCRIPTION_COUNT.value: _share(subs["american_subscription_count"],
                                                    subs["subscription_count"]),
        PlanMetric.AMERICAN_SUBSCRIPTION_COUNT.value: None,
    }
    return {
        "values": values,
        "shares": shares,
        "american_lead_count": american_lead_count,
        "leads_by_day": leads_by_day,
    }
