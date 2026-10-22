from datetime import date, datetime

from django.test import SimpleTestCase

from utils.working_days import return_days_left, working_days_between


class WorkingDaysTests(SimpleTestCase):
    def test_same_day_is_zero(self):
        self.assertEqual(working_days_between(date(2026, 10, 18), date(2026, 10, 18)), 0)

    def test_end_before_start_is_zero(self):
        self.assertEqual(working_days_between(date(2026, 10, 22), date(2026, 10, 18)), 0)

    def test_sunday_to_thursday(self):
        self.assertEqual(working_days_between(date(2026, 10, 18), date(2026, 10, 22)), 4)

    def test_friday_saturday_skipped_sunday_counts(self):
        self.assertEqual(working_days_between(date(2026, 10, 22), date(2026, 10, 25)), 1)

    def test_return_days_left_full_window(self):
        self.assertEqual(return_days_left(datetime(2026, 10, 18, 9), today=date(2026, 10, 18)), 5)

    def test_return_days_left_exhausted(self):
        self.assertEqual(return_days_left(datetime(2026, 10, 18, 9), today=date(2026, 10, 25)), 0)

    def test_return_days_left_never_negative(self):
        self.assertEqual(return_days_left(datetime(2026, 10, 18, 9), today=date(2026, 11, 30)), 0)

    def test_weekend_does_not_consume_window(self):
        self.assertEqual(return_days_left(datetime(2026, 10, 22, 9), today=date(2026, 10, 24)), 5)
