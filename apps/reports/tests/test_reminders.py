from datetime import date, datetime, time
from unittest import mock

from django.utils import timezone

from apps.attendance.models import AttendanceDay
from apps.attendance.types import DayStatus
from apps.notifications.models import Notification, NotificationRecipient
from apps.notifications.types import NotificationKinds
from apps.reports.models import ReportSubmission
from apps.reports.services import reminders
from apps.reports.tests.base import ReportsTestCase
from apps.teams.models import Team
from apps.users.models import User
from apps.users.types import UserTypes

NOW = datetime(2026, 11, 8, 21, 0)  # a Sunday
TODAY = NOW.date()


class ReminderTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        self.a1 = User.objects.create_user(
            username="mk1", password="x", role=UserTypes.AGENT, department=self.marketing)
        self.a2 = User.objects.create_user(
            username="mk2", password="x", role=UserTypes.AGENT, department=self.marketing)
        self.rt = self.make_type("daily", remind_agents=True, remind_at=time(20, 0))

    def recipients(self, user):
        return NotificationRecipient.objects.filter(user=user)

    def test_before_remind_at_nothing(self):
        self.assertEqual(reminders.run_reminders(datetime(2026, 11, 8, 19, 59)), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_after_notifies_missing_once(self):
        self.assertEqual(reminders.run_reminders(NOW), 2)
        self.assertEqual(Notification.objects.count(), 2)
        n = Notification.objects.first()
        self.assertEqual(n.kind, NotificationKinds.REPORT)
        self.assertEqual(n.link, "/reports")
        self.assertEqual(n.title, "Report reminder")
        self.rt.refresh_from_db()
        self.assertEqual(self.rt.last_reminded_on, TODAY)
        self.assertEqual(reminders.run_reminders(NOW), 0)
        self.assertEqual(Notification.objects.count(), 2)

    def test_submitted_and_leave_skipped(self):
        ReportSubmission.objects.create(
            report_type=self.rt, user=self.a1, period_start=TODAY, period_end=TODAY,
            submitted_at=timezone.now())
        AttendanceDay.objects.create(
            user=self.a2, date=TODAY, status=DayStatus.LEAVE, evaluated_at=timezone.now())
        self.assertEqual(reminders.run_reminders(NOW), 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.rt.refresh_from_db()
        self.assertEqual(self.rt.last_reminded_on, TODAY)

    def test_weekly_only_on_last_day(self):
        self.rt.frequency = "weekly"
        self.rt.save()
        self.assertEqual(reminders.run_reminders(NOW), 0)  # Sunday
        self.rt.refresh_from_db()
        self.assertIsNone(self.rt.last_reminded_on)
        friday = datetime(2026, 11, 13, 21, 0)
        self.assertEqual(reminders.run_reminders(friday), 2)

    def test_digest_one_per_supervisor(self):
        self.rt.remind_agents = False
        self.rt.digest_leaders = True
        self.rt.save()
        leader = User.objects.create_user(username="ld", password="x", role=UserTypes.AGENT,
                                          department=self.marketing)
        team = Team.objects.create(name="T", department=self.marketing, leader=leader)
        team.agents.set([self.a1])
        mgr = User.objects.create_user(username="mg", password="x", role=UserTypes.MANAGER,
                                       department=self.marketing)
        # leader and manager are themselves department users so they are required too
        self.assertEqual(reminders.run_reminders(NOW), 2)
        self.assertEqual(self.recipients(self.a1).count(), 0)
        self.assertEqual(self.recipients(leader).count(), 1)
        self.assertEqual(self.recipients(mgr).count(), 1)
        n = self.recipients(leader).get().notification
        self.assertEqual(n.title, "Missing reports")
        self.assertEqual(n.link, f"/reports/board?type={self.rt.uuid}")
        self.assertIn(self.a1.username, n.message)
        m = self.recipients(mgr).get().notification
        for u in (self.a1, self.a2, leader):
            self.assertIn(u.username, m.message)

    def test_both_flags_off(self):
        self.rt.remind_agents = False
        self.rt.save()
        self.assertEqual(reminders.run_reminders(NOW), 0)
        self.rt.refresh_from_db()
        self.assertIsNone(self.rt.last_reminded_on)
