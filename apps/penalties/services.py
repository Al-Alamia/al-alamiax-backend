from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.locks import closed_period_for
from apps.attendance.services.periods import period_range
from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds

from .models import Penalty
from .permissions import can_penalize, can_void, is_top
from .types import PenaltyKind

LINK = "/penalties"


class PenaltyError(Exception):
    def __init__(self, type: str, message: str):
        super().__init__(message)
        self.type = type
        self.message = message
        self.status = 403 if type == "forbidden" else 400


def _name(user) -> str:
    return user.get_full_name() or user.username


def _notify(actor, penalty, message: str) -> None:
    if penalty.user_id != actor.pk:
        notify([penalty.user], message, kind=NotificationKinds.PENALTY, title="Penalty",
               link=LINK, sender=actor)


def _validate_value(kind, value) -> None:
    if value is None or value <= 0:
        raise PenaltyError("invalid", "Value must be greater than zero.")
    if kind == PenaltyKind.DAYS and value != value.quantize(Decimal("0.1")):
        raise PenaltyError("invalid", "Days allow at most one decimal place.")
    if kind == PenaltyKind.MONEY and value != value.quantize(Decimal('0.01')):
        raise PenaltyError("invalid", "Money allows at most two decimal places.")


def _assert_open(when: date) -> None:
    key = closed_period_for(when, when)
    if key is not None:
        raise PenaltyError("period_closed", f"Payroll period {key} is closed.")


def create_penalty(actor, data: dict) -> Penalty:
    target, ptype = data["user"], data.get("penalty_type")
    if target.pk == actor.pk and not is_top(actor):
        raise PenaltyError("self_penalty", "You cannot penalise yourself.")
    if not can_penalize(actor, target):
        raise PenaltyError("forbidden", "You may not penalise this user.")
    when: date = data["date"]
    if when > timezone.now().date():
        raise PenaltyError("future_date", "The penalty date cannot be in the future.")
    _assert_open(when)
    title = (data.get("title") or "").strip()
    if ptype is not None:
        if not ptype.is_active:
            raise PenaltyError("inactive_type", "This penalty type is inactive.")
        title, kind = title or ptype.name, ptype.kind
        value = data.get("value") if data.get("value") is not None else ptype.default_value
    else:
        kind, value = data.get("kind"), data.get("value")
        if not (title and kind and value is not None):
            raise PenaltyError("invalid", "Title, kind and value are required without a type.")
        if kind not in PenaltyKind.values:
            raise PenaltyError("invalid", "Invalid kind.")
    _validate_value(kind, value)
    with transaction.atomic():
        penalty = Penalty.objects.create(
            user=target, penalty_type=ptype, title=title, description=data.get("description") or "",
            date=when, kind=kind, value=value, created_by=actor)
        unit = "days" if kind == PenaltyKind.DAYS else "money"
        _notify(actor, penalty,
                f"{_name(actor)} added a penalty: {title} ({value.quantize(Decimal('0.01'))} {unit}) on {when}")
    return penalty


def void_penalty(actor, penalty, reason: str) -> Penalty:
    if penalty.is_voided:
        raise PenaltyError("already_voided", "This penalty is already voided.")
    reason = (reason or "").strip()
    if not reason:
        raise PenaltyError("invalid", "A reason is required.")
    if not can_void(actor, penalty):
        raise PenaltyError("forbidden", "You may not void this penalty.")
    _assert_open(penalty.date)
    with transaction.atomic():
        penalty.voided_at = timezone.now()
        penalty.voided_by = actor
        penalty.void_reason = reason
        penalty.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
        _notify(actor, penalty, f"{_name(actor)} voided the penalty: {penalty.title} on {penalty.date}")
    return penalty


def period_total(user, period_key: str) -> dict:
    start, end = period_range(period_key, AttendanceSettings.get().period_start_day)
    agg = Penalty.objects.filter(user=user, voided_at__isnull=True, date__range=(start, end)).aggregate(
        days=Sum("value", filter=Q(kind=PenaltyKind.DAYS)),
        money=Sum("value", filter=Q(kind=PenaltyKind.MONEY)),
        count=Count("pk"))
    two = Decimal("0.01")
    return {"period": period_key, "start": start.isoformat(), "end": end.isoformat(),
            "days": str((agg["days"] or Decimal(0)).quantize(two)),
            "money": str((agg["money"] or Decimal(0)).quantize(two)),
            "count": agg["count"]}
