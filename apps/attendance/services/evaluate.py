from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Q

from apps.attendance.models import AttendanceDay, AttendanceSettings, Holiday, Punch, Request
from apps.attendance.types import DayStatus, RequestKind, RequestStatus, TierKind

from .periods import period_key_for, period_range
from .shifts import is_closed, owner_day, policy_for, resolve_shift, shift_window, windows_for


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _tier_days(policy, kind: str, minutes: int) -> float:
    """Deduction of the highest tier of ``kind`` reached by ``minutes`` (0 if none)."""
    tiers = [t for t in policy.tiers.all() if t.kind == kind and t.min_minutes <= minutes]
    return max(tiers, key=lambda t: t.min_minutes).deduction_days if tiers else 0.0


def _deduction(policy, late_minutes: int, early_minutes: int, late_excused: bool) -> float:
    late_part = 0.0 if late_excused else _tier_days(policy, TierKind.LATE, late_minutes)
    early_part = _tier_days(policy, TierKind.EARLY_LEAVE, early_minutes)
    return min(late_part + early_part, policy.absence_days)


def _approved_requests(user, d: date) -> dict:
    """Approved LEAVE / LATE_EXCUSE / EARLY_EXCUSE requests of ``user`` covering ``d``, keyed by kind."""
    found = {}
    qs = (Request.objects.filter(user=user, status=RequestStatus.APPROVED, start_date__lte=d,
                                 end_date__gte=d,
                                 kind__in=[RequestKind.LEAVE, RequestKind.LATE_EXCUSE, RequestKind.EARLY_EXCUSE])
          .select_related("leave_type").order_by("created_at"))
    for req in qs:
        found[req.kind] = req
    return found


def evaluate_day(user, d: date, now: Optional[datetime] = None) -> Optional[AttendanceDay]:
    """Idempotently (re)compute the AttendanceDay of ``user`` on ``d``.

    Returns None (and removes any existing row) for a date before ``user.date_joined`` and for a working day that is still open with no punches.
    The monthly late allowance is not applied here; see ``apply_allowance``.
    """
    now = now or datetime.now()
    fields = dict(status=DayStatus.NO_SHIFT, first_in=None, last_out=None, worked_minutes=0,
                  late_minutes=0, early_leave_minutes=0, deduction_days=0.0,
                  late_excused_by_allowance=False, request=None, excused_late_minutes=0,
                  excused_early_minutes=0, shift=None, shift_name="", expected_start=None,
                  expected_end=None, grace_minutes=0, is_working_day=False, evaluated_at=now)

    def save():
        day, _ = AttendanceDay.objects.update_or_create(user=user, date=d, defaults=fields)
        return day

    if d < user.date_joined.date():  # nothing is owed for days before the user existed
        AttendanceDay.objects.filter(user=user, date=d).delete()
        return None

    shift = resolve_shift(user, d)
    if shift is None:
        return save()

    window = shift_window(shift, d)
    # A punch in this window may belong to a neighbouring day when shifts change; see owner_day
    windows = windows_for(user, [d + timedelta(days=i) for i in (-2, -1, 0, 1)])
    punches = [ts for ts in (Punch.objects.filter(user=user, timestamp__gte=window.window_start,
                                                  timestamp__lt=window.window_end)
                             .order_by("timestamp").values_list("timestamp", flat=True))
               if owner_day(ts, windows) == d]
    first_in = punches[0] if punches else None
    last_out = punches[-1] if len(punches) > 1 else None
    closed = is_closed(window, now)
    holiday_q = Q(department__isnull=True)
    if user.department_id is not None:
        holiday_q |= Q(department_id=user.department_id)
    holiday = Holiday.objects.filter(holiday_q, date=d).exists()
    is_weekend = d.weekday() in (shift.weekend_days or [])
    fields.update(shift=shift, shift_name=shift.name, expected_start=window.expected_start,
                  expected_end=window.expected_end, grace_minutes=shift.grace_minutes,
                  first_in=first_in, last_out=last_out,
                  worked_minutes=_minutes(last_out - first_in) if last_out else 0)

    if is_weekend or holiday:
        fields["status"] = DayStatus.WEEKEND if is_weekend else DayStatus.HOLIDAY
        return save()

    fields["is_working_day"] = True
    policy = policy_for(user)
    requests = _approved_requests(user, d)
    leave = requests.get(RequestKind.LEAVE)
    if leave is not None:
        fields.update(status=DayStatus.LEAVE, request=leave,
                      deduction_days=(1 - leave.leave_type.pay_percent / 100) * policy.absence_days)
        return save()
    if first_in is None:
        if not closed:
            AttendanceDay.objects.filter(user=user, date=d).delete()
            return None
        fields.update(status=DayStatus.ABSENT, deduction_days=policy.absence_days)
        return save()

    late = max(0, _minutes(first_in - window.expected_start) - shift.grace_minutes)
    early = max(0, _minutes(window.expected_end - last_out)) if last_out else 0
    late_req = requests.get(RequestKind.LATE_EXCUSE)
    early_req = requests.get(RequestKind.EARLY_EXCUSE)
    excused_late = min(late_req.minutes or 0, late) if late_req else 0
    excused_early = min(early_req.minutes or 0, early) if early_req else 0
    left_late, left_early = late - excused_late, early - excused_early
    status = DayStatus.LATE if left_late > 0 else DayStatus.PRESENT
    if (late > 0 or early > 0) and left_late == 0 and left_early == 0:
        status = DayStatus.EXCUSED
    if last_out is None and closed:
        status = DayStatus.INCOMPLETE
    covering = late_req if excused_late > 0 else early_req if excused_early > 0 else None
    fields.update(status=status, late_minutes=late, early_leave_minutes=early,
                  excused_late_minutes=excused_late, excused_early_minutes=excused_early,
                  request=covering, deduction_days=_deduction(policy, left_late, left_early, False))
    return save()


