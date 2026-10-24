from datetime import datetime as dt, timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from apps.attendance.management.commands import run_attendance_scheduler as sched
from apps.attendance.models import AttendanceSettings
from apps.attendance.services import nightly
from apps.attendance.tests.test_device_sync import make_device

NOW = dt(2026, 10, 21, 3, 30)


def run_once(now=NOW):
    out = StringIO()
    with mock.patch.object(sched, "_now", return_value=now):
        call_command("run_attendance_scheduler", "--once", stdout=out)
    return out.getvalue()


class SchedulerTests(TestCase):
    def test_nightly_runs_once_per_day(self):
        with mock.patch.object(sched, "run_nightly", return_value=0) as m:
            run_once()
            self.assertEqual(m.call_count, 1)
            self.assertEqual(AttendanceSettings.get().last_nightly_run, NOW.date())
            run_once(NOW + timedelta(minutes=1))
            self.assertEqual(m.call_count, 1)
            run_once(NOW + timedelta(days=1))
            self.assertEqual(m.call_count, 2)

    def test_nightly_not_before_three(self):
        with mock.patch.object(sched, "run_nightly") as m:
            run_once(dt(2026, 10, 21, 2, 59))
        m.assert_not_called()

    def test_sync_when_due_only(self):
        make_device("10.0.0.1", last_synced_at=NOW - timedelta(minutes=30))
        with mock.patch.object(sched, "sync_all", return_value=[]) as m:
            run_once()
            m.assert_not_called()
            make_device("10.0.0.2")  # never synced -> due
            run_once()
            m.assert_called_once()

    def test_sync_busy_skipped_silently(self):
        make_device("10.0.0.1")
        with mock.patch.object(sched, "sync_all", side_effect=sched.SyncBusy()):
            run_once()  # must not raise

    def test_errors_logged_not_raised(self):
        make_device("10.0.0.1")
        with mock.patch.object(sched, "sync_all", side_effect=RuntimeError("boom")):
            out = run_once()
        self.assertIn("boom", out)

    def test_run_nightly_recalculates_two_days(self):
        with mock.patch.object(nightly, "recalculate", return_value=5) as m:
            self.assertEqual(nightly.run_nightly(NOW), 5)
        start, end, _users = m.call_args[0][:3]
        self.assertEqual((start, end), (NOW.date() - timedelta(days=2), NOW.date() - timedelta(days=1)))
