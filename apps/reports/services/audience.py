from datetime import date

from apps.attendance.models import AttendanceDay
from apps.attendance.types import DayStatus
from apps.users.models import User

NON_WORKING = (
    DayStatus.WEEKEND, DayStatus.HOLIDAY, DayStatus.NO_SHIFT, DayStatus.LEAVE, DayStatus.EXCUSED,
)


def required_users(report_type):
    """Active users in the type's departments, minus its excluded users."""
    return (User.objects
            .filter(is_active=True, department__in=report_type.departments.all())
            .exclude(pk__in=report_type.excluded_users.all())
            .distinct())


def not_working_ids(user_ids, start: date, end: date, today: date) -> set:
    """Ids whose every day in [start, min(end, today)] has a non-working AttendanceDay row.

    Missing rows count as working (so the user stays required).
    """
    last = min(end, today)
    if last < start:
        return set()
    days = (last - start).days + 1
    rows = (AttendanceDay.objects
            .filter(user_id__in=list(user_ids), date__range=(start, last), status__in=NON_WORKING)
            .values("user_id", "date").distinct())
    seen: dict = {}
    for r in rows:
        seen[r["user_id"]] = seen.get(r["user_id"], 0) + 1
    return {uid for uid, n in seen.items() if n >= days}


def is_required(report_type, user, start: date, end: date, today: date) -> bool:
    if not required_users(report_type).filter(pk=user.pk).exists():
        return False
    return user.pk not in not_working_ids([user.pk], start, end, today)
