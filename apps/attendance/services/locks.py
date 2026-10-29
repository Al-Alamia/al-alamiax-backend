from datetime import date
from typing import Optional

from apps.attendance.models import PeriodClose


class PeriodClosed(Exception):
    def __init__(self, period: str):
        self.period = period
        super().__init__(f"Payroll period {period} is closed.")


def closed_period_for(start: date, end: date) -> Optional[str]:
    """Key of a closed period overlapping ``[start, end]``, else None."""
    return (PeriodClose.objects.filter(start__lte=end, end__gte=start)
            .order_by("period").values_list("period", flat=True).first())


def is_date_closed(d: date) -> bool:
    return closed_period_for(d, d) is not None


def assert_open(start: date, end: Optional[date] = None) -> None:
    period = closed_period_for(start, end or start)
    if period is not None:
        raise PeriodClosed(period)
