import datetime
import itertools

from apps.attendance.models import (
    DeductionPolicy, DeductionTier, LeaveType, Punch, Request, Shift, ShiftAssignment,
)
from apps.attendance.types import PunchSource, RequestStatus, TierKind

_counter = itertools.count(1)


def make_shift(**kw) -> Shift:
    kw.setdefault("name", f"Shift {next(_counter)}")
    kw.setdefault("start_time", datetime.time(9))
    kw.setdefault("end_time", datetime.time(17))
    kw.setdefault("weekend_days", [4, 5])
    kw.setdefault("grace_minutes", 10)
    return Shift.objects.create(**kw)


def assign(shift, department=None, user=None, effective_from=datetime.date(2026, 9, 1)) -> ShiftAssignment:
    return ShiftAssignment.objects.create(
        shift=shift, department=department, user=user, effective_from=effective_from)


def punch(user, ts, source=PunchSource.WEB) -> Punch:
    return Punch.objects.create(user=user, timestamp=ts, source=source)


def make_policy(department=None, allowance=0, absence=1.0, late=(), early=()) -> DeductionPolicy:
    """Create or update the policy for ``department`` (None = the global row seeded by migrations)."""
    policy, _ = DeductionPolicy.objects.get_or_create(department=department)
    policy.monthly_late_allowance = allowance
    policy.absence_days = absence
    policy.save()
    policy.tiers.all().delete()
    for kind, tiers in ((TierKind.LATE, late), (TierKind.EARLY_LEAVE, early)):
        for minutes, days in tiers:
            DeductionTier.objects.create(policy=policy, kind=kind, min_minutes=minutes, deduction_days=days)
    return policy


def make_leave_type(**kw) -> LeaveType:
    kw.setdefault("name", f"Leave {next(_counter)}")
    kw.setdefault("pay_percent", 100)
    return LeaveType.objects.create(**kw)


def make_request(user, kind, start, end=None, status=RequestStatus.APPROVED, **kw) -> Request:
    return Request.objects.create(user=user, kind=kind, start_date=start, end_date=end or start,
                                  status=status, **kw)
