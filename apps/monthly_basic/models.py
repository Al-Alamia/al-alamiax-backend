from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import pre_save

from core.models import BaseModel
from apps.users.models import User, create_update_history

from .types import BasicStatus

ZERO = Decimal("0")


def _money(**kw):
    return models.DecimalField(max_digits=10, decimal_places=2, default=ZERO,
                               validators=[MinValueValidator(ZERO)], **kw)


class MonthlyBasic(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="monthly_basics")
    period = models.CharField(max_length=7)

    kpi = _money()
    gift = _money()
    other_deduction = _money()
    days_adjustment = models.DecimalField(max_digits=5, decimal_places=1, default=ZERO)
    kpi_note = models.TextField(blank=True)
    gift_note = models.TextField(blank=True)
    days_adjustment_note = models.TextField(blank=True)
    other_deduction_note = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=BasicStatus.choices, default=BasicStatus.DRAFT)
    given_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    given_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    # snapshot, filled on give
    basic = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    daily_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    penalty_money = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    deduction_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    net = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    attendance_days = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    penalty_days = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    deduction_days = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    leave_days = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "period"], name="monthlybasic_unique_user_period"),
        ]

    def __str__(self):
        return f"{self.user_id} {self.period} {self.status}"


pre_save.connect(create_update_history, sender=MonthlyBasic)
