from datetime import date
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase

from apps.commission.models import UserCommissionDetails
from apps.payroll_config import services
from apps.payroll_config.models import BasicSalary
from apps.payroll_config.services import ConfigError, MissingRate
from apps.payroll_config.tests.factories import make_basic, make_rate
from apps.users.models import Department, User


class BasicTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.u = User.objects.create_user(username="u", password="x", department=self.dept)

    def test_basic_for_resolution(self):
        make_basic(self.u, date(2026, 11, 1), 1000)
        make_basic(self.u, date(2027, 1, 1), 1200)
        self.assertEqual(services.basic_for(self.u, date(2026, 12, 20)), Decimal("1000"))
        self.assertEqual(services.basic_for(self.u, date(2027, 1, 5)), Decimal("1200"))
        self.assertIsNone(services.basic_for(self.u, date(2026, 10, 5)))

    def test_set_basic_past_month(self):
        with self.assertRaises(ConfigError) as cm:
            services.set_basic(self.u, date(2026, 10, 1), 5, "", None, today=date(2026, 11, 15))
        self.assertEqual(cm.exception.code, "past_month")

    def test_set_basic_replaces_same_month(self):
        today = date(2026, 11, 15)
        services.set_basic(self.u, date(2026, 11, 1), 100, "a", None, today=today)
        services.set_basic(self.u, date(2026, 11, 20), 200, "b", None, today=today)
        rows = BasicSalary.objects.filter(user=self.u)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows[0].amount, Decimal("200"))


class RateTests(TestCase):
    def test_missing_rate(self):
        with self.assertRaises(MissingRate) as cm:
            services.rate_for(date(2026, 11, 1))
        self.assertEqual(cm.exception.code, "missing_rate")
        self.assertIsInstance(cm.exception, ConfigError)

    def test_set_rate_updates_in_place(self):
        services.set_rate(date(2026, 11, 9), "13.5", None)
        services.set_rate(date(2026, 11, 1), "14", None)
        self.assertEqual(services.rate_for(date(2026, 11, 30)), Decimal("14"))
        make_rate(date(2026, 12, 1), "1")
        self.assertEqual(services.ExchangeRate.objects.count(), 2)

    def test_delete_missing(self):
        with self.assertRaises(ConfigError) as cm:
            services.delete_rate(date(2026, 11, 1))
        self.assertEqual(cm.exception.code, "not_found")

    def test_delete(self):
        make_rate(date(2026, 11, 1), "13")
        services.delete_rate(date(2026, 11, 1))
        with self.assertRaises(MissingRate):
            services.rate_for(date(2026, 11, 1))


class DepartmentRatesTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name="Sales", code="sales")
        self.month = date(2026, 11, 1)
        self.today = date(2026, 11, 15)

    def save(self, steps, month=None, price=10):
        return services.save_rates(
            self.dept, month or self.month, price, steps, None, today=self.today)

    def assertCode(self, code, steps, **kw):
        with self.assertRaises(ConfigError) as cm:
            self.save(steps, **kw)
        self.assertEqual(cm.exception.code, code)

    def test_steps_sorted(self):
        rates = self.save([{"min_leads": 10, "amount": 100}, {"min_leads": 5, "amount": 50}])
        self.assertEqual([s.min_leads for s in rates.steps.all()], [5, 10])

    def test_duplicate_min_leads(self):
        self.assertCode("invalid", [{"min_leads": 5, "amount": 1}, {"min_leads": 5, "amount": 2}])

    def test_decreasing_amounts(self):
        self.assertCode("invalid", [{"min_leads": 5, "amount": 100}, {"min_leads": 10, "amount": 50}])

    def test_too_many_steps(self):
        self.assertCode("invalid", [{"min_leads": i, "amount": i} for i in range(1, 12)])

    def test_zero_steps_ok(self):
        self.assertEqual(self.save([]).steps.count(), 0)

    def test_past_month(self):
        self.assertCode("past_month", [], month=date(2026, 10, 1))

    def test_replaces_steps(self):
        self.save([{"min_leads": 5, "amount": 50}])
        rates = self.save([{"min_leads": 7, "amount": 70}])
        self.assertEqual([s.min_leads for s in rates.steps.all()], [7])

    def test_daily_bonus(self):
        rates = self.save([{"min_leads": 5, "amount": 50}, {"min_leads": 10, "amount": 100},
                           {"min_leads": 15, "amount": 150}])
        self.assertEqual(services.daily_bonus(rates, 4), 0)
        self.assertEqual(services.daily_bonus(rates, 5), 50)
        self.assertEqual(services.daily_bonus(rates, 12), 100)
        self.assertEqual(services.daily_bonus(rates, 40), 150)

    def test_no_sheet(self):
        other = Department.objects.create(name="Ops", code="ops")
        self.assertIsNone(services.rates_for(other, self.month))
        self.assertEqual(services.daily_bonus(None, 9), 0)

    def test_rates_for_latest_effective(self):
        self.save([], price=1)
        self.assertEqual(
            services.rates_for(self.dept, date(2027, 3, 4)).american_lead_price, Decimal("1"))
        self.assertIsNone(services.rates_for(self.dept, date(2026, 10, 4)))


class CopyBasicTests(TestCase):
    def test_copy(self):
        dept = Department.objects.create(name="Sales", code="sales")
        a = User.objects.create_user(username="a", password="x", department=dept)
        b = User.objects.create_user(username="b", password="x", department=dept)
        UserCommissionDetails.objects.update_or_create(user=a, defaults={"basic": 5000})
        UserCommissionDetails.objects.update_or_create(user=b, defaults={"basic": 0})
        n = services.copy_basic_salaries(django_apps, date(2026, 11, 17))
        self.assertEqual(n, 1)
        row = BasicSalary.objects.get()
        self.assertEqual((row.user, row.amount, row.effective_from),
                         (a, Decimal("5000"), date(2026, 11, 1)))
