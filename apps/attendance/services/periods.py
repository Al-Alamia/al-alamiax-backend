import calendar
import re
from datetime import date, timedelta

_KEY_RE = re.compile(r"^(\d{4})-(\d{2})$")


def period_range(key: str, start_day: int) -> "tuple[date, date]":
    """Inclusive date range of payroll period ``key`` ('YYYY-MM') ending in that month."""
    m = _KEY_RE.match(key or "")
    if not m:
        raise ValueError(f"Invalid period key: {key!r}")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Invalid period key: {key!r}")
    if start_day == 1:
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    return date(prev_year, prev_month, start_day), date(year, month, start_day) - timedelta(days=1)


def period_key_for(d: date, start_day: int) -> str:
    """Key of the period containing ``d``."""
    year, month = d.year, d.month
    if start_day != 1 and d.day >= start_day:
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{year:04d}-{month:02d}"
