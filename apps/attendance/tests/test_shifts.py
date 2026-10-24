import datetime as dt

from apps.attendance.services.shifts import (
    day_for_punch, is_closed, policy_for, resolve_shift, shift_window,
)
from apps.attendance.tests.factories import assign, make_policy, make_shift, punch
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase

D = dt.date


class ShiftResolutionTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.morning = make_shift(name="Morning")

    def test_resolve_user_override_beats_department(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6))
        assign(self.morning, department=self.department)
        assign(night, user=self.agent)
        self.assertEqual(resolve_shift(self.agent, D(2026, 10, 5)), night)
        self.assertEqual(resolve_shift(self.superuser, D(2026, 10, 5)), self.morning)

    def test_resolve_effective_from_switch(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6))
        assign(self.morning, department=self.department, effective_from=D(2026, 9, 1))
        assign(night, department=self.department, effective_from=D(2026, 10, 10))
        self.assertEqual(resolve_shift(self.agent, D(2026, 10, 9)), self.morning)
        self.assertEqual(resolve_shift(self.agent, D(2026, 10, 10)), night)
        self.assertIsNone(resolve_shift(self.agent, D(2026, 8, 31)))

    def test_resolve_none(self):
        self.assertIsNone(resolve_shift(self.agent, D(2026, 10, 5)))

    def test_resolve_user_without_department_uses_only_user_assignments(self):
        assign(self.morning, department=self.department)
        loner = User.objects.create_user(username="loner", password="x", email="l@test.com",
                                         project=self.project)
        self.assertIsNone(loner.department)
        self.assertIsNone(resolve_shift(loner, D(2026, 10, 5)))
        assign(self.morning, user=loner)
        self.assertEqual(resolve_shift(loner, D(2026, 10, 5)), self.morning)

    def test_window_and_closed(self):
        w = shift_window(self.morning, D(2026, 10, 5))
        self.assertEqual(w.expected_start, dt.datetime(2026, 10, 5, 9))
        self.assertEqual(w.expected_end, dt.datetime(2026, 10, 5, 17))
        self.assertEqual(w.window_start, dt.datetime(2026, 10, 5, 5))
        self.assertEqual(w.window_end, dt.datetime(2026, 10, 5, 23))
        self.assertFalse(is_closed(w, dt.datetime(2026, 10, 5, 22, 59)))
        self.assertTrue(is_closed(w, dt.datetime(2026, 10, 5, 23)))

    def test_night_window_crosses_midnight(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6))
        w = shift_window(night, D(2026, 10, 5))
        self.assertEqual(w.expected_end, dt.datetime(2026, 10, 6, 6))
        self.assertEqual(w.window_end, dt.datetime(2026, 10, 6, 12))

    def test_day_for_punch_night(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6))
        assign(night, department=self.department)
        self.assertEqual(day_for_punch(self.agent, dt.datetime(2026, 10, 6, 5, 50)), D(2026, 10, 5))
        self.assertEqual(day_for_punch(self.agent, dt.datetime(2026, 10, 5, 23)), D(2026, 10, 5))

    def test_day_for_punch_day_shift_and_no_shift(self):
        self.assertEqual(day_for_punch(self.agent, dt.datetime(2026, 10, 6, 0, 30)), D(2026, 10, 6))
        assign(self.morning, department=self.department)
        self.assertEqual(day_for_punch(self.agent, dt.datetime(2026, 10, 6, 0, 30)), D(2026, 10, 6))

    def test_policy_for(self):
        glob = make_policy(allowance=1)
        self.assertEqual(policy_for(self.agent), glob)
        dep = make_policy(department=self.department, allowance=3)
        self.assertEqual(policy_for(self.agent), dep)
        other = User.objects.create_user(username="o", password="x", email="o@test.com",
                                         project=self.project,
                                         department=Department.objects.create(name="Other"))
        self.assertEqual(policy_for(other), glob)


class ShiftChangeOwnershipTests(BaseUserTestCase):
    def test_day_for_punch_prefers_closest_shift_on_change(self):
        night = make_shift(name="Night", start_time=dt.time(22), end_time=dt.time(6))
        morning = make_shift(name="Morning")
        assign(night, department=self.department, effective_from=D(2026, 9, 1))
        assign(morning, department=self.department, effective_from=D(2026, 10, 6))
        self.assertEqual(day_for_punch(self.agent, dt.datetime(2026, 10, 6, 9)), D(2026, 10, 6))
        self.assertEqual(day_for_punch(self.agent, dt.datetime(2026, 10, 6, 6, 30)), D(2026, 10, 5))
