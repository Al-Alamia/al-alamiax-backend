import datetime

from django.test import SimpleTestCase

from apps.attendance.services.periods import period_key_for, period_range


class PeriodTests(SimpleTestCase):
    def test_period_range_26(self):
        self.assertEqual(period_range("2026-10", 26), (datetime.date(2026, 9, 26), datetime.date(2026, 10, 25)))

    def test_period_range_1(self):
        self.assertEqual(period_range("2026-10", 1), (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31)))

    def test_period_range_january_wraps_year(self):
        self.assertEqual(period_range("2026-01", 26), (datetime.date(2025, 12, 26), datetime.date(2026, 1, 25)))

    def test_period_range_invalid_key(self):
        for bad in ("2026-13", "abc", "2026-1x", "", "2026-00"):
            with self.assertRaises(ValueError):
                period_range(bad, 26)

    def test_period_key_for_boundary(self):
        self.assertEqual(period_key_for(datetime.date(2026, 10, 26), 26), "2026-11")
        self.assertEqual(period_key_for(datetime.date(2026, 10, 25), 26), "2026-10")
        self.assertEqual(period_key_for(datetime.date(2026, 12, 30), 26), "2027-01")
        self.assertEqual(period_key_for(datetime.date(2026, 10, 31), 1), "2026-10")
