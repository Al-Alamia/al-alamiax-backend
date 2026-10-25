from django.db import models


class DayStatus(models.TextChoices):
    PRESENT = ("PRESENT", "Present")
    LATE = ("LATE", "Late")
    ABSENT = ("ABSENT", "Absent")
    INCOMPLETE = ("INCOMPLETE", "Incomplete")
    WEEKEND = ("WEEKEND", "Weekend")
    HOLIDAY = ("HOLIDAY", "Holiday")
    NO_SHIFT = ("NO_SHIFT", "No shift")
    LEAVE = ("LEAVE", "Leave")
    EXCUSED = ("EXCUSED", "Excused")


class PunchSource(models.TextChoices):
    DEVICE = ("DEVICE", "Device")
    WEB = ("WEB", "Web")
    MANUAL = ("MANUAL", "Manual")
    REQUEST = ("REQUEST", "Request")


class TierKind(models.TextChoices):
    LATE = ("LATE", "Late")
    EARLY_LEAVE = ("EARLY_LEAVE", "Early leave")


class RequestKind(models.TextChoices):
    LEAVE = ("LEAVE", "Leave")
    LATE_EXCUSE = ("LATE_EXCUSE", "Late excuse")
    EARLY_EXCUSE = ("EARLY_EXCUSE", "Early excuse")
    MISSED_PUNCH = ("MISSED_PUNCH", "Missed punch")
    GENERAL = ("GENERAL", "General")
    CANCELLATION = ("CANCELLATION", "Cancellation")


class RequestStatus(models.TextChoices):
    PENDING = ("PENDING", "Pending")
    APPROVED = ("APPROVED", "Approved")
    REJECTED = ("REJECTED", "Rejected")
    CANCELLED = ("CANCELLED", "Cancelled")
    REVOKED = ("REVOKED", "Revoked")
