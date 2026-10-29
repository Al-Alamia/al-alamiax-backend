from datetime import date, datetime
from decimal import Decimal

from apps.payroll_config.models import DailyBonusStep
from apps.payroll_config.tests.factories import make_rates
from apps.users.models import Lead
from .base import BaseUserTestCase


class UserLeadsPlusTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.agent.department = self.department
        self.agent.save()
        self.authenticate_as(self.agent)
        n = 0
        for day, count in ((3, 6), (4, 12), (5, 3)):
            for _ in range(count):
                n += 1
                Lead.objects.create(user=self.agent, phone=f"0100{n:07d}", date=datetime(2026, 11, day, 10))

    def summary(self):
        return self.client.post(f"/api/users/user-leads?user_uuid={self.agent.uuid}&month=11&year=2026")

    def test_plus_from_rate_sheet(self):
        rates = make_rates(self.department, date(2026, 11, 1), price=Decimal("30"))
        DailyBonusStep.objects.create(rates=rates, min_leads=5, amount=50)
        DailyBonusStep.objects.create(rates=rates, min_leads=10, amount=100)
        r = self.summary()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["total"], 21)
        self.assertEqual(r.data["plus"], 2)
        self.assertEqual(Decimal(str(r.data["plus_value"])), Decimal("150"))
        self.assertEqual(Decimal(str(r.data["plus_price"])), Decimal("50"))
        self.assertEqual(Decimal(str(r.data["american_leads_price"])), Decimal("30"))

    def test_no_sheet_gives_zeros(self):
        r = self.summary()
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data["plus"], r.data["plus_value"], r.data["plus_price"],
                          r.data["american_leads_price"]), (0, 0, 0, 0))
