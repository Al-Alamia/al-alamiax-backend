from datetime import date
from decimal import Decimal

from apps.attendance.models import PeriodClose, PeriodCloseLog
from apps.monthly_basic import services
from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.services import BasicError
from apps.monthly_basic.types import BasicStatus
from apps.notifications.models import Notification
from apps.payroll_config.tests.factories import make_basic
from apps.penalties.tests.factories import make_penalty
from apps.penalties.types import PenaltyKind
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

KEY = "2026-10"
TODAY = date(2026, 10, 26)
D = Decimal


class ActionTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR, department=self.department)
        self.owner = User.objects.create_user(username="own", password="x", role=UserTypes.OWNER)
        self.mgr = User.objects.create_user(username="mg", password="x", role=UserTypes.MANAGER, department=self.department)
        make_basic(self.agent, date(2026, 10, 1), 3000)

    def assertErr(self, type_, fn, *a, **kw):
        with self.assertRaises(BasicError) as cm:
            fn(*a, **kw)
        self.assertEqual(cm.exception.type, type_)
        return cm.exception

    def upd(self, data, user=None, actor=None, today=TODAY, key=KEY):
        return services.update_inputs(actor or self.hr, user or self.agent, key, data, today=today)

    def test_update_inputs_creates_draft(self):
        rec = self.upd({"kpi": "200", "gift": "0"})
        self.assertEqual(rec.status, BasicStatus.DRAFT)
        self.assertEqual(rec.kpi, D("200"))
        self.assertEqual(rec.updated_by, self.hr)
        self.assertEqual(MonthlyBasic.objects.count(), 1)

    def test_update_validation(self):
        for data in ({"kpi": "-1"}, {"gift": "abc"}, {"days_adjustment": "0.3"},
                     {"days_adjustment": "1"}, {"other_deduction": "10"}, {"bogus": "1"}):
            self.assertErr("invalid", self.upd, data)
        self.upd({"kpi": "10"})  # kpi note optional
        rec = self.upd({"days_adjustment": "0.5", "days_adjustment_note": "late"})
        self.assertEqual(rec.days_adjustment, D("0.5"))
        self.assertErr("invalid", self.upd, {"key": 1}, key="bad")

    def test_future_period(self):
        self.assertErr("future_period", self.upd, {"kpi": "1"}, key="2026-12")

    def test_not_included(self):
        self.assertErr("not_included", self.upd, {"kpi": "1"}, user=self.mgr)

    def test_give_before_end(self):
        self.assertErr("period_open", services.give, self.hr, self.agent, KEY, today=date(2026, 10, 24))

    def test_give_snapshots_and_notifies(self):
        before = services.compute(self.agent, KEY)
        rec = services.give(self.hr, self.agent, KEY, today=TODAY)
        self.assertEqual(rec.status, BasicStatus.GIVEN)
        self.assertEqual(rec.given_by, self.hr)
        self.assertIsNotNone(rec.given_at)
        for f in services.SNAPSHOT_FIELDS:
            self.assertEqual(getattr(rec, f), before[f], f)
        n = Notification.objects.get()
        self.assertEqual(n.kind, "payroll")
        self.assertEqual(n.link, f"/users/{self.agent.uuid}/basic-record?period=2026-10")
        self.assertEqual(n.message, f"Your basic for {KEY} has been given: {before['net']:.2f}")
        self.assertErr("already_given", services.give, self.hr, self.agent, KEY, today=TODAY)

    def test_given_snapshot_frozen(self):
        rec = services.give(self.hr, self.agent, KEY, today=TODAY)
        net = rec.net
        make_penalty(self.agent, self.superuser, date=date(2026, 10, 5), kind=PenaltyKind.DAYS, value=D(1))
        self.assertEqual(services.compute(self.agent, KEY, rec)["net"], net)
        self.assertEqual(services.compute_many([self.agent], KEY)[self.agent.pk]["net"], net)
        self.assertErr("already_given", self.upd, {"kpi": "1"})

    def test_ungive(self):
        self.assertErr("not_given", services.ungive, self.hr, self.agent, KEY)
        services.give(self.hr, self.agent, KEY, today=TODAY)
        rec = services.ungive(self.hr, self.agent, KEY)
        self.assertEqual(rec.status, BasicStatus.DRAFT)
        self.assertIsNone(rec.net)
        self.assertIsNone(rec.basic)
        self.assertIsNone(rec.given_by)
        self.assertIsNone(rec.given_at)

    def test_self_edit_forbidden(self):
        make_basic(self.hr, date(2026, 10, 1), 2000)
        make_basic(self.owner, date(2026, 10, 1), 2000)
        self.assertErr("forbidden", self.upd, {"kpi": "1"}, user=self.hr, actor=self.hr)
        self.assertErr("not_found", self.upd, {"kpi": "1"}, user=self.hr, actor=self.agent)

    def test_close_requires_all_given(self):
        a2 = User.objects.create_user(username="a2", password="x", role=UserTypes.AGENT, department=self.department)
        make_basic(a2, date(2026, 10, 1), 2000)
        services.give(self.hr, self.agent, KEY, today=TODAY)
        e = self.assertErr("not_all_given", services.close_period, self.hr, KEY, today=TODAY)
        self.assertIn("1", e.message)
        self.assertErr("forbidden", services.close_period, self.mgr, KEY, today=TODAY)
        services.give(self.hr, a2, KEY, today=TODAY)
        self.assertErr("period_open", services.close_period, self.hr, KEY, today=date(2026, 10, 24))
        pc = services.close_period(self.hr, KEY, today=TODAY)
        self.assertEqual((pc.start, pc.end), (date(2026, 9, 26), date(2026, 10, 25)))
        self.assertEqual(pc.closed_by, self.hr)
        self.assertEqual(PeriodCloseLog.objects.get(action="close").period, KEY)
        self.assertErr("already_closed", services.close_period, self.hr, KEY, today=TODAY)

    def test_closed_blocks_edits(self):
        services.give(self.hr, self.agent, KEY, today=TODAY)
        services.close_period(self.hr, KEY, today=TODAY)
        self.assertErr("period_closed", self.upd, {"kpi": "1"})
        self.assertErr("period_closed", services.give, self.hr, self.agent, KEY, today=TODAY)
        self.assertErr("period_closed", services.ungive, self.hr, self.agent, KEY)

    def test_reopen(self):
        services.give(self.hr, self.agent, KEY, today=TODAY)
        services.close_period(self.hr, KEY, today=TODAY)
        self.assertErr("forbidden", services.reopen_period, self.hr, KEY, "why")
        self.assertErr("invalid", services.reopen_period, self.owner, KEY, " ")
        self.assertIsNone(services.reopen_period(self.owner, KEY, "fix"))
        self.assertFalse(PeriodClose.objects.exists())
        self.assertEqual(PeriodCloseLog.objects.get(action="reopen").reason, "fix")
        self.assertErr("not_closed", services.reopen_period, self.owner, KEY, "again")