def apply_allowance(user, period_key: str) -> None:
    """Excuse the first N late days of the period (by date) and recompute their deductions."""
    start, end = period_range(period_key, AttendanceSettings.get().period_start_day)
    policy = policy_for(user)
    days = AttendanceDay.objects.filter(user=user, date__range=(start, end)).order_by("date")
    remaining = policy.monthly_late_allowance
    for day in days:
        left_late = day.late_minutes - day.excused_late_minutes
        left_early = day.early_leave_minutes - day.excused_early_minutes
        late_day = left_late > 0 and day.status in (DayStatus.LATE, DayStatus.INCOMPLETE)
        excused = late_day and remaining > 0
        if excused:
            remaining -= 1
        deduction = (_deduction(policy, left_late, left_early, excused)
                     if day.status in (DayStatus.PRESENT, DayStatus.LATE, DayStatus.INCOMPLETE)
                     else day.deduction_days)
        if excused != day.late_excused_by_allowance or deduction != day.deduction_days:
            day.late_excused_by_allowance = excused
            day.deduction_days = deduction
            day.save(update_fields=["late_excused_by_allowance", "deduction_days", "updated_at"])


def evaluate_and_allow(user, d: date, now: Optional[datetime] = None) -> Optional[AttendanceDay]:
    """``evaluate_day`` followed by ``apply_allowance`` for the day's period."""
    day = evaluate_day(user, d, now)
    apply_allowance(user, period_key_for(d, AttendanceSettings.get().period_start_day))
    if day is not None:
        day.refresh_from_db()
    return day


@transaction.atomic
def recalculate(start: date, end: date, users, now: Optional[datetime] = None) -> int:
    """Re-evaluate every user/date in [start, end]; returns the number of rows produced."""
    now = now or datetime.now()
    users = list(users)
    start_day = AttendanceSettings.get().period_start_day
    touched = 0
    periods = set()
    for user in users:
        d = start
        while d <= end:
            if evaluate_day(user, d, now) is not None:
                touched += 1
            periods.add((user, period_key_for(d, start_day)))
            d += timedelta(days=1)
    for user, key in periods:
        apply_allowance(user, key)
    _refresh_leave_days(start, end, users)
    return touched


def _refresh_leave_days(start: date, end: date, users) -> None:
    """Set ``leave_days`` of approved leaves touching [start, end] to their LEAVE day count."""
    leaves = Request.objects.filter(user__in=users, kind=RequestKind.LEAVE,
                                    status=RequestStatus.APPROVED, start_date__lte=end,
                                    end_date__gte=start)
    for req in leaves:
        count = req.attendance_days.filter(status=DayStatus.LEAVE).count()
        if req.leave_days != count:
            req.leave_days = count
            req.save(update_fields=["leave_days", "updated_at"])
