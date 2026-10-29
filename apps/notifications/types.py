from django.db import models


class NotificationKinds(models.TextChoices):
    MANUAL = ("manual", "Manual")  # later phases append system kinds
    REQUEST = ("request", "Request")
    PENALTY = ("penalty", "Penalty")
    DEVICE = ("device", "Device")
    TEAM = ("team", "Team")
    PAYROLL = ("payroll", "Payroll")
