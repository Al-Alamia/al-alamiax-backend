from datetime import date, datetime
from decimal import Decimal

from apps.attendance.models import PeriodClose
from apps.dashboard.registry import build_all
from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.types import BasicStatus
from apps.reports.tests.base import ReportsTestCase
from apps.treasury.models import Advance, TreasuryEntry
from apps.treasury.types import AdvanceStatus, Category, Direction
from apps.users.models import Lead, User
from apps.users.types import LeadStatuses, UserTypes

NOW = datetime(2026, 11, 10, 12, 0)  # period 2026-11 = 2026-10-26 .. 2026-11-25


def widgets(user, now=NOW):
    return build_all(user, now)["widgets"]


class OrgWidgetsTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.hr = User.objects.create_user(username="hr", password="x", email="hr@t.com",
                                           role=UserTypes.HR, project=self.project,
                                           department=self.department)

    def test_agent_no_org_keys(self):
        w = widgets(self.agent)
        for k in ("payroll_period", "leads", "treasury"):
            self.assertNotIn(k, w)

    def test_hr_sees_payroll_period(self):
        PeriodClose.objects.create(period="2026-10", start=date(2026, 9, 26), end=date(2026, 10, 25),
                                   closed_by=self.hr, closed_at=NOW)
        p = widgets(self.hr)["payroll_period"]
        self.assertEqual(p["current"], {"key": "2026-11", "start": "2026-10-26", "end": "2026-11-25"})
        prev = p["previous"]
        self.assertEqual((prev["key"], prev["start"], prev["end"]),
                         ("2026-10", "2026-09-26", "2026-10-25"))
        self.assertIs(prev["closed"], True)
        self.assertEqual(p["link"], "BASIC_LIST")

    def test_payroll_period_open_and_basics(self):
        from unittest import mock
        with mock.patch("apps.dashboard.widgets.org.included_users",
                        return_value=User.objects.filter(pk__in=[self.agent.pk, self.hr.pk])):
            MonthlyBasic.objects.create(user=self.agent, period="2026-10", status=BasicStatus.GIVEN)
            MonthlyBasic.objects.create(user=self.hr, period="2026-10", status=BasicStatus.DRAFT)
            MonthlyBasic.objects.create(user=self.agent, period="2026-09", status=BasicStatus.GIVEN)
            prev = widgets(self.hr)["payroll_period"]["previous"]
        self.assertIs(prev["closed"], False)
        self.assertEqual((prev["basics_given"], prev["basics_total"]), (1, 2))

    def mk_lead(self, phone, status=LeadStatuses.NEW, when=datetime(2026, 11, 9, 9), hidden=False):
        return Lead.objects.create(user=self.superuser, phone=phone, name=phone, status=status,
                                   date=when, is_hidden=hidden)

    def test_leads_counts_for_admin(self):
        self.mk_lead("1")
        self.mk_lead("2", when=datetime(2026, 11, 10, 8))
        self.mk_lead("3", LeadStatuses.INTERESTED, when=datetime(2026, 11, 10, 9))
        self.mk_lead("4", hidden=True)
        lead = widgets(self.superuser)["leads"]
        self.assertEqual((lead["unassigned"], lead["new_today"]), (2, 2))
        self.assertEqual(lead["by_status"], {s.value: 0 for s in LeadStatuses}
                         | {"new": 2, "interested": 1})
        self.assertEqual(lead["link"], "LEADS")

    def test_new_today_counts_any_status(self):
        self.mk_lead("5", LeadStatuses.ASSIGNED, when=datetime(2026, 11, 10, 8))
        self.mk_lead("6", LeadStatuses.ASSIGNED)  # dated 2026-11-09, not today
        self.assertEqual(widgets(self.superuser)["leads"]["new_today"], 1)

    def test_leads_hidden_for_other_department(self):
        self.assertNotIn("leads", widgets(self.agent))  # department code "other"

    def test_treasury_only_top(self):
        self.assertNotIn("treasury", widgets(self.hr))
        TreasuryEntry.objects.create(direction=Direction.IN, category=Category.INCOME,
                                     amount=Decimal("100"), date=date(2026, 10, 1), details="a")
        TreasuryEntry.objects.create(direction=Direction.IN, category=Category.INCOME,
                                     amount=Decimal("40"), date=date(2026, 11, 2), details="b")
        Advance.objects.create(user=self.agent, amount=Decimal("5"), installments=1,
                               start_period="2026-11", status=AdvanceStatus.PENDING)
        t = widgets(self.superuser)["treasury"]
        self.assertEqual(t["balance"], {"income": "140.00", "outcome": "0.00", "net": "140.00"})
        self.assertEqual(t["month_net"], "40.00")
        self.assertEqual(t["pending_advances"], 1)
        self.assertEqual(t["link"], "TREASURY")
