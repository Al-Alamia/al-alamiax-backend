from datetime import date, timedelta

from apps.attendance.models import AttendanceDay
from apps.attendance.types import DayStatus
from apps.reports.services.audience import is_required, not_working_ids, required_users
from apps.reports.tests.base import ReportsTestCase
from apps.users.models import User
from apps.users.types import UserTypes


class AudienceTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.u = User.objects.create_user(
            username="mk1", password="x", role=UserTypes.AGENT, department=self.marketing,
            project=self.project)
        self.rt = self.make_type("daily")
        self.today = date(2026, 11, 8)

    def day(self, user, d, status):
        from django.utils import timezone
        AttendanceDay.objects.create(user=user, date=d, status=status, evaluated_at=timezone.now())

    def test_required_users_departments_active_excluded(self):
        inactive = User.objects.create_user(
            username="mk2", password="x", department=self.marketing, is_active=False)
        excluded = User.objects.create_user(
            username="mk3", password="x", department=self.marketing)
        self.rt.excluded_users.add(excluded)
        ids = set(required_users(self.rt).values_list("pk", flat=True))
        self.assertEqual(ids, {self.u.pk})
        self.assertNotIn(inactive.pk, ids)
        self.assertNotIn(self.agent.pk, ids)  # other department

    def test_daily_leave_not_required(self):
        self.day(self.u, self.today, DayStatus.LEAVE)
        self.assertFalse(is_required(self.rt, self.u, self.today, self.today, self.today))

    def test_daily_absent_required(self):
        self.day(self.u, self.today, DayStatus.ABSENT)
        self.assertTrue(is_required(self.rt, self.u, self.today, self.today, self.today))

    def test_daily_missing_row_required(self):
        self.assertTrue(is_required(self.rt, self.u, self.today, self.today, self.today))

    def test_not_in_audience_not_required(self):
        self.assertFalse(is_required(self.rt, self.agent, self.today, self.today, self.today))

    def test_weekly_all_non_working(self):
        start, end = date(2026, 11, 7), date(2026, 11, 13)
        today = date(2026, 11, 9)
        for i in range(3):  # Sat..Mon
            self.day(self.u, start + timedelta(days=i), DayStatus.WEEKEND)
        self.assertEqual(not_working_ids([self.u.pk], start, end, today), {self.u.pk})
        self.assertFalse(is_required(self.make_type("weekly"), self.u, start, end, today))

    def test_weekly_one_working_day_required(self):
        start, end = date(2026, 11, 7), date(2026, 11, 13)
        today = date(2026, 11, 9)
        self.day(self.u, start, DayStatus.WEEKEND)
        self.day(self.u, start + timedelta(days=1), DayStatus.PRESENT)
        self.day(self.u, start + timedelta(days=2), DayStatus.HOLIDAY)
        self.assertEqual(not_working_ids([self.u.pk], start, end, today), set())

    def test_weekly_missing_row_required(self):
        start, end = date(2026, 11, 7), date(2026, 11, 13)
        today = date(2026, 11, 8)
        self.day(self.u, start, DayStatus.WEEKEND)
        self.assertEqual(not_working_ids([self.u.pk], start, end, today), set())
