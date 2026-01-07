from django.db import models

class UserTypes (models.TextChoices):
    AGENT = ("AGENT", "Agent")
    MANAGER = ("MANAGER", "Manager")
    OWNER = ('OWNER','Owner')
    HR = ('HR','HR')


class RequestTypes (models.TextChoices):
    GLOBAL = ("GLOBAL", "Global")
    ANNUAL = ("DEPARTURE", "Departure")
    VACATION = ('VACATION','Vacation')
    LATE = ('LATE','Late')


class RequestStatuses (models.TextChoices):
    PENDING = ("PENDING", "Pending")
    ACCEPTED = ("ACCEPTED", "Accepted")
    REJECTED = ('REJECTED','Rejected')
