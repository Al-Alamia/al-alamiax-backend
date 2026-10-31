from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.treasury.models import Advance, AdvanceInstallment, ProjectGroup, TreasuryEntry
from apps.treasury.types import AdvanceStatus, Category, Direction
from apps.users.tests.base import BaseUserTestCase


class TreasuryModelTests(BaseUserTestCase):
    def _advance(self, **kw):
        data = dict(user=self.agent, amount=Decimal("100"), installments=2, start_period="2026-11")
        data.update(kw)
        return Advance.objects.create(**data)

    def test_entry_amount_must_be_positive(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            TreasuryEntry.objects.create(direction=Direction.IN, category=Category.INCOME,
                                         amount=0, date=date(2026, 10, 1), details="x")

    def test_group_name_unique_case_insensitive(self):
        ProjectGroup.objects.create(name="Ops")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProjectGroup.objects.create(name="ops")

    def test_one_pending_advance_per_user(self):
        self._advance()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._advance()
        self._advance(user=self.superuser)
        self._advance(status=AdvanceStatus.APPROVED)

    def test_installments_range(self):
        for n in (0, 7):
            with self.assertRaises(IntegrityError), transaction.atomic():
                self._advance(installments=n)

    def test_installment_unique_per_period(self):
        adv = self._advance()
        AdvanceInstallment.objects.create(advance=adv, period="2026-11", amount=Decimal("50"))
        with self.assertRaises(IntegrityError), transaction.atomic():
            AdvanceInstallment.objects.create(advance=adv, period="2026-11", amount=Decimal("50"))
