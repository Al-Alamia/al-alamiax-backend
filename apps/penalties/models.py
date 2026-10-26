from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from core.models import BaseModel
from apps.users.models import User
from .types import PenaltyKind


class PenaltyType(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    kind = models.CharField(max_length=10, choices=PenaltyKind.choices)
    default_value = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Penalty(BaseModel):
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="penalties")
    penalty_type = models.ForeignKey(
        PenaltyType, on_delete=models.PROTECT, null=True, blank=True, related_name="penalties")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    date = models.DateField()
    kind = models.CharField(max_length=10, choices=PenaltyKind.choices)
    value = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="penalties_created")
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="penalties_voided")
    void_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [models.Index(fields=["user", "date"])]

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None

    def __str__(self):
        return f"{self.title} ({self.user_id})"
