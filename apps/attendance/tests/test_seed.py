from datetime import date, datetime, time, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.attendance.models import (AttendanceDay, DeductionPolicy, DeductionTier, Holiday, Punch,
                                    Shift, ShiftAssignment)
from apps.attendance.services.shifts import resolve_shift, shift_window
from apps.attendance.types import DayStatus, PunchSource
from apps.users.models import Department, User, ZKConfig
from apps.users.tests.base import BaseUserTestCase


def seed(*args):
    out = StringIO()
    call_command("seed_attendance_demo", *args, stdout=out)
    return out.getvalue()


class SeedAttendanceDemoTests(BaseUserTestCase):
    @override_settings(DEBUG=False)
    def test_refuses_without_force_when_not_debug(self):
        with self.assertRaises(CommandError):
            seed("--days", "10")
        self.assertEqual(Shift.objects.count(), 0)

    @override_settings(DEBUG=True)
    def test_runs_in_debug_without_force(self):
        seed("--days", "5")
        self.assertTrue(Shift.objects.filter(name="Morning").exists())

    def test_seeds_shifts_policy_assignments_and_users(self):
        out = seed("--force", "--days", "10")
        morning = Shift.objects.get(name="Morning")
        self.assertEqual(morning.start_time.strftime("%H:%M"), "09:00")
        self.assertEqual(morning.weekend_days, [4, 5])
        self.assertEqual(morning.grace_minutes, 10)
        night = Shift.objects.get(name="Night")
        self.assertTrue(night.crosses_midnight)
        self.assertEqual(night.grace_minutes, 0)

        policy = DeductionPolicy.objects.get(department__isnull=True)
        self.assertEqual(policy.monthly_late_allowance, 3)
        tiers = {(t.kind, t.min_minutes): t.deduction_days for t in policy.tiers.all()}
        self.assertEqual(tiers, {("LATE", 15): 0.25, ("LATE", 60): 0.5, ("LATE", 120): 1,
                                 ("EARLY_LEAVE", 30): 0.25, ("EARLY_LEAVE", 120): 0.5})
        self.assertTrue(DeductionPolicy.objects.filter(department__isnull=False).exists())

        # one department switches Morning -> Night
        switching = [d for d in ShiftAssignment.objects.values_list("department", flat=True).distinct()
                     if ShiftAssignment.objects.filter(department=d).count() >= 2]
        self.assertEqual(len(switching), 1)
        self.assertEqual(Holiday.objects.count(), 2)
        # only 2 users existed, so demo users are created
        self.assertTrue(User.objects.filter(username="demo_manager").exists())
        self.assertEqual(User.objects.filter(username__startswith="demo_agent").count(), 4)
        self.assertIn("punches", out.lower())

    def test_creates_punches_and_statuses(self):
        seed("--force", "--days", "10")
        self.assertGreater(Punch.objects.count(), 0)
        self.assertEqual(Punch.objects.filter(is_demo=False).count(), 0)
        statuses = set(AttendanceDay.objects.values_list("status", flat=True))
        self.assertIn(DayStatus.PRESENT, statuses)
        self.assertIn(DayStatus.LATE, statuses)
        manual = Punch.objects.filter(source=PunchSource.MANUAL)
        self.assertTrue(all(p.note == "demo correction" for p in manual))
        self.assertFalse(Punch.objects.filter(source=PunchSource.DEVICE).exists())

    def test_rerun_is_idempotent_and_reset_restores_count(self):
        seed("--force", "--days", "10")
        first = Punch.objects.count()
        days = AttendanceDay.objects.count()
        seed("--force", "--days", "10")
        self.assertEqual(Punch.objects.count(), first)
        self.assertEqual(Shift.objects.count(), 2)
        self.assertEqual(AttendanceDay.objects.count(), days)
        seed("--force", "--days", "10", "--reset")
        self.assertEqual(Punch.objects.filter(is_demo=True).count(), first)
        self.assertEqual(Punch.objects.count(), first)
        self.assertEqual(AttendanceDay.objects.count(), days)

    def test_fp_signal_reconnected_after_run(self):
        from django.db.models.signals import post_save
        from apps.users.models import fp_signal
        post_save.connect(fp_signal, sender=User)
        try:
            seed("--force", "--days", "3")
            # disconnect() returns True only if the receiver was still connected
            self.assertTrue(post_save.disconnect(fp_signal, sender=User))
        finally:
            post_save.disconnect(fp_signal, sender=User)

    def test_demo_users_go_to_demo_departments_only(self):
        seed("--force", "--days", "5")
        names = set(User.objects.filter(username__startswith="demo_").values_list("department__name", flat=True))
        self.assertEqual(names, {"Demo Sales", "Demo Marketing"})

    def test_existing_shift_is_reused_unchanged(self):
        Shift.objects.create(name="Morning", start_time=time(8, 0), end_time=time(15, 0),
                             weekend_days=[6], grace_minutes=3)
        seed("--force", "--days", "5")
        m = Shift.objects.get(name="Morning")
        self.assertEqual((m.start_time, m.end_time, m.weekend_days, m.grace_minutes),
                         (time(8, 0), time(15, 0), [6], 3))

    def test_department_with_assignments_gets_none(self):
        shift = Shift.objects.create(name="Custom", start_time=time(7, 0), end_time=time(15, 0))
        ShiftAssignment.objects.create(department=self.department, shift=shift,
                                       effective_from=date(2020, 1, 1))
        seed("--force", "--days", "10")
        self.assertEqual(ShiftAssignment.objects.filter(department=self.department).count(), 1)
        self.assertTrue(ShiftAssignment.objects.exclude(department=self.department).exists())

    def test_global_policy_with_tiers_is_untouched(self):
        policy = DeductionPolicy.objects.get(department__isnull=True)
        policy.monthly_late_allowance = 7
        policy.save()
        DeductionTier.objects.create(policy=policy, kind="LATE", min_minutes=5, deduction_days=0.1)
        seed("--force", "--days", "5")
        policy.refresh_from_db()
        self.assertEqual(policy.monthly_late_allowance, 7)
        self.assertEqual([(t.kind, t.min_minutes) for t in policy.tiers.all()], [("LATE", 5)])

    def test_real_punch_blocks_demo_punches_and_survives_reset(self):
        seed("--force", "--days", "10")
        Punch.objects.all().delete()
        holidays = set(Holiday.objects.values_list("date", flat=True))
        day = date.today() - timedelta(days=3)
        while day.weekday() in (4, 5) or day in holidays:  # a day demo punches would normally land on
            day -= timedelta(days=1)
        real = Punch.objects.create(
            user=self.agent, source=PunchSource.WEB,
            timestamp=shift_window(resolve_shift(self.agent, day), day).expected_start)
        for args in ([], ["--reset"]):
            seed("--force", "--days", "10", *args)
            w = shift_window(resolve_shift(self.agent, day), day)
            window = (w.window_start, w.window_end - timedelta(microseconds=1))
            self.assertEqual(Punch.objects.filter(user=self.agent, is_demo=True,
                                                  timestamp__range=window).count(), 0)
            self.assertTrue(Punch.objects.filter(pk=real.pk).exists())

    def test_fresh_runs_are_deterministic(self):
        def snapshot():
            return sorted(Punch.objects.values_list("user__username", "timestamp", "source"))
        seed("--force", "--days", "10")
        first = snapshot()
        Punch.objects.all().delete()
        AttendanceDay.objects.all().delete()
        seed("--force", "--days", "10")
        self.assertEqual(snapshot(), first)

    def test_device_punches_when_zkconfig_exists(self):
        ZKConfig.objects.create(ip="10.9.9.9", port=4370, timeout=5, password="", force_udp=False,
                                ommit_ping=False, is_default=True, last_uid=0)
        seed("--force", "--days", "30")
        self.assertTrue(Punch.objects.filter(source=PunchSource.DEVICE).exists())
