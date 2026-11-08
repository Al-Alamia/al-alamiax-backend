from datetime import datetime, timedelta

from apps.activity.models import PageView

ONLINE_WINDOW = 120  # seconds
MERGE_WINDOW = 90  # seconds
MAX_PATH = 200


def normalize_path(path) -> str:
    if not isinstance(path, str):
        raise ValueError("path must be a string")
    path = path.split("#", 1)[0].split("?", 1)[0]
    if not path.startswith("/"):
        raise ValueError("path must start with '/'")
    return path[:MAX_PATH]


def heartbeat(user, path: str, now: datetime) -> PageView:
    path = normalize_path(path)
    last = PageView.objects.filter(user=user).order_by("-last_seen_at").first()
    if (last is not None and last.path == path
            and now - last.last_seen_at <= timedelta(seconds=MERGE_WINDOW)):
        last.last_seen_at = now
        last.save(update_fields=["last_seen_at", "updated_at"])
        return last
    return PageView.objects.create(user=user, path=path, started_at=now, last_seen_at=now)


def _user_ref(user) -> dict:
    return {
        "uuid": str(user.uuid),
        "name": user.get_full_name().strip() or user.username,
        "email": user.email,
        "role": user.role,
    }


def _row(user, now: datetime) -> dict:
    latest = PageView.objects.filter(user=user).order_by("-last_seen_at").first()
    today = now.date()
    seconds = 0
    for started, seen in PageView.objects.filter(
            user=user, started_at__date=today).values_list("started_at", "last_seen_at"):
        seconds += int((seen - started).total_seconds())
    online = bool(latest and latest.last_seen_at >= now - timedelta(seconds=ONLINE_WINDOW))
    return {
        "user": _user_ref(user),
        "online": online,
        "last_seen": latest.last_seen_at.isoformat() if latest else None,
        "current_page": latest.path if latest else None,
        "today_seconds": seconds,
    }


def presence_for(user, now: datetime) -> dict:
    return _row(user, now)


def presence_rows(users, now: datetime) -> list:
    rows = [_row(u, now) for u in users]
    # last_seen desc, nulls last, then online first (stable sorts)
    rows.sort(key=lambda r: r["last_seen"] or "", reverse=True)
    rows.sort(key=lambda r: not r["online"])
    return rows
