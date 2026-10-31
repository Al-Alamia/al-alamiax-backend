from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.attendance.models import AttendanceSettings, PeriodClose
from apps.attendance.services.periods import period_key_for
from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.types import BasicStatus
from apps.monthly_basic.services import period_bounds
from apps.notifications.models import Notification, NotificationRecipient
from apps.payroll_config.tests.factories import make_basic
from apps.treasury.models import Advance, AdvanceInstallment, TreasuryEntry
from apps.treasury.services import TreasuryError, advances
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = Decimal


def next_key(key, n=1):
    y, m = int(key[:4]), int(key[5:])
    idx = y * 12 + (m - 1) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


class AdvanceTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.start_day = AttendanceSettings.get().period_start_day
        self.cur = period_key_for(date.today(), self.start_day)
        make_basic(self.agent, date(2020, 1, 1), 3000)
        self.hr = User.objects.create_user(username="hr", password="x", email="hr@t.com",
                                           role=UserTypes.HR, project=self.project, department=self.department)
        self.manager = User.objects.create_user(username="mgr", password="x", email="m@t.com",
                                                role=UserTypes.MANAGER, project=self.project,
                                                department=self.department)
        other = Department.objects.create(name="Other")
        self.other_mgr = User.objects.create_user(username="mgr2", password="x", email="m2@t.com",
                                                  role=UserTypes.MANAGER, project=self.project, department=other)

    def err(self, type_, fn, *a, **kw):
        with self.assertRaises(TreasuryError) as cm:
            fn(*a, **kw)
        self.assertEqual(cm.exception.type, type_)

    def req(self, by=None, user=None, amount="1000", n=3, start=None, reason="r"):
        return advances.request_advance(by or self.agent, user or self.agent, amount, n,
                                        start or self.cur, reason)

    def close(self, key):
        start, end = period_bounds(key)
        PeriodClose.objects.create(period=key, start=start, end=end, closed_by=self.hr,
                                   closed_at=timezone.now())

    def test_split(self):
        self.assertEqual(advances.split(D("1000"), 3), [D("333.33"), D("333.33"), D("333.34")])
        self.assertEqual(advances.split(D("100"), 1), [D("100")])

    def test_period_keys_wrap_year(self):
        self.assertEqual(advances.period_keys("2026-11", 3), ["2026-11", "2026-12", "2027-01"])

    def test_request_rules(self):
        self.err("over_limit", self.req, amount="3000.01")
        self.err("no_basic", self.req, by=self.hr, user=self.hr)  # hr has no basic; self request
        self.err("past_period", self.req, start=next_key(self.cur, -1))
        self.close(next_key(self.cur, 1))
        self.err("period_closed", self.req, n=3)
        for bad in (0, 7, "x"):
            self.err("invalid", self.req, n=bad)
        self.assertEqual(self.req(n=1).status, "pending")
        self.err("pending_exists", self.req, n=1)

    def test_request_forbidden_and_hr(self):
        self.err("forbidden", self.req, by=self.other_mgr)
        adv = self.req(by=self.hr)
        self.assertEqual(adv.requested_by, self.hr)
        self.assertEqual(adv.user, self.agent)

    def test_request_notifies_approvers_not_requester(self):
        self.req(by=self.hr)
        recips = {r.user_id for r in NotificationRecipient.objects.all()}
        self.assertEqual({u.pk for u in advances.approvers_for(self.agent)},
                         {self.hr.pk, self.manager.pk, self.superuser.pk})
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(recips, {self.manager.pk, self.superuser.pk})

    def test_approve_writes_entry_and_schedule(self):
        adv = self.req()
        Notification.objects.all().delete()
        adv = advances.approve_advance(self.hr, adv, "ok")
        self.assertEqual(adv.status, "approved")
        self.assertEqual(adv.decided_by, self.hr)
        e = TreasuryEntry.objects.get()
        self.assertEqual((e.direction, e.category, e.amount, e.date, e.advance),
                         ("out", "advance", D(1000), date.today(), adv))
        rows = list(AdvanceInstallment.objects.filter(advance=adv).order_by("period"))
        self.assertEqual([r.period for r in rows], advances.period_keys(self.cur, 3))
        self.assertEqual([r.amount for r in rows], advances.split(D(1000), 3))
        self.assertEqual(Notification.objects.count(), 1)

    def test_approve_twice_writes_one_entry(self):
        adv = self.req()
        advances.approve_advance(self.hr, adv)
        self.err("not_pending", advances.approve_advance, self.hr, adv)
        self.assertEqual(TreasuryEntry.objects.count(), 1)

    def test_self_approve_forbidden(self):
        make_basic(self.hr, date(2020, 1, 1), 5000)
        adv = self.req(by=self.hr, user=self.hr, amount="100")
        self.err("forbidden", advances.approve_advance, self.hr, adv)

    def test_manager_scope(self):
        adv = self.req()
        self.err("forbidden", advances.approve_advance, self.other_mgr, adv)
        self.assertEqual(advances.approve_advance(self.manager, adv).status, "approved")

    def test_reject_and_withdraw(self):
        adv = self.req()
        self.err("invalid", advances.reject_advance, self.hr, adv, " ")
        self.assertEqual(advances.reject_advance(self.hr, adv, "no").status, "rejected")
        self.err("not_pending", advances.reject_advance, self.hr, adv, "no")
        adv2 = self.req(by=self.hr)
        self.err("forbidden", advances.withdraw_advance, self.manager, adv2)
        self.assertEqual(advances.withdraw_advance(self.hr, adv2).status, "withdrawn")
        self.err("not_pending", advances.withdraw_advance, self.hr, adv2)
        adv3 = self.req()
        self.assertEqual(advances.withdraw_advance(self.agent, adv3).status, "withdrawn")

    def test_cancel(self):
        adv = advances.approve_advance(self.hr, self.req())
        self.err("invalid", advances.cancel_advance, self.hr, adv, " ")
        pending = self.req()
        self.err("not_approved", advances.cancel_advance, self.hr, pending, "x")
        MonthlyBasic.objects.create(user=self.agent, period=self.cur, status=BasicStatus.GIVEN)
        self.err("deducted", advances.cancel_advance, self.hr, adv, "oops")
        MonthlyBasic.objects.filter(user=self.agent).update(status=BasicStatus.DRAFT)
        adv = advances.cancel_advance(self.hr, adv, "oops")
        self.assertEqual(adv.status, "cancelled")
        self.assertEqual(adv.cancel_reason, "oops")
        self.assertFalse(AdvanceInstallment.objects.filter(advance=adv).exists())
        payout = TreasuryEntry.objects.get(reverses__isnull=True)
        rev = TreasuryEntry.objects.get(reverses__isnull=False)
        self.assertEqual((rev.direction, rev.reverses), ("in", payout))

    def test_installments_for(self):
        advances.approve_advance(self.hr, self.req(amount="900", n=3))
        a2 = Advance.objects.create(user=self.agent, amount=D(600), installments=1, start_period=self.cur,
                                    status="approved")
        AdvanceInstallment.objects.create(advance=a2, period=self.cur, amount=D(600))
        pending = Advance.objects.create(user=self.agent, amount=D(50), installments=1,
                                         start_period=self.cur, status="pending")
        AdvanceInstallment.objects.create(advance=pending, period=self.cur, amount=D(50))
        self.assertEqual(advances.installments_for([self.agent.pk], self.cur), {self.agent.pk: D(900) / 3 + 600})
        self.assertEqual(advances.installments_for([self.agent.pk], next_key(self.cur, 5)), {})
        rows = advances.installment_rows(self.agent, self.cur)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["count"] for r in rows}, {3, 1})
