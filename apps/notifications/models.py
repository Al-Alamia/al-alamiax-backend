from django.db import models

from apps.users.models import User
from core.models import BaseModel

from .types import NotificationKinds


class Notification(BaseModel):
    kind = models.CharField(max_length=40, choices=NotificationKinds.choices, default=NotificationKinds.MANUAL)
    title = models.CharField(max_length=120, blank=True)
    message = models.CharField(max_length=1000)
    link = models.CharField(max_length=300, blank=True)  # in-app path, e.g. "/requests?uuid=..."
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="notifications_sent")
    audience = models.JSONField(default=dict, blank=True)  # what was picked, for display
    expires_at = models.DateTimeField(null=True, blank=True)
    retracted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or self.message[:40]


class NotificationRecipient(BaseModel):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="recipients")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["notification", "user"], name="unique_notification_recipient"),
        ]
        indexes = [models.Index(fields=["user", "read_at"])]
