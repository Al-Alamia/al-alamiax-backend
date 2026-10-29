import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.teams.services import PlanError, evaluate, evaluate_tiers, validate_tiers
from apps.teams.tests.factories import make_plan, make_version
from apps.teams.types import PlanKind
from apps.users.models import Department


def tier(min_, max_, kind, value, variant="normal"):
    return {"variant": variant, "min": min_, "max": max_, "kind": kind, "value": value}


T = [tier(0, 99, "flat", 0), tier(100, 199, "unit", 10), tier(200, None, "unit", 15)]


class EvaluateTiersTests(SimpleTestCase):
    def test_unit_and_flat_tiers(self):
        r = evaluate_tiers(T, 150)
        self.assertEqual((r.amount, r.tier_index, r.variant), (Decimal("1500.00"), 1, "normal"))
        r = evaluate_tiers(T, 99)
        self.assertEqual((r.amount, r.tier_index), (Decimal("0.00"), 0))
        self.assertEqual(evaluate_tiers(T, 100).amount, Decimal("1000.00"))
        self.assertEqual(evaluate_tiers(T, 200).amount, Decimal("3000.00"))
        r = evaluate_tiers(T, 5000)
        self.assertEqual((r.amount, r.tier_index), (Decimal("75000.00"), 2))

    def test_above_bounded_last_tier_uses_last(self):
        self.assertEqual(evaluate_tiers([tier(0, 99, "flat", 500)], 250).amount, Decimal("500.00"))

    def test_below_first_tier_is_zero(self):
        r = evaluate_tiers([tier(50, None, "flat", 5)], 10)
        self.assertEqual(r.amount, Decimal("0.00"))
        self.assertIsNone(r.tier_index)

    def test_percent(self):
        r = evaluate_tiers([tier(0, None, "percent", 3)], Decimal("12345.67"))
        self.assertEqual(r.amount, Decimal("370.37"))

    def test_american_variant(self):
        tiers = T + [tier(0, None, "unit", 20, "american")]
        r = evaluate_tiers(tiers, 10, american_share=Decimal("30"), threshold=Decimal("30"))
        self.assertEqual((r.variant, r.amount), ("american", Decimal("200.00")))
        r = evaluate_tiers(tiers, 10, american_share=Decimal("29.99"), threshold=Decimal("30"))
        self.assertEqual(r.variant, "normal")
        r = evaluate_tiers(tiers, 10, american_share=None, threshold=Decimal("30"))
        self.assertEqual(r.variant, "normal")


class ValidateTiersTests(SimpleTestCase):
    def assert_invalid(self, tiers, index, metric="lead_count", threshold=None):
        with self.assertRaises(PlanError) as ctx:
            validate_tiers(tiers, metric, threshold)
        self.assertEqual(ctx.exception.code, "invalid_tiers")
        self.assertIn(index, [e["index"] for e in ctx.exception.errors])

    def test_valid_returns_normalized_sorted(self):
        out = validate_tiers(list(reversed(T)), "lead_count", None)
        self.assertEqual([t["min_value"] for t in out], [0, 100, 200])
        self.assertIsInstance(out[0]["value"], Decimal)

    def test_overlap(self):
        self.assert_invalid([tier(0, 100, "flat", 1), tier(100, 200, "flat", 1)], 1)

    def test_gap(self):
        self.assert_invalid([tier(0, 99, "flat", 1), tier(101, None, "flat", 1)], 1)

    def test_open_tier_not_last(self):
        self.assert_invalid([tier(0, None, "flat", 1), tier(100, 200, "flat", 1)], 0)

    def test_min_greater_than_max(self):
        self.assert_invalid([tier(10, 5, "flat", 1)], 0)

    def test_no_normal_tiers(self):
        self.assert_invalid([tier(0, None, "flat", 1, "american")], 0, threshold=Decimal("30"))

    def test_american_without_threshold(self):
        self.assert_invalid([tier(0, None, "flat", 1), tier(0, None, "flat", 1, "american")], 1)

    def test_threshold_without_american(self):
        with self.assertRaises(PlanError) as ctx:
            validate_tiers([tier(0, None, "flat", 1)], "lead_count", Decimal("30"))
        self.assertEqual(ctx.exception.code, "invalid_tiers")

    def test_too_many_tiers(self):
        tiers = [tier(i * 10, i * 10 + 9, "flat", 1) for i in range(21)]
        with self.assertRaises(PlanError) as ctx:
            validate_tiers(tiers, "lead_count", None)
        self.assertEqual(ctx.exception.code, "invalid_tiers")

    def test_percent_over_100(self):
        self.assert_invalid([tier(0, None, "percent", 101)], 0)

    def test_count_metric_fraction(self):
        self.assert_invalid([tier(0, Decimal("10.5"), "flat", 1)], 0)

    def test_negative_value(self):
        self.assert_invalid([tier(0, None, "flat", -1)], 0)

    def test_non_numeric(self):
        self.assert_invalid([tier(0, None, "flat", "abc")], 0)

    def test_sales_metric_contiguity(self):
        ok = [tier("0", "999.99", "percent", 1), tier("1000.00", None, "percent", 2)]
        validate_tiers(ok, "sales_amount", None)
        bad = [tier("0", "999.99", "percent", 1), tier("1000.01", None, "percent", 2)]
        self.assert_invalid(bad, 1, metric="sales_amount")


class EvaluateVersionTests(TestCase):
    def test_evaluate_resolves_tier_row(self):
        dept = Department.objects.create(name="D")
        plan = make_plan(PlanKind.PERSONAL, department=dept)
        v = make_version(plan, datetime.date(2026, 11, 1), [
            {"min_value": 0, "max_value": 99, "kind": "flat", "value": 0},
            {"min_value": 100, "max_value": None, "kind": "unit", "value": 10},
        ])
        r = evaluate(v, 150)
        self.assertEqual(r.amount, Decimal("1500.00"))
        self.assertEqual(r.tier.min_value, 100)
        self.assertEqual(evaluate(v, 5).tier.max_value, 99)
