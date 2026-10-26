from django.db import models


class PenaltyKind(models.TextChoices):
    DAYS = ("days", "Days")
    MONEY = ("money", "Money")
