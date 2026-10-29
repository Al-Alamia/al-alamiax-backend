import datetime as dt

from apps.attendance.models import AttendanceDay, AttendanceSettings, PeriodClose, Punch
from apps.attendance.services.evaluate import apply_allowance, evaluate_day
from apps.attendance.services.locks import PeriodClosed, assert_open, closed_period_for, is_date_closed
from apps.attendance.tests.factories import assign, make_policy, make_shift, punch
from apps.attendance.types import DayStatus, PunchSource
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

D = dt.date
NOW = dt.datetime(2026, 10, 20, 12)
PUNCHES = "/api/attendance/punches"
SETTINGS = "/api/attendance/settings"


class LockTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR)

    def close(self, key="2026-09", start=D(2026, 8, 26), end=D(2026, 9, 25)):
        return PeriodClose.objects.create(period=key, start=start, end=end,
                                          closed_by=self.superuser, closed_at=NOW)

    def stored_day(self, d, deduction=1.0):
        return AttendanceDay.objects.create(user=self.agent, date=d, status=DayStatus.ABSENT,
                                            deduction_days=deduction, evaluated_at=NOW)

    def test_closed_period_for_overlap(self):
        self.close()
        self.assertEqual(closed_period_for(D(2026, 9, 25), D(2026, 9, 27)), "2026-09")
        self.assertIsNone(closed_period_for(D(2026, 9, 26), D(2026, 10, 1)))
        self.assertTrue(is_date_closed(D(2026, 8, 26)))
        self.assertFalse(is_date_closed(D(2026, 9, 26)))

    def test_assert_open_raises(self):
        self.close()
        with self.assertRaises(PeriodClosed) as ctx:
            assert_open(D(2026, 9, 1))
        self.assertEqual(ctx.exception.period, "2026-09")
        self.assertEqual(str(ctx.exception), "Payroll period 2026-09 is closed.")
        assert_open(D(2026, 9, 26), D(2026, 10, 1))

    def test_evaluate_day_skips_closed_date(self):
        make_policy(allowance=0, absence=1.0)
        assign(make_shift(name="Morning"), department=self.department)
        self.close()
        d = D(2026, 9, 7)
        row = self.stored_day(d)
        before = AttendanceDay.objects.get(pk=row.pk).updated_at
        punch(self.agent, dt.datetime(2026, 9, 7, 9, 0))
        punch(self.agent, dt.datetime(2026, 9, 7, 17, 0))
        got = evaluate_day(self.agent, d, NOW)
        self.assertEqual(got.pk, row.pk)
        self.assertEqual(got.deduction_days, 1.0)
        self.assertEqual(AttendanceDay.objects.get(pk=row.pk).updated_at, before)
        self.assertIsNone(evaluate_day(self.agent, D(2026, 9, 8), NOW))
        self.assertFalse(AttendanceDay.objects.filter(date=D(2026, 9, 8)).exists())

    def test_apply_allowance_noop_when_closed(self):
        make_policy(allowance=2, late=[(15, 0.25)])
        assign(make_shift(name="Morning"), department=self.department)
        d = D(2026, 9, 7)
        punch(self.agent, dt.datetime(2026, 9, 7, 9, 30)); punch(self.agent, dt.datetime(2026, 9, 7, 17))
        evaluate_day(self.agent, d, NOW)
        before = AttendanceDay.objects.get(user=self.agent, date=d)
        self.assertAlmostEqual(before.deduction_days, 0.25)
        self.close()
        apply_allowance(self.agent, "2026-09")
        after = AttendanceDay.objects.get(user=self.agent, date=d)
        self.assertAlmostEqual(after.deduction_days, 0.25)
        self.assertFalse(after.late_excused_by_allowance)

    def test_manual_punch_create_and_delete_refused(self):
        self.close()
        self.authenticate_as(self.hr)
        r = self.client.post(PUNCHES, {"user": str(self.agent.uuid), "timestamp": "2026-09-07T09:00",
                                       "note": "fix"}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "period_closed"))
        self.assertFalse(Punch.objects.exists())
        p = punch(self.agent, dt.datetime(2026, 9, 7, 9, 0), PunchSource.MANUAL)
        r = self.client.delete(f"{PUNCHES}/{p.uuid}")
        self.assertEqual((r.status_code, r.data["type"]), (400, "period_closed"))
        self.assertTrue(Punch.objects.filter(pk=p.pk).exists())

    def test_period_start_day_locked_while_closed(self):
        self.close()
        self.authenticate_as(self.hr)
        r = self.client.put(SETTINGS, {"period_start_day": 10}, format="json")
        self.assertEqual((r.status_code, r.data["type"]), (400, "period_closed"))
        self.assertEqual(AttendanceSettings.get().period_start_day, 26)
        r = self.client.put(SETTINGS, {"period_start_day": 26}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        r = self.client.put(SETTINGS, {"device_sync_minutes": 30}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
