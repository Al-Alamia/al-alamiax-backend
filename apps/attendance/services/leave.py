from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from apps.attendance.models import LeaveAllowance, LeaveType, Request
from apps.attendance.types import RequestKind, RequestStatus

from .shifts import is_holiday, resolve_shift

ZERO = Decimal("0")


def working_dates(user, start: date, end: date) -> "list[date]":
    """Dates in [start, end] that ``evaluate_day`` would mark LEAVE for an approved leave."""
    joined = user.date_joined.date()
    out = []
    d = max(start, joined)
    while d <= end:
        shift = resolve_shift(user, d)
        if (shift is not None and d.weekday() not in (shift.weekend_days or [])
                and not is_holiday(user, d)):
            out.append(d)
        d += timedelta(days=1)
    return out


def allowance(user, leave_type, year: int) -> Decimal:
    override = LeaveAllowance.objects.filter(user=user, leave_type=leave_type, year=year).first()
    return Decimal(override.days if override else leave_type.yearly_allowance)


def _requests(user, leave_type, year: int, status: str, exclude=None):
    qs = Request.objects.filter(user=user, kind=RequestKind.LEAVE, leave_type=leave_type,
                                status=status, start_date__year=year)
    return qs.exclude(pk=exclude.pk) if exclude is not None else qs


def used(user, leave_type, year: int, exclude=None) -> Decimal:
    total = _requests(user, leave_type, year, RequestStatus.APPROVED, exclude).aggregate(
        t=Sum("leave_days"))["t"]
    return Decimal(total or ZERO)


def pending(user, leave_type, year: int, exclude=None) -> Decimal:
    return Decimal(sum(len(working_dates(user, r.start_date, r.end_date))
                       for r in _requests(user, leave_type, year, RequestStatus.PENDING, exclude)))


def remaining(user, leave_type, year: int, exclude=None) -> Decimal:
    return allowance(user, leave_type, year) - used(user, leave_type, year, exclude)


def balances(user, year: int) -> "list[dict]":
    return [{"leave_type": {"uuid": lt.uuid, "name": lt.name},
             "allowance": allowance(user, lt, year),
             "used": used(user, lt, year),
             "pending": pending(user, lt, year),
             "remaining": remaining(user, lt, year)}
            for lt in LeaveType.objects.filter(is_active=True, uses_balance=True).order_by("name")]
