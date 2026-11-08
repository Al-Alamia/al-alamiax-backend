from django.conf import settings
from django.db import models

from core.models import BaseModel


class Area(models.TextChoices):
    ATTENDANCE = "attendance", "Attendance"
    PEOPLE = "people", "People"
    PAYROLL = "payroll", "Payroll"
    ADVANCES = "advances", "Advances"
    TREASURY = "treasury", "Treasury"
    SALES = "sales", "Sales"
    TEAMS = "teams", "Teams"
    REPORTS = "reports", "Reports"


class ActivityEvent(BaseModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activity_done",
    )
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="activity_received",
    )
    verb = models.CharField(max_length=64)
    area = models.CharField(max_length=16, choices=Area.choices)
    target_type = models.CharField(max_length=32, blank=True)
    target_uuid = models.UUIDField(null=True, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    data = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["created_at"], name="act_event_created_idx"),
            models.Index(fields=["subject", "created_at"], name="act_event_subject_idx"),
            models.Index(fields=["actor", "created_at"], name="act_event_actor_idx"),
            models.Index(fields=["area", "created_at"], name="act_event_area_idx"),
        ]

    def __str__(self):
        return f"{self.verb} ({self.area})"


class PageView(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="page_views",
    )
    path = models.CharField(max_length=200)
    started_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()

    class Meta:
        indexes = [
            models.Index(fields=["user", "last_seen_at"], name="act_pv_user_seen_idx"),
        ]

    def __str__(self):
        return f"{self.user_id} {self.path}"
