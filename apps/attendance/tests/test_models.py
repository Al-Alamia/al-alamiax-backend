import datetime

from django.db import IntegrityError, transaction

from apps.attendance.models import (
    AttendanceSettings,
    DeductionPolicy,
    Punch,
    Shift,
    ShiftAssignment,
)
from apps.attendance.types import PunchSource
from apps.users.models import User, ZKConfig
from apps.users.tests.base import BaseUserTestCase


class AttendanceModelsTests(BaseUserTestCase):
    def test_settings_singleton(self):
        first = AttendanceSettings.get()
        second = AttendanceSettings.get()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(AttendanceSettings.objects.count(), 1)
        self.assertEqual(first.period_start_day, 26)
        self.assertEqual(first.device_sync_minutes, 60)

    def test_crosses_midnight(self):
        night = Shift(name="n", start_time=datetime.time(22), end_time=datetime.time(6))
        day = Shift(name="d", start_time=datetime.time(9), end_time=datetime.time(17))
        self.assertTrue(night.crosses_midnight)
        self.assertFalse(day.crosses_midnight)

    def test_shift_assignment_requires_exactly_one_target(self):
        shift = Shift.objects.create(name="s", start_time=datetime.time(9), end_time=datetime.time(17))
        today = datetime.date(2026, 10, 1)
        for kwargs in ({}, {"department": self.department, "user": self.agent}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                ShiftAssignment.objects.create(shift=shift, effective_from=today, **kwargs)
        ShiftAssignment.objects.create(shift=shift, effective_from=today, department=self.department)
        ShiftAssignment.objects.create(shift=shift, effective_from=today, user=self.agent)

    def test_punch_unique_per_device_only(self):
        zk = ZKConfig.objects.create(ip="10.0.0.1", port=4370, timeout=5, password="0",
                                     force_udp=False, ommit_ping=False, is_default=False, last_uid=0)
        ts = datetime.datetime(2026, 10, 1, 9, 0)
        Punch.objects.create(user=self.agent, timestamp=ts, source=PunchSource.DEVICE, device=zk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Punch.objects.create(user=self.agent, timestamp=ts, source=PunchSource.DEVICE, device=zk)
        Punch.objects.create(user=self.agent, timestamp=ts, source=PunchSource.WEB)
        Punch.objects.create(user=self.agent, timestamp=ts, source=PunchSource.WEB)
        self.assertEqual(Punch.objects.filter(device=None).count(), 2)

    def test_fp_id_unique_when_not_blank(self):
        User.objects.create_user(username="a1", password="x", fp_id="")
        User.objects.create_user(username="a2", password="x", fp_id="")
        User.objects.create_user(username="a3", password="x", fp_id="7")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username="a4", password="x", fp_id="7")

    def test_global_policy_exists_after_migrations(self):
        self.assertEqual(DeductionPolicy.objects.filter(department__isnull=True).count(), 1)
