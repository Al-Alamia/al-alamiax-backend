from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from django.db.models import Q

from apps.attendance.models import DeductionPolicy, Holiday, Shift, ShiftAssignment

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


def is_holiday(user, d: date) -> bool:
    """True if ``d`` is a global holiday or a holiday of the user's department."""
    q = Q(department__isnull=True)
    if user.department_id is not None:
        q |= Q(department_id=user.department_id)
    return Holiday.objects.filter(q, date=d).exists()


def shift_window(shift: Shift, d: date) -> ShiftWindow:
    start = datetime.combine(d, shift.start_time)
    end = datetime.combine(d, shift.end_time)
    if shift.crosses_midnight:
        end += timedelta(days=1)
    return ShiftWindow(start, end, start - WINDOW_BEFORE, end + WINDOW_AFTER)


def is_closed(window: ShiftWindow, now: datetime) -> bool:
    return now >= window.window_end


def windows_for(user, days) -> "dict[date, ShiftWindow]":
    """Shift windows of ``user`` for each of ``days`` that has a shift."""
    out = {}
    for d in days:
        shift = resolve_shift(user, d)
        if shift is not None:
            out[d] = shift_window(shift, d)
    return out


def owner_day(ts: datetime, windows: "dict[date, ShiftWindow]") -> date:
    """Pure rule: which day owns ``ts``, given the windows of at least ts.date()-1 and ts.date().

    Candidates are ts.date()-1 and ts.date(); a candidate counts if it has a shift whose window
    contains ``ts``. When both do, the day whose expected interval is closest to ``ts`` wins
    (ties go to the later day). With no qualifying candidate the answer is ts.date().
    """
    best = None
    for cand in (ts.date() - timedelta(days=1), ts.date()):
        w = windows.get(cand)
        if w is None or not (w.window_start <= ts < w.window_end):
            continue
        if ts < w.expected_start:
            dist = w.expected_start - ts
        elif ts > w.expected_end:
            dist = ts - w.expected_end
        else:
            dist = timedelta(0)
        if best is None or dist <= best[0]:  # later candidate wins ties
            best = (dist, cand)
    return best[1] if best else ts.date()


def day_for_punch(user, ts: datetime) -> date:
    """The attendance day a punch belongs to (see ``owner_day``)."""
    d = ts.date()
    return owner_day(ts, windows_for(user, [d - timedelta(days=1), d]))


def policy_for(user) -> DeductionPolicy:
    qs = DeductionPolicy.objects.prefetch_related("tiers")
    if user.department_id is not None:
        policy = qs.filter(department_id=user.department_id).first()
        if policy is not None:
            return policy
    policy = qs.filter(department=None).first()
    if policy is None:
        DeductionPolicy.objects.create(department=None)
        policy = qs.get(department=None)
    return policy
