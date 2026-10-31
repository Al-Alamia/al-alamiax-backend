from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import pre_save

from core.models import BaseModel
from apps.users.models import User, create_update_history

from .types import SalaryStatus


class Salary(BaseModel):
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="salaries")
    period = models.CharField(max_length=7)
    status = models.CharField(max_length=10, choices=SalaryStatus.choices, default=SalaryStatus.DRAFT)
    given_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    given_at = models.DateTimeField(null=True, blank=True)

    # snapshot, filled on give
    basic_net = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    commission = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    parts = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "period"], name="salary_unique_user_period"),
        ]

    def __str__(self):
        return f"{self.user_id} {self.period} {self.status}"


class SalaryOverride(BaseModel):
    salary = models.ForeignKey(Salary, on_delete=models.CASCADE, related_name="overrides")
    part_key = models.CharField(max_length=100)
    value = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    reason = models.TextField()
    by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["salary", "part_key"], name="salaryoverride_unique_part"),
            models.CheckConstraint(check=models.Q(value__gte=0), name="salaryoverride_value_non_negative"),
        ]

    def __str__(self):
        return f"{self.salary_id} {self.part_key}"


pre_save.connect(create_update_history, sender=Salary)
