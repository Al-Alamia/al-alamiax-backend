from datetime import datetime, timedelta

from apps.activity.models import ActivityEvent, PageView

PAGEVIEW_DAYS = 120
EVENT_DAYS = 365


def prune(now: datetime) -> tuple:
    pv, _ = PageView.objects.filter(last_seen_at__lt=now - timedelta(days=PAGEVIEW_DAYS)).delete()
    ev, _ = ActivityEvent.objects.filter(created_at__lt=now - timedelta(days=EVENT_DAYS)).delete()
    return pv, ev
