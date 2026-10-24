from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from apps.attendance.models import DeductionPolicy, Shift, ShiftAssignment

WINDOW_BEFORE = timedelta(hours=4)
WINDOW_AFTER = timedelta(hours=6)


@dataclass
class ShiftWindow:
    expected_start: datetime
    expected_end: datetime
    window_start: datetime
    window_end: datetime


def resolve_shift(user, d: date) -> Optional[Shift]:
    """Newest user assignment effective on ``d``, else newest department assignment, else None."""
    qs = ShiftAssignment.objects.filter(effective_from__lte=d).select_related("shift")
    assignment = qs.filter(user=user).order_by("-effective_from").first()
    if assignment is None and user.department_id is not None:
        assignment = qs.filter(department_id=user.department_id).order_by("-effective_from").first()
    return assignment.shift if assignment else None


def shift_window(shift: Shift, d: date) -> ShiftWindow:
    start = datetime.combine(d, shift.start_time)
    end = datetime.combine(d, shift.end_time)
    if shift.crosses_midnight:
        end += timedelta(days=1)
    return ShiftWindow(start, end, start - WINDOW_BEFORE, end + WINDOW_AFTER)


def is_closed(window: ShiftWindow, now: datetime) -> bool:
    return now >= window.window_end


def day_for_punch(user, ts: datetime) -> date:
    """The attendance day a punch belongs to: yesterday if it falls in yesterday's shift window."""
    prev = ts.date() - timedelta(days=1)
    shift = resolve_shift(user, prev)
    if shift is not None:
        w = shift_window(shift, prev)
        if w.window_start <= ts < w.window_end:
            return prev
    return ts.date()


def policy_for(user) -> DeductionPolicy:
    if user.department_id is not None:
        policy = DeductionPolicy.objects.filter(department_id=user.department_id).first()
        if policy is not None:
            return policy
    policy, _ = DeductionPolicy.objects.get_or_create(department=None)
    return policy
