from datetime import date
from decimal import Decimal
from typing import Optional

from django.db import models
from django.db.models import F, Q
from django.db.models.signals import pre_save

from core.models import BaseModel
from apps.users.models import Lead, User, create_update_history
from apps.users.types import StockMarkets

from .types import Currency, PaymentMethod, SubscriptionKind, SubscriptionStatus


class Subscription(BaseModel):
    lead = models.ForeignKey(Lead, on_delete=models.PROTECT, related_name="subscriptions")
    kind = models.CharField(max_length=10, choices=SubscriptionKind.choices)
    plan_name = models.CharField(max_length=100)
    market = models.CharField(max_length=20, choices=StockMarkets.choices)
    currency = models.CharField(max_length=3, choices=Currency.choices)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    start_date = models.DateField()
    end_date = models.DateField()
    seller = models.ForeignKey(User, on_delete=models.PROTECT, related_name="subscriptions_sold")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-start_date", "-created_at"]
        constraints = [
            models.CheckConstraint(check=Q(total_amount__gt=Decimal("0")), name="subscription_total_positive"),
            models.CheckConstraint(check=Q(end_date__gte=F("start_date")), name="subscription_dates_ordered"),
        ]

    def status(self, today: Optional[date] = None) -> str:
        today = today or date.today()
        if self.cancelled_at:
            return SubscriptionStatus.CANCELLED
        if self.end_date < today:
            return SubscriptionStatus.EXPIRED
        return SubscriptionStatus.ACTIVE

    def __str__(self):
        return f"{self.plan_name} ({self.lead_id})"


class Payment(BaseModel):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    transaction_id = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=500, blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-paid_on", "-created_at"]
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=Decimal("0")), name="payment_amount_positive"),
        ]


pre_save.connect(create_update_history, sender=Subscription)
pre_save.connect(create_update_history, sender=Payment)
