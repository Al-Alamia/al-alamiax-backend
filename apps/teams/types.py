from django.db import models


class PlanKind(models.TextChoices):
    PERSONAL = ("personal", "Personal")
    TEAM = ("team", "Team")


class PlanMetric(models.TextChoices):
    LEAD_COUNT = ("lead_count", "Lead count")
    DEAL_COUNT = ("deal_count", "Deal count")
    SALES_AMOUNT = ("sales_amount", "Sales amount")


class TierKind(models.TextChoices):
    FLAT = ("flat", "Flat")
    UNIT = ("unit", "Per unit")
    PERCENT = ("percent", "Percent")


class TierVariant(models.TextChoices):
    NORMAL = ("normal", "Normal")
    AMERICAN = ("american", "American")
