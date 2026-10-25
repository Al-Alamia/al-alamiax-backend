import datetime as dt

from apps.attendance.models import AttendanceDay, Holiday
from apps.attendance.services.evaluate import evaluate_and_allow, evaluate_day, recalculate
from apps.attendance.tests.factories import (
    assign, make_leave_type, make_policy, make_request, make_shift, punch,
)
from apps.attendance.types import DayStatus, PunchSource, RequestKind, RequestStatus
from apps.users.tests.base import BaseUserTestCase

D = dt.date
MON = D(2026, 10, 5)
TUE = D(2026, 10, 6)
NOW = dt.datetime(2026, 10, 20, 12)


def at(h, m=0, day=MON):
    return dt.datetime(day.year, day.month, day.day, h, m)


class EvaluateRequestsTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.shift = make_shift(name="Morning")
        assign(self.shift, department=self.department)
        make_policy(late=[(15, 0.25), (60, 0.5), (120, 1.0)], early=[(30, 0.25), (120, 0.5)],
                    allowance=0, absence=1.0)

    def ev(self, d=MON, now=NOW):
        return evaluate_day(self.agent, d, now)

    def leave(self, start=MON, end=None, pay=100, **kw):
        return make_request(self.agent, RequestKind.LEAVE, start, end,
                            leave_type=make_leave_type(pay_percent=pay), **kw)

    def test_leave_full_pay(self):
        req = self.leave()
        day = self.ev()
        self.assertEqual(day.status, DayStatus.LEAVE)
        self.assertEqual(day.deduction_days, 0)
        self.assertEqual(day.request_id, req.pk)

    def test_leave_half_and_unpaid(self):
        self.leave(pay=50)
        self.assertAlmostEqual(self.ev().deduction_days, 0.5)
        AttendanceDay.objects.all().delete()
        from apps.attendance.models import Request
        Request.objects.all().delete()
        self.leave(pay=0)
        self.assertAlmostEqual(self.ev().deduction_days, 1.0)

    def test_leave_skips_weekend_and_holiday(self):
        thu, fri, sat, sun = D(2026, 10, 8), D(2026, 10, 9), D(2026, 10, 10), D(2026, 10, 11)
        Holiday.objects.create(date=sun, name="H")
        self.leave(thu, sun)
        self.assertEqual(self.ev(thu).status, DayStatus.LEAVE)
        self.assertEqual(self.ev(fri).status, DayStatus.WEEKEND)
        self.assertEqual(self.ev(sat).status, DayStatus.WEEKEND)
        self.assertEqual(self.ev(sun).status, DayStatus.HOLIDAY)

    def test_future_leave_creates_row(self):
        self.leave(TUE)
        day = self.ev(TUE, now=at(8))
        self.assertIsNotNone(day)
        self.assertEqual(day.status, DayStatus.LEAVE)

    def test_leave_ignores_punches_status(self):
        self.leave()
        punch(self.agent, at(10, 30)); punch(self.agent, at(17))
        day = self.ev()
        self.assertEqual(day.status, DayStatus.LEAVE)
        self.assertEqual(day.first_in, at(10, 30))
        self.assertEqual(day.late_minutes, 0)
        self.assertEqual(day.early_leave_minutes, 0)
        self.assertEqual(day.deduction_days, 0)

    def test_late_excuse_full(self):
        punch(self.agent, at(9, 40)); punch(self.agent, at(17))
        req = make_request(self.agent, RequestKind.LATE_EXCUSE, MON, minutes=30)
        day = self.ev()
        self.assertEqual(day.status, DayStatus.EXCUSED)
        self.assertEqual(day.deduction_days, 0)
        self.assertEqual(day.late_minutes, 30)
        self.assertEqual(day.excused_late_minutes, 30)
        self.assertEqual(day.request_id, req.pk)

    def test_late_excuse_partial(self):
        punch(self.agent, at(10, 20)); punch(self.agent, at(17))
        make_request(self.agent, RequestKind.LATE_EXCUSE, MON, minutes=30)
        day = self.ev()
        self.assertEqual(day.status, DayStatus.LATE)
        self.assertEqual(day.late_minutes, 70)
        self.assertEqual(day.excused_late_minutes, 30)
        self.assertAlmostEqual(day.deduction_days, 0.25)

    def test_early_excuse_full(self):
        punch(self.agent, at(9)); punch(self.agent, at(16))
        make_request(self.agent, RequestKind.EARLY_EXCUSE, MON, minutes=60)
        day = self.ev()
        self.assertEqual(day.status, DayStatus.EXCUSED)
        self.assertEqual(day.deduction_days, 0)
        self.assertEqual(day.excused_early_minutes, 60)

    def test_early_excuse_on_incomplete_noop(self):
        punch(self.agent, at(9))
        make_request(self.agent, RequestKind.EARLY_EXCUSE, MON, minutes=60)
        day = self.ev(now=dt.datetime(2026, 10, 6))
        self.assertEqual(day.status, DayStatus.INCOMPLETE)

    def test_excused_day_skips_allowance(self):
        make_policy(allowance=1, late=[(15, 0.25)])
        punch(self.agent, at(9, 40)); punch(self.agent, at(17))
        punch(self.agent, at(9, 40, TUE)); punch(self.agent, at(17, day=TUE))
        make_request(self.agent, RequestKind.LATE_EXCUSE, MON, minutes=30)
        mon = evaluate_and_allow(self.agent, MON, NOW)
        tue = evaluate_and_allow(self.agent, TUE, NOW)
        mon.refresh_from_db()
        self.assertEqual(mon.status, DayStatus.EXCUSED)
        self.assertFalse(mon.late_excused_by_allowance)
        self.assertTrue(tue.late_excused_by_allowance)

    def test_partial_excuse_uses_remaining_in_allowance(self):
        make_policy(allowance=0, late=[(15, 0.25), (60, 0.5)])
        punch(self.agent, at(10, 20)); punch(self.agent, at(17))
        make_request(self.agent, RequestKind.LATE_EXCUSE, MON, minutes=30)
        day = evaluate_and_allow(self.agent, MON, NOW)
        self.assertAlmostEqual(day.deduction_days, 0.25)

    def test_rejected_or_pending_has_no_effect(self):
        self.leave(status=RequestStatus.PENDING)
        self.assertEqual(self.ev().status, DayStatus.ABSENT)
        self.leave(status=RequestStatus.REJECTED)
        self.assertEqual(self.ev().status, DayStatus.ABSENT)

    def test_recalculate_refreshes_leave_days(self):
        wed = D(2026, 10, 7)
        req = self.leave(MON, wed)
        recalculate(MON, wed, [self.agent], NOW)
        req.refresh_from_db()
        self.assertEqual(req.leave_days, 3)
        Holiday.objects.create(date=TUE, name="H")
        recalculate(MON, wed, [self.agent], NOW)
        req.refresh_from_db()
        self.assertEqual(req.leave_days, 2)

    def test_missed_punch_night_shift_owner_day(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6), grace_minutes=0)
        assign(night, user=self.agent, effective_from=D(2026, 10, 1))
        punch(self.agent, at(22))
        punch(self.agent, at(5, 50, TUE), source=PunchSource.REQUEST)
        recalculate(MON, D(2026, 10, 7), [self.agent], NOW)
        day = AttendanceDay.objects.get(user=self.agent, date=MON)
        self.assertEqual(day.last_out, at(5, 50, TUE))
