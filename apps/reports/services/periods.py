from datetime import date, timedelta

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_key_for, period_range

from ..types import Frequency

_SATURDAY = 5  # date.weekday()


def _week_start(d: date) -> date:
    return d - timedelta(days=(d.weekday() - _SATURDAY) % 7)


def period_for(report_type, d: date) -> "tuple[date, date]":
    if report_type.frequency == Frequency.WEEKLY:
        start = _week_start(d)
        return start, start + timedelta(days=6)
    if report_type.frequency == Frequency.MONTHLY:
        start_day = AttendanceSettings.get().period_start_day
        return period_range(period_key_for(d, start_day), start_day)
    return d, d


def recent_periods(report_type, today: date, count: int) -> "list[tuple[date, date]]":
    """The ``count`` latest periods, newest first, starting with the one containing ``today``."""
    periods = []
    current = period_for(report_type, today)
    for _ in range(count):
        periods.append(current)
        current = period_for(report_type, current[0] - timedelta(days=1))
    return periods
