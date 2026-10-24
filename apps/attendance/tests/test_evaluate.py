import datetime as dt

from apps.attendance.models import AttendanceDay, Holiday
from apps.attendance.services.evaluate import (
    apply_allowance, evaluate_and_allow, evaluate_day, recalculate,
)
from apps.attendance.services.shifts import day_for_punch
from apps.attendance.tests.factories import assign, make_policy, make_shift, punch
from apps.attendance.types import DayStatus
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase

D = dt.date
MON = D(2026, 10, 5)
NOW = dt.datetime(2026, 10, 20, 12)  # long after every tested day is closed


def at(h, m=0, day=MON):
    return dt.datetime(day.year, day.month, day.day, h, m)


class EvaluateDayTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.shift = make_shift(name="Morning")
        assign(self.shift, department=self.department)
        make_policy(late=[(15, 0.25), (60, 0.5), (120, 1.0)], early=[(30, 0.25), (120, 0.5)],
                    allowance=0, absence=1.0)

    def ev(self, d=MON, now=NOW, user=None):
        return evaluate_day(user or self.agent, d, now)

    def test_on_time_within_grace(self):
        punch(self.agent, at(9, 9)); punch(self.agent, at(17, 5))
        day = self.ev()
        self.assertEqual(day.status, DayStatus.PRESENT)
        self.assertEqual(day.late_minutes, 0)
        self.assertEqual(day.deduction_days, 0)
        self.assertEqual(day.worked_minutes, 476)

    def test_late_tier(self):
        punch(self.agent, at(9, 30)); punch(self.agent, at(17))
        day = self.ev()
        self.assertEqual(day.status, DayStatus.LATE)
        self.assertEqual(day.late_minutes, 20)
        self.assertAlmostEqual(day.deduction_days, 0.25)

    def test_late_highest_tier(self):
        punch(self.agent, at(10, 40)); punch(self.agent, at(17))
        day = self.ev()
        self.assertEqual(day.late_minutes, 90)
        self.assertAlmostEqual(day.deduction_days, 0.5)

    def test_early_leave_tier(self):
        punch(self.agent, at(9)); punch(self.agent, at(16))
        day = self.ev()
        self.assertEqual(day.early_leave_minutes, 60)
        self.assertAlmostEqual(day.deduction_days, 0.25)
        self.assertEqual(day.status, DayStatus.PRESENT)

    def test_deduction_capped(self):
        punch(self.agent, at(12)); punch(self.agent, at(13))
        day = self.ev()
        self.assertEqual(day.late_minutes, 170)
        self.assertEqual(day.early_leave_minutes, 240)
        self.assertAlmostEqual(day.deduction_days, 1.0)

    def test_single_punch_open_day_not_incomplete(self):
        punch(self.agent, at(9))
        day = self.ev(now=at(12))
        self.assertEqual(day.status, DayStatus.PRESENT)
        self.assertIsNone(day.last_out)
        self.assertEqual(day.first_in, at(9))

    def test_single_punch_closed_incomplete(self):
        punch(self.agent, at(9))
        day = self.ev(now=dt.datetime(2026, 10, 6))
        self.assertEqual(day.status, DayStatus.INCOMPLETE)
        self.assertEqual(day.early_leave_minutes, 0)
        self.assertEqual(day.worked_minutes, 0)

    def test_no_punch_open_returns_none(self):
        self.assertIsNone(self.ev(now=at(12)))
        self.assertEqual(AttendanceDay.objects.count(), 0)

    def test_open_day_with_no_punch_deletes_stale_row(self):
        p = punch(self.agent, at(9))
        self.ev(now=at(12))
        p.delete()
        self.assertIsNone(self.ev(now=at(12)))
        self.assertEqual(AttendanceDay.objects.count(), 0)

    def test_no_punch_closed_absent(self):
        day = self.ev()
        self.assertEqual(day.status, DayStatus.ABSENT)
        self.assertAlmostEqual(day.deduction_days, 1.0)
        self.assertTrue(day.is_working_day)

    def test_weekend_no_punch(self):
        day = self.ev(d=D(2026, 10, 9), now=at(12, day=D(2026, 10, 9)))
        self.assertEqual(day.status, DayStatus.WEEKEND)
        self.assertEqual(day.deduction_days, 0)
        self.assertFalse(day.is_working_day)

    def test_weekend_with_punch_zero_deduction(self):
        fri = D(2026, 10, 9)
        punch(self.agent, at(12, day=fri)); punch(self.agent, at(13, day=fri))
        day = self.ev(d=fri)
        self.assertEqual(day.status, DayStatus.WEEKEND)
        self.assertEqual(day.deduction_days, 0)
        self.assertEqual(day.first_in, at(12, day=fri))
        self.assertEqual(day.last_out, at(13, day=fri))

    def test_holiday_global(self):
        Holiday.objects.create(date=MON, name="H")
        day = self.ev()
        self.assertEqual(day.status, DayStatus.HOLIDAY)
        self.assertEqual(day.deduction_days, 0)

    def test_holiday_other_department_ignored(self):
        Holiday.objects.create(date=MON, name="H", department=Department.objects.create(name="Other"))
        self.assertEqual(self.ev().status, DayStatus.ABSENT)

    def test_holiday_own_department(self):
        Holiday.objects.create(date=MON, name="H", department=self.department)
        self.assertEqual(self.ev().status, DayStatus.HOLIDAY)

    def test_no_shift(self):
        other = User.objects.create_user(username="o", password="x", email="o@test.com",
                                         project=self.project,
                                         department=Department.objects.create(name="Other"),
                                         date_joined=dt.datetime(2020, 1, 1))
        day = self.ev(user=other)
        self.assertEqual(day.status, DayStatus.NO_SHIFT)
        self.assertEqual(day.deduction_days, 0)

    def test_no_row_before_date_joined(self):
        newbie = User.objects.create_user(username="newbie", password="x", email="n@test.com",
                                          project=self.project, department=self.department,
                                          date_joined=dt.datetime(2026, 10, 10, 8))
        AttendanceDay.objects.create(user=newbie, date=D(2026, 10, 5), status=DayStatus.ABSENT,
                                     evaluated_at=NOW)
        recalculate(D(2026, 10, 5), D(2026, 10, 12), [newbie], now=NOW)
        self.assertFalse(AttendanceDay.objects.filter(user=newbie, date=D(2026, 10, 5)).exists())
        self.assertIsNone(self.ev(d=D(2026, 10, 5), user=newbie))
        self.assertTrue(AttendanceDay.objects.filter(user=newbie, date=D(2026, 10, 12)).exists())
        self.assertEqual(AttendanceDay.objects.filter(user=newbie).count(), 3)  # 10, 11, 12

    def test_night_shift_across_midnight(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6), grace_minutes=0)
        assign(night, user=self.agent, effective_from=D(2026, 10, 1))
        punch(self.agent, at(22, 20)); punch(self.agent, at(5, 50, day=D(2026, 10, 6)))
        day = self.ev(now=at(23, day=D(2026, 10, 6)))
        self.assertEqual(day.date, MON)
        self.assertEqual(day.status, DayStatus.LATE)
        self.assertEqual(day.late_minutes, 20)
        self.assertEqual(day.early_leave_minutes, 10)
        self.assertEqual(day.first_in, at(22, 20))
        self.assertEqual(day.last_out, at(5, 50, day=D(2026, 10, 6)))
        self.assertEqual(day_for_punch(self.agent, at(5, 50, day=D(2026, 10, 6))), MON)
        self.assertEqual(day_for_punch(self.agent, at(23)), MON)

    def test_snapshot_survives_shift_edit(self):
        punch(self.agent, at(9, 30)); punch(self.agent, at(17))
        first = self.ev()
        self.shift.start_time = dt.time(10)
        self.shift.save()
        row = AttendanceDay.objects.get(pk=first.pk)
        self.assertEqual(row.expected_start, at(9))
        self.assertEqual(row.late_minutes, 20)
        self.assertEqual(row.shift_name, "Morning")
        self.assertEqual(row.grace_minutes, 10)
        recalculate(MON, MON, [self.agent], NOW)
        row.refresh_from_db()
        self.assertEqual(row.expected_start, at(10))
        self.assertEqual(row.late_minutes, 0)

    def test_evaluate_is_upsert(self):
        punch(self.agent, at(9, 30))
        self.ev(); self.ev()
        self.assertEqual(AttendanceDay.objects.count(), 1)

    def test_allowance_order_independent(self):
        make_policy(allowance=2, late=[(15, 0.25)])
        days = [D(2026, 10, 5), D(2026, 10, 6), D(2026, 10, 7)]
        for d in days:
            punch(self.agent, at(9, 30, day=d)); punch(self.agent, at(17, day=d))
        for d in (days[2], days[0], days[1]):
            evaluate_and_allow(self.agent, d, NOW)
        rows = {r.date: r for r in AttendanceDay.objects.filter(user=self.agent)}
        for d in days[:2]:
            self.assertTrue(rows[d].late_excused_by_allowance)
            self.assertEqual(rows[d].deduction_days, 0)
        self.assertFalse(rows[days[2]].late_excused_by_allowance)
        self.assertAlmostEqual(rows[days[2]].deduction_days, 0.25)

    def test_allowance_keeps_early_leave_deduction(self):
        make_policy(allowance=1, late=[(15, 0.25)], early=[(30, 0.25)])
        punch(self.agent, at(9, 30)); punch(self.agent, at(16))
        day = evaluate_and_allow(self.agent, MON, NOW)
        day.refresh_from_db()
        self.assertTrue(day.late_excused_by_allowance)
        self.assertAlmostEqual(day.deduction_days, 0.25)

    def test_allowance_reverts_when_punch_changes(self):
        make_policy(allowance=1, late=[(15, 0.25)])
        punch(self.agent, at(9, 30)); punch(self.agent, at(17))
        evaluate_and_allow(self.agent, MON, NOW)
        self.assertTrue(AttendanceDay.objects.get().late_excused_by_allowance)
        apply_allowance(self.agent, "2026-10")
        self.assertTrue(AttendanceDay.objects.get().late_excused_by_allowance)
        make_policy(allowance=0, late=[(15, 0.25)])
        apply_allowance(self.agent, "2026-10")
        row = AttendanceDay.objects.get()
        self.assertFalse(row.late_excused_by_allowance)
        self.assertAlmostEqual(row.deduction_days, 0.25)

    def test_recalculate_idempotent(self):
        punch(self.agent, at(9, 30)); punch(self.agent, at(16))
        users = User.objects.filter(is_active=True)
        n1 = recalculate(D(2026, 10, 4), D(2026, 10, 8), users, NOW)
        snap1 = list(AttendanceDay.objects.order_by("user__username", "date")
                     .values_list("user__username", "date", "status", "deduction_days", "late_minutes"))
        n2 = recalculate(D(2026, 10, 4), D(2026, 10, 8), users, NOW)
        snap2 = list(AttendanceDay.objects.order_by("user__username", "date")
                     .values_list("user__username", "date", "status", "deduction_days", "late_minutes"))
        self.assertEqual(n1, n2)
        self.assertEqual(snap1, snap2)
        self.assertGreater(len(snap1), 0)

    def test_department_policy_overrides_global(self):
        make_policy(department=self.department, late=[(15, 0.75)])
        punch(self.agent, at(9, 30)); punch(self.agent, at(17))
        self.assertAlmostEqual(self.ev().deduction_days, 0.75)

    def test_shift_change_punch_not_double_counted(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6), grace_minutes=0)
        assign(night, user=self.agent, effective_from=D(2026, 10, 1))
        tue = D(2026, 10, 6)
        assign(self.shift, user=self.agent, effective_from=tue)
        punch(self.agent, at(22)); punch(self.agent, at(6, day=tue))
        punch(self.agent, at(9, day=tue)); punch(self.agent, at(17, day=tue))
        d1 = self.ev()
        self.assertEqual(d1.first_in, at(22))
        self.assertEqual(d1.last_out, at(6, day=tue))
        self.assertEqual(d1.early_leave_minutes, 0)
        d2 = self.ev(d=tue)
        self.assertEqual(d2.first_in, at(9, day=tue))
        self.assertEqual(d2.last_out, at(17, day=tue))

    def test_incomplete_late_day_consumes_allowance(self):
        make_policy(allowance=1, late=[(15, 0.25)])
        punch(self.agent, at(9, 30))
        day = evaluate_and_allow(self.agent, MON, dt.datetime(2026, 10, 6))
        self.assertEqual(day.status, DayStatus.INCOMPLETE)
        self.assertTrue(day.late_excused_by_allowance)
        self.assertEqual(day.deduction_days, 0)
