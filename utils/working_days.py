from datetime import date, datetime, timedelta
from typing import Optional

RETURN_WINDOW_DAYS = 5

# Python weekday(): Mon=0 .. Sun=6. Working week is Sun-Thu.
WORKING_WEEKDAYS = {6, 0, 1, 2, 3}


def working_days_between(start: date, end: date) -> int:
    """Count working days (Sun-Thu) in (start, end]. 0 if end <= start."""
    if end <= start:
        return 0
    return sum(
        1
        for offset in range(1, (end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in WORKING_WEEKDAYS
    )


def return_days_left(assigned_at: datetime, today: Optional[date] = None) -> int:
    used = working_days_between(assigned_at.date(), today or date.today())
    return max(0, RETURN_WINDOW_DAYS - used)
