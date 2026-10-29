from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.signals import pre_save

from core.models import BaseModel
from apps.users.models import Department, User, create_update_history
from .types import PlanKind, PlanMetric, TierKind, TierVariant


class Team(BaseModel):
    name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="teams")
    leader = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="team_leader")
    agents = models.ManyToManyField(User, blank=True, related_name="team_agents")
    include_leader_in_total = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class CommissionPlan(BaseModel):
    kind = models.CharField(max_length=10, choices=PlanKind.choices)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True, related_name="commission_plans")
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True, related_name="commission_plans")
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True, related_name="commission_plans")
    metric = models.CharField(max_length=32, choices=PlanMetric.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="plan_target_matches_kind",
                check=(
                    Q(kind=PlanKind.PERSONAL, team__isnull=True)
                    & (Q(department__isnull=False, user__isnull=True)
                       | Q(department__isnull=True, user__isnull=False))
                ) | Q(kind=PlanKind.TEAM, team__isnull=False,
                      department__isnull=True, user__isnull=True),
            ),
            models.UniqueConstraint(
                fields=["department", "metric"], condition=Q(department__isnull=False),
                name="unique_plan_per_department_metric"),
            models.UniqueConstraint(
                fields=["user", "metric"], condition=Q(user__isnull=False),
                name="unique_plan_per_user_metric"),
            models.UniqueConstraint(
                fields=["team", "metric"], condition=Q(team__isnull=False),
                name="unique_plan_per_team_metric"),
        ]

    def __str__(self):
        return f"{self.kind} plan"


class PlanVersion(BaseModel):
    plan = models.ForeignKey(CommissionPlan, on_delete=models.CASCADE, related_name="versions")
    effective_from = models.DateField()
    american_threshold_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "effective_from"], name="unique_version_per_plan_month"),
        ]

    def __str__(self):
        return f"{self.plan_id} @ {self.effective_from}"


class Tier(BaseModel):
    version = models.ForeignKey(PlanVersion, on_delete=models.CASCADE, related_name="tiers")
    variant = models.CharField(
        max_length=10, choices=TierVariant.choices, default=TierVariant.NORMAL)
    min_value = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    max_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    kind = models.CharField(max_length=10, choices=TierKind.choices)
    value = models.DecimalField(
        max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        ordering = ["variant", "min_value"]

    def __str__(self):
        return f"{self.variant} {self.min_value}-{self.max_value}: {self.kind} {self.value}"


pre_save.connect(create_update_history, sender=Team)
pre_save.connect(create_update_history, sender=CommissionPlan)
pre_save.connect(create_update_history, sender=PlanVersion)
