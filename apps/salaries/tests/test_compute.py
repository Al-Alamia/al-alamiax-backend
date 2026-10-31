from datetime import timedelta
from decimal import Decimal

from apps.payroll_config.models import DailyBonusStep
from apps.payroll_config.tests.factories import make_rate, make_rates
from apps.salaries.models import Salary, SalaryOverride
from apps.salaries.services import compute
from apps.salaries.tests.factories import KEY, MONTH, give_basic, make_lead_on, window
from apps.subscriptions.tests.factories import (
    make_lead, make_payment, make_subscription, marketing_dept, sales_dept,
)
from apps.teams.tests.factories import make_plan, make_team, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import DepartmentCodes, UserTypes

D = Decimal
UNIT10 = [{"min_value": 1, "kind": "unit", "value": 10}]


def mk(username, dept):
    return User.objects.create_user(username=username, password="x", email=f"{username}@t.com",
                                    role=UserTypes.AGENT, project=None, department=dept)


def by_key(result):
    return {p["key"]: p for p in result["parts"]}


class ComputeTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.start, self.end = window()
        self.M = marketing_dept()
        self.S = sales_dept()
        self.T = Department.objects.get_or_create(
            code=DepartmentCodes.TECHNICAL, defaults={"name": "Technical"})[0]

    def marketing_agent(self):
        a = mk("mk1", self.M)
        give_basic(a, 2900)
        make_version(make_plan(PlanKind.PERSONAL, department=self.M), MONTH, UNIT10)
        for _ in range(5):
            make_lead_on(a, self.start)
        make_lead_on(a, self.start + timedelta(days=1), stock_market="american")
        rates = make_rates(self.M, MONTH, price=25)
        DailyBonusStep.objects.create(rates=rates, min_leads=5, amount=50)
        return a

    def test_marketing_agent(self):
        r = compute(self.marketing_agent(), KEY)
        self.assertEqual([p["key"] for p in r["parts"]],
                         ["personal:lead_count", "daily_bonus", "american_leads"])
        p = by_key(r)
        self.assertEqual(p["personal:lead_count"]["computed"], "60.00")
        self.assertEqual(p["daily_bonus"]["computed"], "50.00")
        self.assertEqual(p["daily_bonus"]["value"], "1")
        self.assertEqual(p["american_leads"]["computed"], "25.00")
        self.assertEqual(p["american_leads"]["value"], "1")
        self.assertEqual(r["commission"], "135.00")
        self.assertEqual(r["total"], "3035.00")
        self.assertEqual(r["errors"], [])
        pl = p["personal:lead_count"]
        self.assertEqual(pl["tier"]["index"], 0)
        self.assertEqual(pl["variant"], "normal")
        self.assertEqual(pl["currency"], "EGP")
        self.assertIsNone(pl["rate"])
        self.assertEqual(r["basic"], {"net": "2900.00", "status": "draft"})

    def test_american_variant(self):
        a = mk("mk2", self.M)
        give_basic(a, 100)
        make_version(make_plan(PlanKind.PERSONAL, department=self.M), MONTH, [
            {"min_value": 1, "kind": "unit", "value": 10},
            {"variant": "american", "min_value": 1, "kind": "unit", "value": 20}], threshold=50)
        make_lead_on(a, self.start, stock_market="american")
        make_lead_on(a, self.start, stock_market="american")
        make_lead_on(a, self.start, stock_market="saudi")
        p = by_key(compute(a, KEY))["personal:lead_count"]
        self.assertEqual(p["variant"], "american")
        self.assertEqual(p["american_share"], "66.67")
        self.assertEqual(p["computed"], "60.00")

    def test_team_leader(self):
        leader = mk("ld", self.M)
        a1, a2 = mk("a1", self.M), mk("a2", self.M)
        give_basic(leader, 1000)
        team = make_team(self.M, leader=leader, agents=[a1, a2])
        make_version(make_plan(PlanKind.TEAM, team=team, metric="lead_count"), MONTH,
                     [{"min_value": 5, "kind": "flat", "value": 500}])
        for _ in range(3):
            make_lead_on(a1, self.start)
        for _ in range(2):
            make_lead_on(a2, self.start)
        r = compute(leader, KEY)
        p = by_key(r)[f"team:{team.uuid}:lead_count"]
        self.assertEqual(p["kind"], "team")
        self.assertEqual(p["value"], "5")
        self.assertEqual(p["computed"], "500.00")
        self.assertEqual(p["team"], {"uuid": str(team.uuid), "name": team.name})
        self.assertEqual(r["parts"], [p])

    def sales_setup(self):
        s = mk("sl", self.S)
        give_basic(s, 1000)
        make_version(make_plan(PlanKind.PERSONAL, department=self.S, metric="sales_amount"), MONTH,
                     [{"min_value": 1, "kind": "percent", "value": 10}])
        make_payment(make_subscription(make_lead(s), s), "10000", self.start)
        return s

    def test_sales_percent_converted(self):
        s = self.sales_setup()
        make_rate(MONTH, "12.5")
        p = by_key(compute(s, KEY))["personal:sales_amount"]
        self.assertEqual(p["value"], "10000.00")
        self.assertEqual(p["currency"], "SAR")
        self.assertEqual(p["rate"], "12.5000")
        self.assertEqual(p["computed"], "12500.00")

    def test_sales_missing_rate(self):
        r = compute(self.sales_setup(), KEY)
        self.assertIn({"type": "missing_rate", "month": "2026-10", "currency": "SAR"}, r["errors"])
        self.assertEqual(by_key(r)["personal:sales_amount"]["computed"], "0.00")

    def test_team_member_missing_rate(self):
        leader = mk("ld", self.S)
        seller = mk("sl", self.S)
        give_basic(leader, 1000)
        team = make_team(self.S, leader=leader, agents=[seller])
        make_version(make_plan(PlanKind.TEAM, team=team, metric="deal_count"), MONTH,
                     [{"min_value": 1, "kind": "flat", "value": 100}])
        sub = make_subscription(make_lead(seller), seller, currency="USD")
        make_payment(sub, "100", self.start)
        r = compute(leader, KEY)
        self.assertIn({"type": "missing_rate", "month": f"{self.start:%Y-%m}", "currency": "USD"}, r["errors"])
        self.assertEqual(by_key(r)[f"team:{team.uuid}:deal_count"]["computed"], "0.00")

    def test_cs_renewal_counts(self):
        cs = mk("cs", self.S)
        give_basic(cs, 500)
        make_version(make_plan(PlanKind.PERSONAL, department=self.S, metric="deal_count"), MONTH,
                     [{"min_value": 1, "kind": "unit", "value": 100}])
        make_rate(MONTH, "1")
        sub = make_subscription(make_lead(cs), cs, kind="renewal")
        make_payment(sub, "2000", self.start)
        self.assertEqual(by_key(compute(cs, KEY))["personal:deal_count"]["computed"], "100.00")

    def test_technical_basic_only(self):
        t = mk("tc", self.T)
        give_basic(t, 2000)
        r = compute(t, KEY)
        self.assertEqual(r["parts"], [])
        self.assertEqual(r["commission"], "0.00")
        self.assertEqual(r["total"], "2000.00")

    def test_basic_not_given(self):
        t = mk("tc", self.T)
        r = compute(t, KEY)
        self.assertIn({"type": "basic_not_given"}, r["errors"])
        self.assertIsNone(r["total"])
        self.assertIsNone(r["basic"]["net"])

    def test_override_applied(self):
        a = self.marketing_agent()
        sal = Salary.objects.create(user=a, period=KEY)
        SalaryOverride.objects.create(salary=sal, part_key="personal:lead_count",
                                      value=80, reason="fix")
        r = compute(a, KEY)
        p = by_key(r)["personal:lead_count"]
        self.assertEqual(p["computed"], "60.00")
        self.assertEqual(p["amount"], "80.00")
        self.assertEqual(p["override"]["reason"], "fix")
        self.assertEqual(p["override"]["value"], "80.00")
        self.assertEqual(r["commission"], "155.00")

    def test_given_returns_snapshot(self):
        a = mk("mk3", self.M)
        Salary.objects.create(user=a, period=KEY, status="given", basic_net=1, commission=2,
                              total=3, parts=[{"key": "x"}])
        make_lead_on(a, self.start)
        r = compute(a, KEY)
        self.assertEqual(r["parts"], [{"key": "x"}])
        self.assertEqual(r["total"], "3.00")
        self.assertEqual(r["commission"], "2.00")
        self.assertEqual(r["basic"], {"net": "1.00", "status": "given"})
        self.assertEqual(r["errors"], [])
