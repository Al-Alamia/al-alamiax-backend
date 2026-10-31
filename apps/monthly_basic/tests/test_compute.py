from datetime import date, datetime
from decimal import Decimal

from apps.attendance.models import AttendanceDay, AttendanceSettings
from apps.attendance.types import DayStatus
from apps.monthly_basic import services
from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.types import BasicStatus
from apps.payroll_config.models import BasicSalary
from apps.payroll_config.tests.factories import make_basic
from apps.penalties.tests.factories import make_penalty
from apps.penalties.types import PenaltyKind
from apps.treasury.models import Advance, AdvanceInstallment
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

KEY = "2026-10"
D = Decimal


def day(user, d, deduction=0.0, status=DayStatus.PRESENT):
    return AttendanceDay.objects.create(
        user=user, date=d, status=status, deduction_days=deduction, evaluated_at=datetime(2026, 10, 30))


class ComputeTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        make_basic(self.agent, date(2026, 10, 1), 3000)

    def test_compute_terms(self):
        day(self.agent, date(2026, 9, 27), 1.0)
        day(self.agent, date(2026, 9, 28), 0.5)
        day(self.agent, date(2026, 9, 25), 1.0)
        day(self.agent, date(2026, 10, 1), 0, DayStatus.LEAVE)
        make_penalty(self.agent, self.superuser, date=date(2026, 10, 1), kind=PenaltyKind.DAYS, value=D(1))
        make_penalty(self.agent, self.superuser, date=date(2026, 10, 2), kind=PenaltyKind.MONEY, value=D(100))
        voided = make_penalty(self.agent, self.superuser, date=date(2026, 10, 3), kind=PenaltyKind.MONEY, value=D(999))
        voided.voided_at = timezone.now()
        voided.save()
        rec = MonthlyBasic.objects.create(
            user=self.agent, period=KEY, kpi=200, gift=50, days_adjustment=D("-0.5"),
            days_adjustment_note="x", other_deduction=25, other_deduction_note="y")
        r = services.compute(self.agent, KEY, rec)
        self.assertEqual(r["attendance_days"], D("1.50"))
        self.assertEqual(r["penalty_days"], D("1.00"))
        self.assertEqual(r["deduction_days"], D("2.00"))
        self.assertEqual(r["daily_rate"], D("100.00"))
        self.assertEqual(r["deduction_amount"], D("200.00"))
        self.assertEqual(r["penalty_money"], D("100.00"))
        self.assertEqual(r["net"], D("2925.00"))
        self.assertEqual(r["leave_days"], D("1"))

    def test_deduction_days_not_negative(self):
        rec = MonthlyBasic.objects.create(user=self.agent, period=KEY, days_adjustment=D("-5"),
                                          days_adjustment_note="x")
        self.assertEqual(services.compute(self.agent, KEY, rec)["deduction_days"], D("0"))

    def test_negative_net_allowed(self):
        rec = MonthlyBasic.objects.create(user=self.agent, period=KEY, other_deduction=5000,
                                          other_deduction_note="x")
        self.assertEqual(services.compute(self.agent, KEY, rec)["net"], D("-2000.00"))

    def test_rounding(self):
        BasicSalary.objects.filter(user=self.agent).update(amount=1000)
        day(self.agent, date(2026, 10, 1), 1.0)
        r = services.compute(self.agent, KEY)
        self.assertEqual(r["daily_rate"], D("33.33"))
        self.assertEqual(r["deduction_amount"], D("33.33"))

    def test_salary_month_is_period_month(self):
        make_basic(self.agent, date(2026, 9, 1), 2000)
        BasicSalary.objects.filter(user=self.agent, effective_from=date(2026, 10, 1)).update(amount=4000)
        self.assertEqual(services.compute(self.agent, KEY)["basic"], D("4000.00"))

    def test_invalid_key(self):
        with self.assertRaises(services.BasicError) as cm:
            services.period_bounds("2026-13")
        self.assertEqual(cm.exception.type, "invalid")
        self.assertEqual(cm.exception.status, 400)
        self.assertEqual(services.month_of(KEY), date(2026, 10, 1))
        self.assertEqual(services.BasicError("forbidden", "m").status, 403)
        self.assertEqual(services.BasicError("not_found", "m").status, 404)

    def test_included_and_missing(self):
        inactive = User.objects.create_user(username="ina", password="x", role=UserTypes.AGENT, is_active=False)
        owner = User.objects.create_user(username="own", password="x", role=UserTypes.OWNER)
        nosal = User.objects.create_user(username="nos", password="x", role=UserTypes.AGENT)
        for u in (inactive, owner, self.superuser):
            make_basic(u, date(2026, 10, 1), 1000)
        self.assertEqual(set(services.included_users(KEY)), {self.agent})
        self.assertEqual(set(services.missing_salary_users(KEY)), {nosal})

    def _mk(self, n):
        users = []
        for i in range(n):
            u = User.objects.create_user(username=f"u{n}_{i}", password="x", role=UserTypes.AGENT)
            make_basic(u, date(2026, 9, 1), 1000 + i * 100)
            day(u, date(2026, 10, 2), 0.5)
            day(u, date(2026, 10, 3), 0, DayStatus.LEAVE)
            make_penalty(u, self.superuser, date=date(2026, 10, 4), kind=PenaltyKind.DAYS, value=D(1))
            make_penalty(u, self.superuser, date=date(2026, 10, 5), kind=PenaltyKind.MONEY, value=D(10 + i))
            if i % 2:
                MonthlyBasic.objects.create(user=u, period=KEY, kpi=5, gift=D("1.5"))
            users.append(u)
        return users

    def test_compute_many_matches_compute_and_bounded_queries(self):
        three = self._mk(3)
        AttendanceSettings.get()
        with self.assertNumQueries(6):
            many3 = services.compute_many(three, KEY)
        for u in three:
            rec = MonthlyBasic.objects.filter(user=u, period=KEY).first()
            self.assertEqual(many3[u.pk], services.compute(u, KEY, rec))
        six = three + [User.objects.create_user(username=f"x{i}", password="x") for i in range(3)]
        with self.assertNumQueries(6):
            services.compute_many(six, KEY)


