from datetime import time

from django.db import models

from core.models import BaseModel
from apps.users.models import Department, Project, User

from .types import FieldKind, Frequency


class ReportType(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.DAILY)
    edit_window_days = models.PositiveSmallIntegerField(null=True, blank=True)
    departments = models.ManyToManyField(Department, blank=True, related_name="report_types")
    excluded_users = models.ManyToManyField(User, blank=True, related_name="excluded_report_types")
    remind_agents = models.BooleanField(default=False)
    remind_at = models.TimeField(default=time(20, 0))
    digest_leaders = models.BooleanField(default=False)
    last_reminded_on = models.DateField(null=True, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    # Case-insensitive uniqueness of `name` is a functional unique index created via RunSQL in
    # migration 0001 (Django 3.2 cannot express UniqueConstraint(Lower("name"))).

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class ReportSection(BaseModel):
    report_type = models.ForeignKey(ReportType, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.name


class ReportField(BaseModel):
    section = models.ForeignKey(ReportSection, on_delete=models.CASCADE, related_name="fields")
    label = models.CharField(max_length=100)
    kind = models.CharField(max_length=10, choices=FieldKind.choices)
    required = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self):
        return self.label


class ReportSubmission(BaseModel):
    report_type = models.ForeignKey(ReportType, on_delete=models.PROTECT, related_name="submissions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="report_submissions")
    period_start = models.DateField()
    period_end = models.DateField()
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    submitted_at = models.DateTimeField()
    is_late = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["report_type", "user", "period_start"], name="reports_submission_unique_period"),
        ]

    def __str__(self):
        return f"{self.report_type_id} {self.user_id} {self.period_start}"


class ReportValue(BaseModel):
    submission = models.ForeignKey(ReportSubmission, on_delete=models.CASCADE, related_name="values")
    field = models.ForeignKey(ReportField, on_delete=models.PROTECT, related_name="values")
    number = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    text = models.CharField(max_length=500, blank=True)
    accounts = models.JSONField(default=list)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["submission", "field"], name="reports_value_unique_field"),
        ]
