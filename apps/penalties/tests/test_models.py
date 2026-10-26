from datetime import date

from django.db.models import ProtectedError

from apps.users.tests.base import BaseUserTestCase
from apps.penalties.models import Penalty, PenaltyType
from apps.penalties.types import PenaltyKind


class PenaltyModelTests(BaseUserTestCase):
    def _make(self, ptype=None, d=date(2026, 10, 1)):
        return Penalty.objects.create(
            user=self.agent, penalty_type=ptype, title="Late", description="desc",
            date=d, kind=PenaltyKind.DAYS, value="0.50", created_by=self.superuser)

    def test_penalty_defaults(self):
        t = PenaltyType.objects.create(name="Late", kind=PenaltyKind.DAYS, default_value="0.5")
        p = self._make(t)
        self.assertFalse(p.is_voided)
        self.assertTrue(t.is_active)
        self.assertEqual((p.title, p.description, p.kind), ("Late", "desc", "days"))
        self.assertEqual(p.void_reason, "")

    def test_type_protected(self):
        t = PenaltyType.objects.create(name="Late", kind=PenaltyKind.DAYS, default_value="0.5")
        self._make(t)
        with self.assertRaises(ProtectedError):
            t.delete()

    def test_ordering(self):
        self._make(d=date(2026, 10, 1))
        self._make(d=date(2026, 10, 5))
        self.assertEqual(Penalty.objects.all()[0].date, date(2026, 10, 5))
