import re
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.attendance.models import AttendanceDay, AttendanceSettings, PeriodClose, PeriodCloseLog
from apps.attendance.permissions import is_hr_plus
from apps.attendance.services.locks import closed_period_for
from apps.attendance.services.periods import period_range
from apps.attendance.types import DayStatus
from apps.notifications.services import notify
from apps.notifications.types import NotificationKinds
from apps.payroll_config.models import BasicSalary
from apps.payroll_config.services import basic_for
from apps.penalties.models import Penalty
from apps.penalties.types import PenaltyKind
from apps.users.admin_permissions import is_top
from apps.users.models import User
from apps.users.types import UserTypes

from .models import MonthlyBasic
from .permissions import can_edit_basic, can_manage_basic
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


# ---- actions -------------------------------------------------------------

MONEY_FIELDS = ("kpi", "gift", "other_deduction")
NOTE_FIELDS = ("kpi_note", "gift_note", "days_adjustment_note", "other_deduction_note")
INPUT_FIELDS = MONEY_FIELDS + ("days_adjustment",) + NOTE_FIELDS
_MAX_MONEY = Decimal("99999999.99")
_MAX_ADJUSTMENT = Decimal("999")
_HALF = Decimal("0.5")


def _today(today):
    return today or date.today()


def _decimal(field, value):
    try:
        d = Decimal(str(value).strip())
    except Exception:
        d = None
    if d is None or not d.is_finite():
        raise BasicError("invalid", f"{field} must be a number.")
    return d


def _clean_inputs(data):
    unknown = set(data) - set(INPUT_FIELDS)
    if unknown:
        raise BasicError("invalid", f"Unknown fields: {', '.join(sorted(unknown))}.")
    clean = {}
    for f in MONEY_FIELDS:
        if f in data:
            d = _decimal(f, data[f])
            if d < 0 or d > _MAX_MONEY:
                raise BasicError("invalid", f"{f} must be between 0 and {_MAX_MONEY}.")
            clean[f] = _q(d)
    if "days_adjustment" in data:
        d = _decimal("days_adjustment", data["days_adjustment"])
        if d % _HALF != 0 or abs(d) > _MAX_ADJUSTMENT:
            raise BasicError("invalid", "days_adjustment must be a multiple of 0.5.")
        clean["days_adjustment"] = d.quantize(_TENTH)
    for f in NOTE_FIELDS:
        if f in data:
            clean[f] = str(data[f] or "").strip()
    return clean


def _assert_open(key, start, end):
    if closed_period_for(start, end) is not None:
        raise BasicError("period_closed", f"Payroll period {key} is closed.")


def _target(actor, user, key, today, *, check_included=True):
    """Common guards for edit/give/ungive; returns nothing, raises BasicError."""
    if not can_manage_basic(actor, user):
        raise BasicError("not_found", "Record not found.")
    if not can_edit_basic(actor, user):
        raise BasicError("forbidden", "You cannot edit this record.")
    start, end = period_bounds(key)
    month_of(key)
    if start > _today(today):
        raise BasicError("future_period", "The period has not started yet.")
    _assert_open(key, start, end)
    if check_included and not included_users(key).filter(pk=user.pk).exists():
        raise BasicError("not_included", "The user has no basic salary for this period.")
    return start, end


def _locked(user, key, create=False):
    qs = MonthlyBasic.objects.select_for_update()
    if create:
        record, _ = qs.get_or_create(user=user, period=key)
        return record
    return qs.filter(user=user, period=key).first()


def update_inputs(actor, user, key, data, *, today=None):
    start, end = _target(actor, user, key, today)
    clean = _clean_inputs(data)
    with transaction.atomic():
        record = _locked(user, key, create=True)
        _assert_open(key, start, end)
        if record.status == BasicStatus.GIVEN:
            raise BasicError("already_given", "The record is already given.")
        for f, v in clean.items():
            setattr(record, f, v)
        if record.days_adjustment != 0 and not record.days_adjustment_note:
            raise BasicError("invalid", "days_adjustment_note is required.")
        if record.other_deduction != 0 and not record.other_deduction_note:
            raise BasicError("invalid", "other_deduction_note is required.")
        record.updated_by = actor
        record.save()
    return record


def give(actor, user, key, *, today=None):
    start, end = _target(actor, user, key, today)
    if _today(today) < end:
        raise BasicError("period_open", "The period has not ended yet.")
    with transaction.atomic():
        record = _locked(user, key, create=True)
        _assert_open(key, start, end)
        if record.status == BasicStatus.GIVEN:
            raise BasicError("already_given", "The record is already given.")
        values = compute(user, key, record)
        for f in SNAPSHOT_FIELDS:
            setattr(record, f, values[f])
        record.status = BasicStatus.GIVEN
        record.given_by = actor
        record.given_at = timezone.now()
        record.save()
        notify([user], f"Your basic for {key} has been given: {record.net:.2f}",
               kind=NotificationKinds.PAYROLL, title="Basic",
               link=f"/users/{user.uuid}/basic-record?period={key}", sender=actor)
    return record


def ungive(actor, user, key):
    from apps.salaries.models import Salary
    from apps.salaries.types import SalaryStatus
    start, end = _target(actor, user, key, None, check_included=False)
    with transaction.atomic():
        record = _locked(user, key)
        if Salary.objects.select_for_update().filter(
                user=user, period=key, status=SalaryStatus.GIVEN).exists():
            raise BasicError("salary_given", "Ungive the salary first.")
        _assert_open(key, start, end)
        if record is None or record.status != BasicStatus.GIVEN:
            raise BasicError("not_given", "The record is not given.")
        for f in SNAPSHOT_FIELDS:
            setattr(record, f, None)
        record.status = BasicStatus.DRAFT
        record.given_by = None
        record.given_at = None
        record.updated_by = actor
        record.save()
    return record


def close_period(actor, key, *, today=None):
    if not is_hr_plus(actor):
        raise BasicError("forbidden", "Only HR can close a period.")
    start, end = period_bounds(key)
    month_of(key)
    with transaction.atomic():
        if PeriodClose.objects.filter(period=key).exists():
            raise BasicError("already_closed", f"Payroll period {key} is already closed.")
        if _today(today) < end:
            raise BasicError("period_open", "The period has not ended yet.")
        included = included_users(key)
        given = MonthlyBasic.objects.filter(
            period=key, status=BasicStatus.GIVEN, user__in=included).count()
        missing = included.count() - given
        if missing:
            raise BasicError("not_all_given", f"{missing} user(s) have not been given their basic.")
        from apps.salaries.models import Salary
        from apps.salaries.types import SalaryStatus
        unpaid = included.count() - Salary.objects.filter(
            period=key, status=SalaryStatus.GIVEN, user__in=included).count()
        if unpaid:
            raise BasicError("not_all_salaries_given",
                             f"{unpaid} user(s) have not been given their salary.")
        closed = PeriodClose.objects.create(
            period=key, start=start, end=end, closed_by=actor, closed_at=timezone.now())
        PeriodCloseLog.objects.create(period=key, action="close", actor=actor)
    return closed


def reopen_period(actor, key, reason):
    if not is_top(actor):
        raise BasicError("forbidden", "Only the owner can reopen a period.")
    month_of(key)
    reason = (reason or "").strip()
    if not reason:
        raise BasicError("invalid", "A reason is required.")
    with transaction.atomic():
        deleted, _ = PeriodClose.objects.filter(period=key).delete()
        if not deleted:
            raise BasicError("not_closed", f"Payroll period {key} is not closed.")
        PeriodCloseLog.objects.create(period=key, action="reopen", actor=actor, reason=reason)
