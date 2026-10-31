from datetime import timedelta
from decimal import Decimal

from apps.payroll_config.services import MissingRate
from apps.salaries.metrics import metric_values
from apps.salaries.tests.factories import make_lead_on, window
from apps.subscriptions.tests.factories import (
    make_lead, make_payment, make_subscription, marketing_dept, sales_dept,
)
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = Decimal


def mk(username, dept):
    return User.objects.create_user(username=username, password="x", email=f"{username}@t.com",
                                    role=UserTypes.AGENT, project=None, department=dept)


class MetricTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.start, self.end = window()
        self.m = mk("mk1", marketing_dept())
        self.s = mk("sl1", sales_dept())

    def test_leads_counted_for_creator_in_window(self):
        day = timedelta(days=1)
        for _ in range(5):
            make_lead_on(self.m, self.start)
        make_lead_on(self.m, self.start + day, stock_market="american")
        make_lead_on(self.m, self.start, is_hidden=True)
        make_lead_on(self.m, self.end + day)
        make_lead_on(self.s, self.start)
        r = metric_values(self.m, self.start, self.end)
        self.assertEqual(r["values"]["lead_count"], 6)
        self.assertEqual(r["american_lead_count"], 1)
        self.assertEqual(r["leads_by_day"], {self.start: 5, self.start + day: 1})
        self.assertEqual(round(r["shares"]["lead_count"], 2), D("16.67"))

    def test_no_leads_share_none(self):
        r = metric_values(self.m, self.start, self.end)
        self.assertIsNone(r["shares"]["lead_count"])
        self.assertEqual(r["values"]["lead_count"], 0)

    def test_sales_metrics_from_payments(self):
        lead = make_lead(self.m)
        us = make_subscription(lead, self.s, market="american")
        make_payment(us, "3000", self.start)
        sa = make_subscription(lead, self.s)
        make_payment(sa, "1000", self.start)
        r = metric_values(self.s, self.start, self.end)
        self.assertEqual(r["values"]["sales_amount"], 4000)
        self.assertEqual(r["values"]["sales_american_amount"], 3000)
        self.assertEqual(r["values"]["deal_count"], 2)
        self.assertEqual(r["shares"]["sales_amount"], 75)
        self.assertEqual(r["shares"]["deal_count"], 50)
        self.assertIsNone(r["shares"]["sales_american_amount"])

    def test_subscription_counts_for_lead_creator(self):
        lead = make_lead(self.m)
        make_lead(self.m)
        sub = make_subscription(lead, self.s, market="american")
        make_payment(sub, "500", self.start)
        r = metric_values(self.m, self.start, self.end)
        self.assertEqual(r["values"]["subscription_count"], 1)
        self.assertEqual(r["values"]["american_subscription_count"], 1)
        self.assertEqual(r["shares"]["subscription_count"], 100)
        self.assertIsNone(r["shares"]["american_subscription_count"])

    def test_missing_rate_propagates(self):
        sub = make_subscription(make_lead(self.m), self.s, currency="USD")
        make_payment(sub, "100", self.start)
        with self.assertRaises(MissingRate):
            metric_values(self.s, self.start, self.end)
