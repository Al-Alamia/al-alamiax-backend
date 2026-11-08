from datetime import date

from apps.reports.services.periods import period_for, recent_periods
from apps.reports.tests.base import ReportsTestCase


class PeriodsTests(ReportsTestCase):
    def test_daily(self):
        rt = self.make_type("daily")
        d = date(2026, 11, 8)
        self.assertEqual(period_for(rt, d), (d, d))

    def test_weekly_starts_saturday(self):
        rt = self.make_type("weekly")
        self.assertEqual(period_for(rt, date(2026, 11, 11)), (date(2026, 11, 7), date(2026, 11, 13)))

    def test_weekly_on_saturday(self):
        rt = self.make_type("weekly")
        self.assertEqual(period_for(rt, date(2026, 11, 7)), (date(2026, 11, 7), date(2026, 11, 13)))

    def test_weekly_on_friday(self):
        rt = self.make_type("weekly")
        self.assertEqual(period_for(rt, date(2026, 11, 13)), (date(2026, 11, 7), date(2026, 11, 13)))

    def test_monthly_payroll_period(self):
        from apps.attendance.models import AttendanceSettings
        s = AttendanceSettings.get()
        s.period_start_day = 26
        s.save()
        rt = self.make_type("monthly")
        self.assertEqual(period_for(rt, date(2026, 11, 8)), (date(2026, 10, 26), date(2026, 11, 25)))

    def test_recent_periods_weekly(self):
        rt = self.make_type("weekly")
        self.assertEqual(recent_periods(rt, date(2026, 11, 11), 3), [
            (date(2026, 11, 7), date(2026, 11, 13)),
            (date(2026, 10, 31), date(2026, 11, 6)),
            (date(2026, 10, 24), date(2026, 10, 30)),
        ])

    def test_recent_periods_daily_and_monthly(self):
        rt = self.make_type("daily")
        self.assertEqual(recent_periods(rt, date(2026, 11, 8), 2),
                         [(date(2026, 11, 8),) * 2, (date(2026, 11, 7),) * 2])
        from apps.attendance.models import AttendanceSettings
        s = AttendanceSettings.get()
        s.period_start_day = 1
        s.save()
        rt = self.make_type("monthly")
        self.assertEqual(recent_periods(rt, date(2026, 11, 8), 2), [
            (date(2026, 11, 1), date(2026, 11, 30)),
            (date(2026, 10, 1), date(2026, 10, 31)),
        ])
