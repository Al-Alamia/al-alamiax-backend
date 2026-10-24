from django.core.management.base import BaseCommand, CommandError

from apps.attendance.services.device_sync import SyncBusy, sync_all


class Command(BaseCommand):
    help = "Pull attendance punches from all fingerprint devices"

    def handle(self, *args, **options):
        try:
            results = sync_all()
        except SyncBusy:
            raise CommandError("A sync is already running")
        for r in results:
            line = f"{r['device']}: {r['new_punches']} new punches" if r["ok"] else f"{r['device']}: FAILED {r['error']}"
            self.stdout.write(line)
