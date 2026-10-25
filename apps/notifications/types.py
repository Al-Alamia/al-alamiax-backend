from django.db import models


class NotificationKinds(models.TextChoices):
    MANUAL = ("manual", "Manual")  # later phases append system kinds
    REQUEST = ("request", "Request")
