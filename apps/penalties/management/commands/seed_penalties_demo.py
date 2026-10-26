from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_key_for, period_range
from apps.penalties.models import Penalty, PenaltyType
from apps.penalties.types import PenaltyKind
from apps.users.models import User
from apps.users.types import UserTypes

DEMO_TAG = "[demo]"
TYPES = [  # name, kind, default value
    ("Late without excuse", PenaltyKind.DAYS, Decimal("0.5")),
    ("Unexcused absence", PenaltyKind.DAYS, Decimal("1")),
    ("Policy violation", PenaltyKind.DAYS, Decimal("2")),
    ("Equipment damage", PenaltyKind.MONEY, Decimal("500")),
]
# (type name or None for custom, title, kind, value, days back into the window)
PENALTIES = [
    ("Late without excuse", "Late three times", None, None, 2),
    ("Unexcused absence", "Absent without notice", None, None, 5),
    ("Policy violation", "Shared credentials", None, None, 9),
    ("Equipment damage", "Broken headset", None, None, 12),
    ("Late without excuse", "Late after break", None, None, 16),
    ("Unexcused absence", "No-show on shift", None, None, 21),
    ("Policy violation", "Left workstation unlocked", None, None, 27),
    ("Equipment damage", "Damaged monitor", None, None, 33),
    (None, "Customer complaint follow-up", PenaltyKind.DAYS, Decimal("0.25"), 38),
    (None, "Late return of equipment", PenaltyKind.MONEY, Decimal("150"), 44),
]
VOIDED_INDEX = 4


class Command(BaseCommand):
    help = "Seed demo penalty types and penalties (no notifications are sent)"

    def handle(self, *args, **options):
        with transaction.atomic():
            types = self._types()
            if Penalty.objects.filter(description__contains=DEMO_TAG).exists():
                self.stdout.write("Demo penalties already exist; nothing to add")
                return
            creator = (User.objects.filter(is_active=True, role__in=[UserTypes.HR, UserTypes.OWNER])
                       .order_by("pk").first()
                       or User.objects.filter(is_active=True, is_superuser=True).order_by("pk").first())
            targets = list(User.objects.filter(is_active=True, is_superuser=False)
                           .exclude(pk=getattr(creator, "pk", None)).order_by("username"))
            if creator is None or not targets:
                self.stdout.write("No eligible users (creator and active non-superuser targets); "
                                  "seeded penalty types only")
                return
            count = self._penalties(types, creator, targets)
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(types)} penalty types and {count} penalties"))

    def _types(self):
        types = {}
        for name, kind, value in TYPES:
            types[name], _ = PenaltyType.objects.get_or_create(
                name=name, defaults={"kind": kind, "default_value": value})
        return types

    def _penalties(self, types, creator, targets):
        today = date.today()
        start_day = AttendanceSettings.get().period_start_day
        current = period_range(period_key_for(today, start_day), start_day)[0]
        previous = period_range(period_key_for(current - timedelta(days=1), start_day), start_day)[0]
        for i, (type_name, title, kind, value, back) in enumerate(PENALTIES):
            ptype = types.get(type_name)
            day = max(previous, today - timedelta(days=back))  # spans both periods, never future
            penalty = Penalty(
                user=targets[i % len(targets)], penalty_type=ptype, title=title,
                description=f"{DEMO_TAG} {title}", date=day,
                kind=ptype.kind if ptype else kind,
                value=ptype.default_value if ptype else value, created_by=creator)
            if i == VOIDED_INDEX:
                penalty.voided_at = timezone.now()
                penalty.voided_by = creator
                penalty.void_reason = "Entered by mistake (demo)"
            penalty.save()
        return len(PENALTIES)
