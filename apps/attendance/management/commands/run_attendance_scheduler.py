import time
import traceback
from datetime import datetime, time as dtime, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.device_sync import SyncBusy, sync_all
from apps.attendance.services.nightly import run_nightly
from apps.users.models import ZKConfig

NIGHTLY_AT = dtime(3, 0)
LOOP_SECONDS = 60


def _now() -> datetime:
    return datetime.now()


class Command(BaseCommand):
    help = "Periodically sync devices and run the nightly attendance pass"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run a single iteration and exit")

    last_sync_attempt = None  # in-memory: at most one sync attempt per interval, success or not

    def log(self, message: str) -> None:
        self.stdout.write(f"[{_now():%Y-%m-%d %H:%M:%S}] {message}")
        self.stdout.flush()

    def handle(self, *args, **options):
        self.log("attendance scheduler started")
        while True:
            self.tick(_now())
            if options["once"]:
                return
            time.sleep(LOOP_SECONDS)

    def tick(self, now: datetime) -> None:
        try:
            self.maybe_sync(now)
        except Exception:
            self.log("device sync failed:\n" + traceback.format_exc())
        try:
            self.maybe_nightly(now)
        except Exception:
            self.log("nightly pass failed:\n" + traceback.format_exc())

    def maybe_sync(self, now: datetime) -> None:
        interval = timedelta(minutes=AttendanceSettings.get().device_sync_minutes)
        if self.last_sync_attempt is not None and now - self.last_sync_attempt < interval:
            return
        threshold = now - interval
        if not ZKConfig.objects.filter(Q(last_synced_at__isnull=True) | Q(last_synced_at__lt=threshold)).exists():
            return
        self.last_sync_attempt = now
        try:
            results = sync_all(now)
        except SyncBusy:
            return
        for r in results:
            self.log(f"sync {r['device']}: " + (f"{r['new_punches']} new punches" if r["ok"]
                                                  else f"FAILED {r['error']}"))

    def maybe_nightly(self, now: datetime) -> None:
        settings = AttendanceSettings.get()
        if now.time() < NIGHTLY_AT or settings.last_nightly_run == now.date():
            return
        touched = run_nightly(now)
        settings.last_nightly_run = now.date()
        settings.save(update_fields=["last_nightly_run"])
        self.log(f"nightly pass done ({touched} days)")
