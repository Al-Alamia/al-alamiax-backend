"""Read-only aggregates: phase 8 salary interface and the subscriptions list summary."""
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Optional

from django.db.models import Min, Sum
from django.db.models.functions import TruncMonth

from apps.payroll_config.services import MissingRate, rate_for, to_sar
from apps.users.types import StockMarkets

from .models import Payment, Subscription
from .types import SubscriptionKind

ZERO = Decimal("0.00")


def _empty():
    return {"deal_count": 0, "sales_amount": ZERO,
            "american_deal_count": 0, "american_sales_amount": ZERO}


def _first_payment_subs(start, end, **filters):
    """Subscriptions matching `filters` whose first payment falls in [start, end]."""
    return (Subscription.objects.filter(**filters)
            .annotate(first_paid=Min("payments__paid_on"))
            .filter(first_paid__gte=start, first_paid__lte=end))


def sales_totals(user, start: date, end: date) -> dict:
    result = _empty()
    result["by_kind"] = {SubscriptionKind.NEW: _empty(), SubscriptionKind.RENEWAL: _empty()}

    def bump(bucket, american, count=0, amount=ZERO):
        bucket["deal_count"] += count
        bucket["sales_amount"] += amount
        if american:
            bucket["american_deal_count"] += count
            bucket["american_sales_amount"] += amount

    deals = (_first_payment_subs(start, end, seller=user)
             .values_list("kind", "market"))
    for kind, market in deals:
        american = market == StockMarkets.AMERICAN
        bump(result, american, count=1)
        bump(result["by_kind"][kind], american, count=1)

    rows = (Payment.objects
            .filter(subscription__seller=user, paid_on__gte=start, paid_on__lte=end)
            .annotate(month=TruncMonth("paid_on"))
            .values("subscription__kind", "subscription__market", "subscription__currency", "month")
            .annotate(total=Sum("amount")))
    for row in rows:
        amount = to_sar(row["total"], row["subscription__currency"], row["month"])
        american = row["subscription__market"] == StockMarkets.AMERICAN
        bump(result, american, amount=amount)
        bump(result["by_kind"][row["subscription__kind"]], american, amount=amount)
    return result


def marketing_subscription_counts(user, start: date, end: date) -> dict:
    markets = list(_first_payment_subs(
        start, end, lead__user=user, kind=SubscriptionKind.NEW).values_list("market", flat=True))
    return {
        "subscription_count": len(markets),
        "american_subscription_count": sum(1 for m in markets if m == StockMarkets.AMERICAN),
    }


def _money(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.01")))


def list_summary(qs, start: Optional[date], end: Optional[date]) -> dict:
    qs = qs.order_by()
    count = qs.count()
    new_count = qs.filter(kind=SubscriptionKind.NEW).count()
    sold = {row["currency"]: row["total"] for row in
            qs.values("currency").annotate(total=Sum("total_amount")).order_by("currency")}

    payments = Payment.objects.filter(subscription__in=qs)
    if start is not None:
        payments = payments.filter(paid_on__gte=start)
    if end is not None:
        payments = payments.filter(paid_on__lte=end)
    rows = (payments.annotate(month=TruncMonth("paid_on"))
            .values("subscription__currency", "month")
            .annotate(total=Sum("amount")).order_by("subscription__currency", "month"))

    collected = defaultdict(lambda: ZERO)
    missing = set()
    sar_total = ZERO
    for row in rows:
        cur, month, total = row["subscription__currency"], row["month"], row["total"]
        collected[cur] += total
        if cur == "SAR":
            sar_total += total
            continue
        for needed in {cur, "SAR"} - {"EGP"}:
            try:
                rate_for(month, needed)
            except MissingRate as e:
                missing.add("{} {:%Y-%m}".format(e.currency, e.month))
        if not missing:
            sar_total += to_sar(total, cur, month)

    return {
        "count": count,
        "new_count": new_count,
        "renewal_count": count - new_count,
        "sold_by_currency": {c: _money(v) for c, v in sold.items()},
        "collected_by_currency": {c: _money(v) for c, v in sorted(collected.items())},
        "collected_sar": None if missing else _money(sar_total),
        "missing_rates": sorted(missing),
    }
