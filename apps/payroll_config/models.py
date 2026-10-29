from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import pre_save

from core.models import BaseModel
from apps.users.models import Department, User, create_update_history


class BasicSalary(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="basic_salaries")
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    effective_from = models.DateField()
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "effective_from"], name="unique_basic_per_user_month"),
        ]

    def __str__(self):
        return f"{self.user_id} {self.amount} @ {self.effective_from}"


class ExchangeRate(BaseModel):
    month = models.DateField(unique=True)
    sar_to_egp = models.DecimalField(
        max_digits=10, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))])
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-month"]

    def __str__(self):
        return f"{self.month}: {self.sar_to_egp}"


class DepartmentRates(BaseModel):
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="rate_sheets")
    effective_from = models.DateField()
    american_lead_price = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "effective_from"], name="unique_rates_per_department_month"),
        ]

    def __str__(self):
        return f"{self.department_id} @ {self.effective_from}"


class DailyBonusStep(BaseModel):
    rates = models.ForeignKey(DepartmentRates, on_delete=models.CASCADE, related_name="steps")
    min_leads = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        ordering = ["min_leads"]
        constraints = [
            models.UniqueConstraint(fields=["rates", "min_leads"], name="unique_step_per_rates"),
        ]

    def __str__(self):
        return f">= {self.min_leads}: {self.amount}"


pre_save.connect(create_update_history, sender=BasicSalary)
pre_save.connect(create_update_history, sender=ExchangeRate)
pre_save.connect(create_update_history, sender=DepartmentRates)
