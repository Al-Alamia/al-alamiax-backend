from datetime import date
from decimal import Decimal

from apps.penalties.models import Penalty, PenaltyType
from apps.penalties.types import PenaltyKind
from apps.users.models import User


def make_user(username, role, department=None):
    return User.objects.create_user(username=username, password="x", role=role, department=department)


def make_type(**kw):
    kw.setdefault("name", "Late")
    kw.setdefault("kind", PenaltyKind.DAYS)
    kw.setdefault("default_value", Decimal("0.5"))
    return PenaltyType.objects.create(**kw)


def make_penalty(user, created_by, **kw):
    kw.setdefault("title", "Late")
    kw.setdefault("date", date(2026, 10, 1))
    kw.setdefault("kind", PenaltyKind.DAYS)
    kw.setdefault("value", Decimal("0.5"))
    return Penalty.objects.create(user=user, created_by=created_by, **kw)
