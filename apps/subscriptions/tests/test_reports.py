import datetime as dt
from decimal import Decimal

from apps.payroll_config.services import MissingRate
from apps.payroll_config.tests.factories import make_rate
from apps.subscriptions import reports
from apps.subscriptions.models import Subscription
from apps.subscriptions.tests.factories import (
    make_lead, make_payment, make_subscription, marketing_dept, sales_dept,
)
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date
OCT = (D(2026, 10, 1), D(2026, 10, 31))
NOV = (D(2026, 11, 1), D(2026, 11, 30))


def mk(username, role, dept):
    return User.objects.create_user(
        username=username, password="x", email=f"{username}@t.com", role=role,
        project=None, department=dept,
    )


class ReportBase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.c = mk("r_c", UserTypes.AGENT, sales_dept())
        self.d = mk("r_d", UserTypes.AGENT, sales_dept())
        self.m = mk("r_m", UserTypes.AGENT, marketing_dept())
        self.lead = make_lead(self.m)


class SalesTotalsTests(ReportBase):
    def test_deal_counted_in_period_of_first_payment(self):
        sub = make_subscription(self.lead, self.c)
        make_payment(sub, "100", D(2026, 10, 5))
        make_payment(sub, "200", D(2026, 11, 5))
        oct_ = reports.sales_totals(self.c, *OCT)
        nov = reports.sales_totals(self.c, *NOV)
        self.assertEqual(oct_["deal_count"], 1)
        self.assertEqual(oct_["sales_amount"], Decimal("100.00"))
        self.assertEqual(nov["deal_count"], 0)
        self.assertEqual(nov["sales_amount"], Decimal("200.00"))

    def test_usd_converted_and_missing_rate(self):
        sub = make_subscription(self.lead, self.c, currency="USD")
        make_payment(sub, "100", D(2026, 10, 5))
        with self.assertRaises(MissingRate):
            reports.sales_totals(self.c, *OCT)
        make_rate(D(2026, 10, 1), "50", "USD")
        make_rate(D(2026, 10, 1), "13", "SAR")
        self.assertEqual(reports.sales_totals(self.c, *OCT)["sales_amount"], Decimal("384.62"))

    def test_american_split_by_kind_and_cancelled(self):
        s1 = make_subscription(self.lead, self.c, market="american")
        make_payment(s1, "100", D(2026, 10, 5))
        s2 = make_subscription(self.lead, self.c, kind="renewal")
        make_payment(s2, "40", D(2026, 10, 6))
        s2.cancelled_at = dt.datetime(2026, 10, 7)
        s2.save()
        other = make_subscription(self.lead, self.d)
        make_payment(other, "999", D(2026, 10, 6))
        r = reports.sales_totals(self.c, *OCT)
        self.assertEqual(r["deal_count"], 2)
        self.assertEqual(r["sales_amount"], Decimal("140.00"))
        self.assertEqual(r["american_deal_count"], 1)
        self.assertEqual(r["american_sales_amount"], Decimal("100.00"))
        self.assertEqual(r["by_kind"]["new"]["deal_count"], 1)
        self.assertEqual(r["by_kind"]["new"]["american_sales_amount"], Decimal("100.00"))
        self.assertEqual(r["by_kind"]["renewal"]["deal_count"], 1)
        self.assertEqual(r["by_kind"]["renewal"]["sales_amount"], Decimal("40.00"))
        self.assertEqual(r["by_kind"]["renewal"]["american_deal_count"], 0)
        self.assertEqual(reports.sales_totals(self.d, *OCT)["deal_count"], 1)

    def test_empty(self):
        r = reports.sales_totals(self.c, *OCT)
        self.assertEqual(r["deal_count"], 0)
        self.assertEqual(r["sales_amount"], Decimal("0.00"))


class MarketingCountsTests(ReportBase):
    def test_counts(self):
        s1 = make_subscription(self.lead, self.c)
        make_payment(s1, "10", D(2026, 10, 5))
        s2 = make_subscription(self.lead, self.c, market="american")
        make_payment(s2, "10", D(2026, 10, 6))
        s3 = make_subscription(self.lead, self.c, kind="renewal")
        make_payment(s3, "10", D(2026, 10, 7))
        s4 = make_subscription(self.lead, self.c)
        make_payment(s4, "10", D(2026, 9, 7))
        make_payment(s4, "10", D(2026, 10, 8))
        make_subscription(self.lead, self.c)  # no payments
        r = reports.marketing_subscription_counts(self.m, *OCT)
        self.assertEqual(r, {"subscription_count": 2, "american_subscription_count": 1})
        self.assertEqual(reports.marketing_subscription_counts(self.c, *OCT)["subscription_count"], 0)


class ListSummaryTests(ReportBase):
    def test_per_month_conversion_and_missing(self):
        sub = make_subscription(self.lead, self.c, currency="USD", total_amount=Decimal("500"))
        make_payment(sub, "100", D(2026, 10, 5))
        make_payment(sub, "100", D(2026, 11, 5))
        sar = make_subscription(self.lead, self.c, kind="renewal", total_amount=Decimal("300"))
        make_payment(sar, "30", D(2026, 10, 9))
        make_rate(D(2026, 10, 1), "50", "USD")
        make_rate(D(2026, 10, 1), "13", "SAR")
        make_rate(D(2026, 11, 1), "52", "USD")
        make_rate(D(2026, 11, 1), "13", "SAR")
        qs = Subscription.objects.all()
        s = reports.list_summary(qs, D(2026, 10, 1), D(2026, 11, 30))
        self.assertEqual((s["count"], s["new_count"], s["renewal_count"]), (2, 1, 1))
        self.assertEqual(s["sold_by_currency"], {"USD": "500.00", "SAR": "300.00"})
        self.assertEqual(s["collected_by_currency"], {"USD": "200.00", "SAR": "30.00"})
        # 100*50/13 = 384.62 ; 100*52/13 = 400.00 ; + 30
        self.assertEqual(s["collected_sar"], "814.62")
        self.assertEqual(s["missing_rates"], [])
        # Oct only
        s = reports.list_summary(qs, *OCT)
        self.assertEqual(s["collected_by_currency"], {"USD": "100.00", "SAR": "30.00"})
        # unbounded
        s = reports.list_summary(qs, None, None)
        self.assertEqual(s["collected_by_currency"]["USD"], "200.00")

    def test_missing_rate_reported(self):
        sub = make_subscription(self.lead, self.c, currency="USD")
        make_payment(sub, "100", D(2026, 10, 5))
        make_payment(sub, "100", D(2026, 11, 5))
        make_rate(D(2026, 10, 1), "50", "USD")
        make_rate(D(2026, 10, 1), "13", "SAR")
        make_rate(D(2026, 11, 1), "13", "SAR")
        s = reports.list_summary(Subscription.objects.all(), None, None)
        self.assertIsNone(s["collected_sar"])
        self.assertEqual(s["missing_rates"], ["USD 2026-11"])
        self.assertEqual(s["collected_by_currency"], {"USD": "200.00"})

    def test_empty(self):
        s = reports.list_summary(Subscription.objects.none(), None, None)
        self.assertEqual(s["count"], 0)
        self.assertEqual(s["collected_sar"], "0.00")
        self.assertEqual(s["sold_by_currency"], {})
