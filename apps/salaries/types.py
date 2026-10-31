from django.db import models


class SalaryStatus(models.TextChoices):
    DRAFT = ("draft", "Draft")
    GIVEN = ("given", "Given")


class PartKind(models.TextChoices):
    PERSONAL = ("personal", "Personal")
    TEAM = ("team", "Team")
    DAILY_BONUS = ("daily_bonus", "Daily bonus")
    AMERICAN_LEADS = ("american_leads", "American leads")
