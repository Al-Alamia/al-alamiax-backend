from django.db import models


class BasicStatus(models.TextChoices):
    DRAFT = ("draft", "Draft")
    GIVEN = ("given", "Given")
