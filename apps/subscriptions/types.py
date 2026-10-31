from django.db import models


class SubscriptionKind(models.TextChoices):
    NEW = ("new", "New")
    RENEWAL = ("renewal", "Renewal")


class Currency(models.TextChoices):
    SAR = ("SAR", "SAR")
    USD = ("USD", "USD")
    AED = ("AED", "AED")
    EGP = ("EGP", "EGP")


class PaymentMethod(models.TextChoices):
    BANK_TRANSFER = ("bank_transfer", "Bank Transfer")
    CASH = ("cash", "Cash")
    CARD = ("card", "Card")
    ONLINE = ("online", "Online")
    OTHER = ("other", "Other")


class SubscriptionStatus(models.TextChoices):
    ACTIVE = ("active", "Active")
    EXPIRED = ("expired", "Expired")
    CANCELLED = ("cancelled", "Cancelled")
