from django.db import models


class Frequency(models.TextChoices):
    DAILY = ("daily", "Daily")
    WEEKLY = ("weekly", "Weekly")
    MONTHLY = ("monthly", "Monthly")


class FieldKind(models.TextChoices):
    NUMBER = ("number", "Number")
    TEXT = ("text", "Text")
    ACCOUNTS = ("accounts", "Accounts")


class SubmissionStatus(models.TextChoices):
    """Computed, never stored."""
    SUBMITTED = ("submitted", "Submitted")
    LATE = ("late", "Late")
    MISSING = ("missing", "Missing")
    NOT_REQUIRED = ("not_required", "Not required")