def make_advance(user, amount=1000, n=2, status="approved", start=KEY):
    adv = Advance.objects.create(user=user, amount=D(amount), installments=n, start_period=start, status=status)
    y, m = int(start[:4]), int(start[5:])
    for i in range(n):
        idx = y * 12 + m - 1 + i
        AdvanceInstallment.objects.create(
            advance=adv, period=f"{idx // 12:04d}-{idx % 12 + 1:02d}", amount=D(amount) / n)
    return adv


class AdvanceDeductionTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        make_basic(self.agent, date(2026, 10, 1), 3000)

    def test_advance_deduction_reduces_net(self):
        make_advance(self.agent)
        r = services.compute(self.agent, KEY)
        self.assertEqual(r["advance_deduction"], D("500.00"))
        self.assertEqual(r["net"], D("2500.00"))

    def test_compute_many_matches_compute_with_advances(self):
        make_advance(self.agent)
        other = User.objects.create_user(username="adv2", password="x", role=UserTypes.AGENT)
        make_basic(other, date(2026, 9, 1), 1000)
        many = services.compute_many([self.agent, other], KEY)
        self.assertEqual(many[self.agent.pk], services.compute(self.agent, KEY))
        self.assertEqual(many[other.pk]["advance_deduction"], D("0"))
        self.assertEqual(many[other.pk], services.compute(other, KEY))

    def test_snapshot_keeps_advance_deduction(self):
        make_advance(self.agent)
        services.give(self.superuser, self.agent, KEY, today=date(2026, 11, 5))
        rec = MonthlyBasic.objects.get(user=self.agent, period=KEY)
        self.assertEqual(rec.advance_deduction, D("500"))
        self.assertEqual(services.compute(self.agent, KEY, rec)["advance_deduction"], D("500.00"))

    def test_regive_after_cancel_recomputes(self):
        adv = make_advance(self.agent)
        services.give(self.superuser, self.agent, KEY, today=date(2026, 11, 5))
        services.ungive(self.superuser, self.agent, KEY)
        adv.status = "cancelled"
        adv.save()
        services.give(self.superuser, self.agent, KEY, today=date(2026, 11, 5))
        rec = MonthlyBasic.objects.get(user=self.agent, period=KEY)
        self.assertEqual(rec.advance_deduction, D("0"))
        self.assertEqual(rec.net, D("3000"))

    def test_snapshot_handles_null_advance_deduction(self):
        rec = MonthlyBasic.objects.create(
            user=self.agent, period=KEY, status=BasicStatus.GIVEN, basic=D(3000), daily_rate=D(100),
            attendance_days=D(0), penalty_days=D(0), deduction_days=D(0), deduction_amount=D(0),
            penalty_money=D(0), advance_deduction=None, net=D(3000), leave_days=D(0))
        self.assertEqual(services.compute(self.agent, KEY, rec)["advance_deduction"], D("0.00"))

    def test_give_locks_user_advances(self):
        make_advance(self.agent)
        with CaptureQueriesContext(connection) as ctx:
            services.give(self.superuser, self.agent, KEY, today=date(2026, 11, 5))
        self.assertTrue(any('FROM "treasury_advance"' in q["sql"] and "JOIN" not in q["sql"]
                            for q in ctx.captured_queries))
