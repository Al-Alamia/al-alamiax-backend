from django.db.models import Q

from .models import NotificationRecipient
from .serializers import InboxItemSerializer


def visible_rows(user):
    return (
        NotificationRecipient.objects.filter(user=user, notification__retracted_at__isnull=True)
        .select_related("notification__sender")
        .order_by("-notification__created_at")
    )


def active_rows(user, now):
    return visible_rows(user).filter(Q(notification__expires_at__isnull=True) | Q(notification__expires_at__gt=now))


def snapshot(user, now):
    rows = active_rows(user, now)
    latest = rows.first()
    return {
        "unread": rows.filter(read_at__isnull=True).count(),
        "latest": InboxItemSerializer(latest, context={"now": now}).data if latest else None,
    }
