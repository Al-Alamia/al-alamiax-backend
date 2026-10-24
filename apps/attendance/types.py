from django.db import models


class DayStatus(models.TextChoices):
    PRESENT = ("PRESENT", "Present")
    LATE = ("LATE", "Late")
    ABSENT = ("ABSENT", "Absent")
    INCOMPLETE = ("INCOMPLETE", "Incomplete")
    WEEKEND = ("WEEKEND", "Weekend")
    HOLIDAY = ("HOLIDAY", "Holiday")
    NO_SHIFT = ("NO_SHIFT", "No shift")


class PunchSource(models.TextChoices):
    DEVICE = ("DEVICE", "Device")
    WEB = ("WEB", "Web")
    MANUAL = ("MANUAL", "Manual")


class TierKind(models.TextChoices):
    LATE = ("LATE", "Late")
    EARLY_LEAVE = ("EARLY_LEAVE", "Early leave")
