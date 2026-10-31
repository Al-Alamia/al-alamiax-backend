from django.db import models
from django.db.models import Q
from django.utils.timezone import now, timedelta

from core.models import BaseModel
from apps.users.models import Project, User

from .types import AdvanceStatus, Category, Direction


def tomorrow():
    # Kept only because historical migration 0009 references it.
    return now() + timedelta(days=1)


class ProjectGroup(BaseModel):
    name = models.CharField(max_length=100)
    projects = models.ManyToManyField(Project, blank=True, related_name="treasury_groups")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    # Case-insensitive uniqueness of `name` is a functional unique index created via RunSQL in
    # migration 0017 (Django 3.2 cannot express UniqueConstraint(Lower("name"))).

    def __str__(self):
        return self.name


class ImportBatch(BaseModel):
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    row_count = models.IntegerField(default=0)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reversal_reason = models.TextField(blank=True)


class Advance(BaseModel):
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="advances")
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    installments = models.PositiveSmallIntegerField()
    start_period = models.CharField(max_length=7)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=AdvanceStatus.choices, default=AdvanceStatus.PENDING)
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    cancel_reason = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name="treasury_advance_amount_positive"),
            models.CheckConstraint(check=Q(installments__gte=1, installments__lte=6),
                                   name="treasury_advance_installments_range"),
            models.UniqueConstraint(fields=["user"], condition=Q(status="pending"),
                                    name="treasury_one_pending_advance_per_user"),
        ]


class AdvanceInstallment(BaseModel):
    advance = models.ForeignKey(Advance, on_delete=models.CASCADE, related_name="schedule")
    period = models.CharField(max_length=7)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["advance", "period"], name="treasury_installment_unique_period"),
        ]


class TreasuryEntry(BaseModel):
    direction = models.CharField(max_length=3, choices=Direction.choices)
    category = models.CharField(max_length=10, choices=Category.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField()
    details = models.CharField(max_length=250)
    group = models.ForeignKey(ProjectGroup, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    advance = models.ForeignKey(Advance, on_delete=models.PROTECT, null=True, blank=True, related_name="entries")
    import_batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="entries")
    reverses = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="reversal")
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversal_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["-date", "-created_at"]
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name="treasury_entry_amount_positive"),
        ]
