from dataclasses import dataclass
from datetime import date, datetime
from functools import cached_property

from apps.attendance.models import AttendanceSettings
from apps.attendance.permissions import scoped_users
from apps.attendance.services.periods import period_key_for, period_range


@dataclass
class DashboardContext:
    viewer: object
    now: datetime
    today: date
    period_key: str
    period_start: date
    period_end: date

    @cached_property
    def team_scope(self):
        return scoped_users(self.viewer).exclude(pk=self.viewer.pk)


def build_context(viewer, now: datetime) -> DashboardContext:
    today = now.date()
    start_day = AttendanceSettings.get().period_start_day
    key = period_key_for(today, start_day)
    start, end = period_range(key, start_day)
    return DashboardContext(viewer=viewer, now=now, today=today, period_key=key,
                            period_start=start, period_end=end)
