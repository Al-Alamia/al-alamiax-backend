from datetime import date, datetime, timedelta
from typing import List, Optional

from apps.attendance.models import AttendanceSettings, Punch
from apps.attendance.types import PunchSource
from apps.users.models import User, ZKConfig

from . import zk_client
from .evaluate import evaluate_and_allow
from .shifts import day_for_punch

LOCK_TIMEOUT = timedelta(minutes=10)


class SyncBusy(Exception):
    pass


def acquire_lock(now: datetime) -> bool:
    """Atomically take the sync lock; a lock older than 10 minutes counts as abandoned."""
    from django.db.models import Q

    AttendanceSettings.get()
    taken = AttendanceSettings.objects.filter(
        Q(sync_started_at__isnull=True) | Q(sync_started_at__lt=now - LOCK_TIMEOUT)
    ).update(sync_started_at=now)
    return taken == 1


def release_lock() -> None:
    AttendanceSettings.objects.update(sync_started_at=None)


def _sync_device(config: ZKConfig, now: datetime) -> int:
    with zk_client.OPEN_DEVICE(config) as session:
        records = session.get_attendance()
    cutoff = config.last_synced_at - timedelta(days=1) if config.last_synced_at else None
    users = {u.fp_id: u for u in User.objects.exclude(fp_id="")}
    wanted = {}
    for r in records:
        user = users.get(r.user_id)
        ts = r.timestamp.replace(microsecond=0)
        if user is None or (cutoff is not None and ts < cutoff):
            continue
        wanted[(user.pk, ts)] = user
    existing = set(Punch.objects.filter(device=config, user_id__in={k[0] for k in wanted})
                   .values_list("user_id", "timestamp"))
    fresh = {k: u for k, u in wanted.items() if k not in existing}
    before = Punch.objects.filter(device=config).count()
    Punch.objects.bulk_create(
        [Punch(user=u, timestamp=ts, source=PunchSource.DEVICE, device=config) for (_, ts), u in fresh.items()],
        ignore_conflicts=True)
    inserted = Punch.objects.filter(device=config).count() - before
    affected = {(u, day_for_punch(u, ts)) for (_, ts), u in fresh.items()}
    for user, d in affected:
        evaluate_and_allow(user, d, now)
    config.last_synced_at = now
    config.save(update_fields=["last_synced_at", "updated_at"])
    return inserted


def sync_all(now: Optional[datetime] = None) -> List[dict]:
    now = now or datetime.now()
    if not acquire_lock(now):
        raise SyncBusy()
    results = []
    try:
        for config in ZKConfig.objects.order_by("name", "ip"):
            result = {"uuid": str(config.uuid), "device": config.name or config.ip, "ok": True,
                      "new_punches": 0, "error": None}
            try:
                result["new_punches"] = _sync_device(config, now)
            except Exception as e:  # one unreachable device must not stop the others
                result.update(ok=False, error=str(e) or e.__class__.__name__)
            results.append(result)
    finally:
        release_lock()
    return results
