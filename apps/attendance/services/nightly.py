from datetime import datetime, timedelta

from apps.users.models import User

from .evaluate import recalculate


def run_nightly(now: datetime) -> int:
    """Re-evaluate the last two full days for all active users (catches absences; idempotent)."""
    today = now.date()
    return recalculate(today - timedelta(days=2), today - timedelta(days=1),
                       User.objects.filter(is_active=True), now)
