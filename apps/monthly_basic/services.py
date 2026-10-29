import re
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q, Sum

from apps.attendance.models import AttendanceDay, AttendanceSettings
from apps.attendance.services.periods import period_range
from apps.attendance.types import DayStatus
from apps.payroll_config.models import BasicSalary
from apps.payroll_config.services import basic_for
from apps.penalties.models import Penalty
from apps.penalties.types import PenaltyKind
from apps.users.models import User
from apps.users.types import UserTypes

from .models import MonthlyBasic
from .types import BasicStatus

_KEY_RE = re.compile(r"^(\d{4})-(\d{2})$")
DIVISOR = Decimal(30)
ZERO = Decimal(0)
_CENT = Decimal("0.01")
_TENTH = Decimal("0.1")

SNAPSHOT_FIELDS = ("basic", "daily_rate", "attendance_days", "penalty_days", "deduction_days",
                   "deduction_amount", "penalty_money", "net", "leave_days")


class BasicError(Exception):
    def __init__(self, type, message):
        super().__init__(message)
        self.type = type
        self.message = message

    @property
    def status(self):
        return {"forbidden": 403, "not_found": 404}.get(self.type, 400)


def period_bounds(key):
    try:
        return period_range(key, AttendanceSettings.get().period_start_day)
    except (ValueError, TypeError):
        raise BasicError("invalid", "Invalid period.")


def month_of(key):
    m = _KEY_RE.match(key or "") if isinstance(key, str) else None
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise BasicError("invalid", "Invalid period.")
    return date(int(m.group(1)), int(m.group(2)), 1)


def _q(value, step=_CENT):
    return Decimal(value).quantize(step, rounding=ROUND_HALF_UP)


def _eligible():
    return User.objects.filter(is_active=True, is_superuser=False).exclude(role=UserTypes.OWNER)


def _with_salary_ids(month):
    return BasicSalary.objects.filter(effective_from__lte=month).values("user_id")


def included_users(key):
    return _eligible().filter(pk__in=_with_salary_ids(month_of(key)))


def missing_salary_users(key):
    return _eligible().exclude(pk__in=_with_salary_ids(month_of(key)))


def _assemble(basic, attendance, penalty_days, penalty_money, leave, record):
    inputs = record or MonthlyBasic()
    kpi, gift = Decimal(inputs.kpi or 0), Decimal(inputs.gift or 0)
    other, adjustment = Decimal(inputs.other_deduction or 0), Decimal(inputs.days_adjustment or 0)
    basic = Decimal(basic)
    deduction_days = max(ZERO, Decimal(attendance) + Decimal(penalty_days) + adjustment)
    rate = basic / DIVISOR
    amount = _q(deduction_days * rate)
    penalty_money = _q(penalty_money)
    return {
        "basic": _q(basic), "daily_rate": _q(rate),
        "attendance_days": _q(attendance), "penalty_days": _q(penalty_days),
        "days_adjustment": _q(adjustment, _TENTH), "deduction_days": _q(deduction_days),
        "deduction_amount": amount, "penalty_money": penalty_money,
        "other_deduction": _q(other), "kpi": _q(kpi), "gift": _q(gift),
        "net": _q(basic - amount - penalty_money - other + kpi + gift),
        "leave_days": _q(leave, _TENTH),
    }


def _snapshot(record):
    return {
        "basic": record.basic, "daily_rate": record.daily_rate,
        "attendance_days": record.attendance_days, "penalty_days": record.penalty_days,
        "days_adjustment": _q(record.days_adjustment, _TENTH), "deduction_days": record.deduction_days,
        "deduction_amount": record.deduction_amount, "penalty_money": record.penalty_money,
        "other_deduction": _q(record.other_deduction), "kpi": _q(record.kpi), "gift": _q(record.gift),
        "net": record.net, "leave_days": record.leave_days,
    }


def _is_given(record):
    return record is not None and record.status == BasicStatus.GIVEN


def compute(user, key, record=None):
    if _is_given(record):
        return _snapshot(record)
    start, end = period_bounds(key)
    basic = basic_for(user, month_of(key)) or ZERO
    att = AttendanceDay.objects.filter(user=user, date__range=(start, end)).aggregate(
        days=Sum("deduction_days"), leave=Count("pk", filter=Q(status=DayStatus.LEAVE)))
    pen = Penalty.objects.filter(user=user, voided_at__isnull=True, date__range=(start, end)).aggregate(
        days=Sum("value", filter=Q(kind=PenaltyKind.DAYS)),
        money=Sum("value", filter=Q(kind=PenaltyKind.MONEY)))
    return _assemble(basic, Decimal(str(att["days"] or 0)), pen["days"] or ZERO,
                     pen["money"] or ZERO, att["leave"], record)


def compute_many(users, key):
    """Same result as ``compute`` per user, with a fixed number of queries."""
    start, end = period_bounds(key)
    month = month_of(key)
    ids = [u.pk for u in users]

    salaries = {}
    for row in (BasicSalary.objects.filter(user_id__in=ids, effective_from__lte=month)
                .order_by("user_id", "effective_from")):
        salaries[row.user_id] = row.amount  # ascending: last one wins

    att = {r["user_id"]: r for r in AttendanceDay.objects.filter(
        user_id__in=ids, date__range=(start, end)).order_by().values("user_id").annotate(
        days=Sum("deduction_days"), leave=Count("pk", filter=Q(status=DayStatus.LEAVE)))}

    pen = defaultdict(lambda: {PenaltyKind.DAYS: ZERO, PenaltyKind.MONEY: ZERO})
    for r in (Penalty.objects.filter(user_id__in=ids, voided_at__isnull=True, date__range=(start, end))
              .order_by().values("user_id", "kind").annotate(total=Sum("value"))):
        pen[r["user_id"]][r["kind"]] = r["total"] or ZERO

    records = {r.user_id: r for r in MonthlyBasic.objects.filter(user_id__in=ids, period=key)}

    result = {}
    for uid in ids:
        record = records.get(uid)
        if _is_given(record):
            result[uid] = _snapshot(record)
            continue
        a = att.get(uid)
        p = pen[uid]
        result[uid] = _assemble(
            salaries.get(uid, ZERO), Decimal(str(a["days"] or 0)) if a else ZERO,
            p[PenaltyKind.DAYS], p[PenaltyKind.MONEY], a["leave"] if a else 0, record)
    return result
