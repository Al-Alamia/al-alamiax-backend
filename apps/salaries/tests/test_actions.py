from datetime import date
from decimal import Decimal

from apps.attendance.models import PeriodClose
from apps.monthly_basic.models import MonthlyBasic
from apps.notifications.models import Notification
from apps.payroll_config.tests.factories import make_basic
from apps.salaries import services
from apps.salaries.models import Salary, SalaryOverride
from apps.salaries.services import SalaryError
from apps.salaries.tests.factories import KEY, MONTH, give_basic, make_lead_on, window
from apps.salaries.types import SalaryStatus
from apps.subscriptions.tests.factories import make_payment, make_subscription, marketing_dept
from apps.teams.tests.factories import make_plan, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = Decimal
UNIT10 = [{"min_value": 1, "kind": "unit", "value": 10}]


class ActionTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.start, self.end = window()
        self.today = self.end
        self.M = marketing_dept()
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR, department=self.M)
        self.agent = User.objects.create_user(username="mk", password="x", role=UserTypes.AGENT,
                                              department=self.M)
        make_basic(self.agent, MONTH, 3000)
        give_basic(self.agent, 2900)
        make_version(make_plan(PlanKind.PERSONAL, department=self.M), MONTH, UNIT10)
        make_lead_on(self.agent, self.start)
        self.part = services.compute(self.agent, KEY)["parts"][0]["key"]

    def assertErr(self, type_, fn, *a, **kw):
        with self.assertRaises(SalaryError) as cm:
            fn(*a, **kw)
        self.assertEqual(cm.exception.type, type_)
        return cm.exception

    def ov(self, value="5", reason="why", part=None, actor=None, user=None):
        return services.set_override(actor or self.hr, user or self.agent, KEY, part or self.part,
                                     value, reason, today=self.today)

    def give(self, user=None, actor=None):
        return services.give(actor or self.hr, user or self.agent, KEY, today=self.today)

    def test_set_and_replace_override(self):
        s = self.ov("5", " first ")
        o = s.overrides.get()
        self.assertEqual((o.value, o.reason, o.by), (D("5"), "first", self.hr))
        self.ov("7", "second")
        self.assertEqual(SalaryOverride.objects.get().value, D("7"))
        c = services.compute(self.agent, KEY)
        self.assertEqual(c["parts"][0]["amount"], "7.00")

    def test_clear_override(self):
        self.ov()
        s = services.clear_override(self.hr, self.agent, KEY, self.part, today=self.today)
        self.assertFalse(s.overrides.exists())
        services.clear_override(self.hr, self.agent, KEY, self.part, today=self.today)  # idempotent

    def test_override_validation(self):
        for value in ("-1", "abc", "10000000", "nan", "inf"):
            self.assertErr("invalid", self.ov, value=value)
        self.assertErr("invalid", self.ov, reason="  ")
        self.assertErr("invalid", self.ov, part="nope")
        self.assertErr("invalid", services.clear_override, self.hr, self.agent, KEY, "nope",
                       today=self.today)

    def test_override_on_given_refused(self):
        self.give()
        self.assertErr("already_given", self.ov)
        self.assertErr("already_given", services.clear_override, self.hr, self.agent, KEY,
                       self.part, today=self.today)

    def test_future_period(self):
        self.assertErr("future_period", services.set_override, self.hr, self.agent, KEY, self.part,
                       "1", "r", today=date(2026, 9, 1))

    def test_give_snapshots_and_notifies(self):
        before = services.compute(self.agent, KEY)
        s = self.give()
        self.assertEqual(s.status, SalaryStatus.GIVEN)
        self.assertEqual(s.given_by, self.hr)
        self.assertIsNotNone(s.given_at)
        self.assertEqual(f"{s.basic_net:.2f}", before["basic"]["net"])
        self.assertEqual(f"{s.commission:.2f}", before["commission"])
        self.assertEqual(f"{s.total:.2f}", before["total"])
        self.assertEqual(s.parts, before["parts"])
        n = Notification.objects.get(title="Salary")
        self.assertEqual(n.link, f"/salaries/{self.agent.uuid}/{KEY}")
        self.assertIn(KEY, n.message)
        make_lead_on(self.agent, self.start)
        after = services.compute(self.agent, KEY)
        self.assertEqual(after["commission"], before["commission"])
        self.assertEqual(after["total"], before["total"])

    def test_give_requires_basic(self):
        MonthlyBasic.objects.all().delete()
        e = self.assertErr("basic_not_given", self.give)
        self.assertEqual(e.message, f"The basic for {KEY} has not been given.")

    def test_give_before_end(self):
        self.assertErr("period_open", services.give, self.hr, self.agent, KEY,
                       today=date(2026, 10, 24))

    def test_give_missing_rate(self):
        sub = make_subscription(make_lead_on(self.agent, self.start), self.agent, currency="USD")
        make_payment(sub, 100, self.start)
        e = self.assertErr("missing_rate", self.give)
        self.assertIn("exchange rate", e.message)
        self.assertEqual(e.message, f"Set the USD exchange rate for {self.start:%Y-%m}.")

    def test_give_twice(self):
        self.give()
        self.assertErr("already_given", self.give)

    def test_ungive(self):
        self.assertErr("not_given", services.ungive, self.hr, self.agent, KEY)
        self.ov()
        self.give()
        s = services.ungive(self.hr, self.agent, KEY)
        self.assertEqual(s.status, SalaryStatus.DRAFT)
        for f in ("basic_net", "commission", "total", "parts", "given_by", "given_at"):
            self.assertIsNone(getattr(s, f), f)
        self.assertEqual(s.overrides.count(), 1)

    def test_not_included(self):
        other = User.objects.create_user(username="x", password="x", role=UserTypes.AGENT,
                                         department=self.M)
        self.assertErr("not_included", self.give, user=other)

    def test_closed_period_refuses_all(self):
        PeriodClose.objects.create(period=KEY, start=self.start, end=self.end, closed_by=self.hr,
                                   closed_at=self.hr.date_joined)
        self.assertErr("period_closed", self.ov)
        self.assertErr("period_closed", self.give)
        self.assertErr("period_closed", services.ungive, self.hr, self.agent, KEY)

    def test_permissions(self):
        self.assertErr("not_found", self.give, actor=self.agent)  # agents cannot manage anyone
        self.assertErr("forbidden", self.give, user=self.hr, actor=self.hr)  # HR cannot edit self
        self.assertErr("forbidden", self.ov, user=self.hr, actor=self.hr)
        other = Department.objects.create(name="Other")
        mgr = User.objects.create_user(username="mg", password="x", role=UserTypes.MANAGER,
                                       department=other)
        self.assertErr("not_found", self.give, actor=mgr)
        self.assertErr("not_found", services.ungive, mgr, self.agent, KEY)

    def test_give_all(self):
        b = User.objects.create_user(username="b", password="x", role=UserTypes.AGENT, department=self.M)
        make_basic(b, MONTH, 2000)
        done = User.objects.create_user(username="c", password="x", role=UserTypes.AGENT, department=self.M)
        make_basic(done, MONTH, 2000)
        give_basic(done, 2000)
        self.give(user=done)
        res = services.give_all(self.hr, KEY, today=self.today)
        self.assertEqual(res["given"], 1)
        self.assertEqual(len(res["skipped"]), 1)
        sk = res["skipped"][0]
        self.assertEqual(sk["type"], "basic_not_given")
        self.assertEqual(sk["user"]["uuid"], str(b.uuid))
        self.assertTrue(sk["message"])
        self.assertEqual(Salary.objects.filter(status=SalaryStatus.GIVEN).count(), 2)

    def test_give_all_forbidden(self):
        self.assertErr("forbidden", services.give_all, self.agent, KEY, today=self.today)
