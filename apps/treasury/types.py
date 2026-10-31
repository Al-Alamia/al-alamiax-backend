from django.db import models


class Direction(models.TextChoices):
    IN = ("in", "In")
    OUT = ("out", "Out")


class Category(models.TextChoices):
    INCOME = ("income", "Income")
    ADVANCE = ("advance", "Advance")
    OPERATING = ("operating", "Operating")
    OTHER = ("other", "Other")


class AdvanceStatus(models.TextChoices):
    PENDING = ("pending", "Pending")
    APPROVED = ("approved", "Approved")
    REJECTED = ("rejected", "Rejected")
    WITHDRAWN = ("withdrawn", "Withdrawn")
    CANCELLED = ("cancelled", "Cancelled")


# `advance` is system-only: never accepted from manual entry or import.
CATEGORIES_BY_DIRECTION = {
    "in": {"income", "other"},
    "out": {"advance", "operating", "other"},
}
