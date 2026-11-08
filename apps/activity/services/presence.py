from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import OuterRef, Subquery

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


def presence_rows(users, now: datetime) -> list:
    users = list(users)
    ids = [u.pk for u in users]
    newest = (PageView.objects.filter(user=OuterRef("user"))
              .order_by("-last_seen_at").values("last_seen_at")[:1])
    latest = {}
    for pv in (PageView.objects.filter(user_id__in=ids, last_seen_at=Subquery(newest))
               .order_by("-created_at")):
        latest.setdefault(pv.user_id, pv)
    seconds = defaultdict(int)
    for uid, started, seen in PageView.objects.filter(
            user_id__in=ids, started_at__date=now.date()
    ).values_list("user_id", "started_at", "last_seen_at"):
        seconds[uid] += int((seen - started).total_seconds())
    cutoff = now - timedelta(seconds=ONLINE_WINDOW)
    rows = []
    for u in users:
        pv = latest.get(u.pk)
        rows.append({
            "user": _user_ref(u),
            "online": bool(pv and pv.last_seen_at >= cutoff),
            "last_seen": pv.last_seen_at.isoformat() if pv else None,
            "current_page": pv.path if pv else None,
            "today_seconds": seconds[u.pk],
            "_seen": pv.last_seen_at if pv else None,
        })
    # last_seen desc, nulls last; then online first (stable sorts)
    rows.sort(key=lambda r: r["_seen"] or datetime.min, reverse=True)
    rows.sort(key=lambda r: not r["online"])
    for r in rows:
        del r["_seen"]
    return rows


def presence_for(user, now: datetime) -> dict:
    return presence_rows([user], now)[0]
