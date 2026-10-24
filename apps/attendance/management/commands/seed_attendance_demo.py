import random
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save

from apps.attendance.models import (AttendanceDay, DeductionPolicy, DeductionTier, Holiday, Punch,
                                    Shift, ShiftAssignment)
from apps.attendance.services.evaluate import recalculate
from apps.attendance.services.shifts import resolve_shift, shift_window
from apps.attendance.types import PunchSource, TierKind
from apps.users.models import Department, User, ZKConfig, fp_signal
from apps.users.types import UserTypes

DEMO_PASSWORD = "demo12345"
WEEKEND = [4, 5]  # Fri, Sat
GLOBAL_TIERS = [(TierKind.LATE, 15, 0.25), (TierKind.LATE, 60, 0.5), (TierKind.LATE, 120, 1),
                (TierKind.EARLY_LEAVE, 30, 0.25), (TierKind.EARLY_LEAVE, 120, 0.5)]
DEPARTMENT_TIERS = [(TierKind.LATE, 10, 0.25), (TierKind.LATE, 45, 0.5),
                    (TierKind.EARLY_LEAVE, 20, 0.25)]
FALLBACK_DEPARTMENTS = ["Demo Sales", "Demo Marketing"]


class Command(BaseCommand):
    help = "Seed demo attendance data (shifts, policies, holidays, punches) and evaluate it"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=60)
        parser.add_argument("--reset", action="store_true",
                            help="Delete demo punches and evaluated days, then reseed")
        parser.add_argument("--force", action="store_true", help="Allow running when DEBUG is off")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to seed demo data unless DEBUG is on; pass --force to override")
        days = options["days"]
        if days < 2:
            raise CommandError("--days must be at least 2")

        today = date.today()
        start, end = today - timedelta(days=days), today - timedelta(days=1)
        rng = random.Random(42)

        with transaction.atomic():
            morning, night = self._shifts()
            departments = self._departments()
            new_users = self._demo_users(departments)
            assignments = self._assignments(departments, morning, night, start, days)
            self._holidays(start, end)
            self._policies(departments[-1])
            users = list(User.objects.filter(is_active=True, department__in=departments)
                         .order_by("username"))
            if options["reset"]:
                Punch.objects.filter(is_demo=True).delete()
                AttendanceDay.objects.filter(user__in=users, date__range=(start, end)).delete()
            punches = self._punches(users, start, end, rng)
            evaluated = recalculate(start, end, users, now=datetime.now())

        self.stdout.write(self.style.SUCCESS(
            f"Seeded attendance demo {start} .. {end}: shifts={Shift.objects.count()}, "
            f"assignments created={assignments}, users created={new_users} (seeded {len(users)}), "
            f"punches created={punches}, days evaluated={evaluated}"))

    def _shifts(self):
        morning, _ = Shift.objects.update_or_create(
            name="Morning", defaults=dict(start_time=time(9, 0), end_time=time(17, 0),
                                          weekend_days=WEEKEND, grace_minutes=10, active=True))
        night, _ = Shift.objects.update_or_create(
            name="Night", defaults=dict(start_time=time(22, 0), end_time=time(6, 0),
                                        weekend_days=WEEKEND, grace_minutes=0, active=True))
        return morning, night

    def _departments(self):
        # real departments first, so earlier-seeded demo departments never reshuffle the choice
        departments = list(Department.objects.exclude(name__in=FALLBACK_DEPARTMENTS).order_by("name")[:2])
        for name in FALLBACK_DEPARTMENTS:
            if len(departments) >= 2:
                break
            dept, _ = Department.objects.get_or_create(name=name)
            if dept not in departments:
                departments.append(dept)
        return departments

    def _demo_users(self, departments) -> int:
        if User.objects.count() >= 5:
            return 0
        spec = [("demo_agent1", UserTypes.AGENT, 0), ("demo_agent2", UserTypes.AGENT, 0),
                ("demo_agent3", UserTypes.AGENT, 1), ("demo_agent4", UserTypes.AGENT, 1),
                ("demo_manager", UserTypes.MANAGER, 0)]
        created = 0
        # the post_save signal tries to reach a fingerprint device for every new user
        was_connected = post_save.disconnect(fp_signal, sender=User)
        try:
            for username, role, dept_index in spec:
                if User.objects.filter(username=username).exists():
                    continue
                User.objects.create_user(username=username, password=DEMO_PASSWORD, role=role,
                                         department=departments[dept_index])
                created += 1
        finally:
            if was_connected:
                post_save.connect(fp_signal, sender=User)
        return created

    def _assignments(self, departments, morning, night, start: date, days: int) -> int:
        plan = [(departments[0], morning, start), (departments[0], night, start + timedelta(days=days // 2))]
        plan += [(d, morning, start) for d in departments[1:]]
        created = 0
        for dept, shift, effective_from in plan:
            _, was_created = ShiftAssignment.objects.update_or_create(
                department=dept, effective_from=effective_from, defaults={"shift": shift})
            created += was_created
        return created

    def _holidays(self, start: date, end: date):
        span = (end - start).days + 1
        picks = []
        for offset in (span // 4, (span * 3) // 4):
            d = start + timedelta(days=offset)
            while d.weekday() in WEEKEND or d in picks:
                d += timedelta(days=1)
            if d > end:  # walk back for very short ranges
                d = end
                while d.weekday() in WEEKEND or d in picks:
                    d -= timedelta(days=1)
            picks.append(d)
        for d, name in zip(picks, ("Demo National Day", "Demo Founders Day")):
            Holiday.objects.get_or_create(date=d, department=None, defaults={"name": name})

    def _policies(self, department):
        global_policy = DeductionPolicy.objects.filter(department__isnull=True).first() or DeductionPolicy()
        global_policy.monthly_late_allowance, global_policy.absence_days = 3, 1.0
        global_policy.save()
        dept_policy, _ = DeductionPolicy.objects.get_or_create(department=department)
        dept_policy.monthly_late_allowance, dept_policy.absence_days = 1, 1.0
        dept_policy.save()
        for policy, tiers in ((global_policy, GLOBAL_TIERS), (dept_policy, DEPARTMENT_TIERS)):
            for kind, minutes, deduction in tiers:
                DeductionTier.objects.update_or_create(policy=policy, kind=kind, min_minutes=minutes,
                                                       defaults={"deduction_days": deduction})

    def _punches(self, users, start: date, end: date, rng: random.Random) -> int:
        holidays = set(Holiday.objects.filter(date__range=(start, end), department__isnull=True)
                       .values_list("date", flat=True))
        hr = (User.objects.filter(is_active=True)
              .filter(Q(is_superuser=True) | Q(role__in=[UserTypes.HR, UserTypes.OWNER]))
              .order_by("username").first())
        zk = ZKConfig.objects.order_by("-is_default", "ip").first()
        now = datetime.now()
        created = 0
        for user in users:
            d = start
            while d <= end:
                # rng is always advanced so skipped days do not change later outcomes
                roll, jitter = rng.random(), [rng.random() for _ in range(4)]
                sources = [rng.random(), rng.random()]
                shift = resolve_shift(user, d)
                if shift is not None and d.weekday() not in (shift.weekend_days or []) \
                        and d not in holidays:
                    window = shift_window(shift, d)
                    exists = Punch.objects.filter(user=user, is_demo=True,
                                                  timestamp__gte=window.window_start,
                                                  timestamp__lt=window.window_end).exists()
                    if not exists:
                        for ts, src in zip(self._times(roll, jitter, shift, window), sources):
                            if ts > now:
                                continue
                            Punch.objects.create(user=user, timestamp=ts, is_demo=True,
                                                 **self._source(src, user, zk, hr))
                            created += 1
                d += timedelta(days=1)
        return created

    @staticmethod
    def _times(roll, jitter, shift, window):
        """Punch timestamps (check-in, check-out) of one working day; empty list = absent."""
        grace = shift.grace_minutes
        late_in = window.expected_start + timedelta(minutes=grace + 16 + int(jitter[0] * 115))
        on_time_in = window.expected_start + timedelta(minutes=int(jitter[0] * (grace + 16)) - 15)
        normal_out = window.expected_end + timedelta(minutes=int(jitter[1] * 30))
        if roll < 0.70:
            return [on_time_in, normal_out]
        if roll < 0.85:
            return [late_in, normal_out]
        if roll < 0.90:
            return [on_time_in, window.expected_end - timedelta(minutes=35 + int(jitter[2] * 95))]
        if roll < 0.95:
            return [on_time_in]
        return []

    @staticmethod
    def _source(roll, user, zk, hr) -> dict:
        if roll < 0.2:
            return dict(source=PunchSource.MANUAL, note="demo correction", created_by=hr)
        if zk is not None and roll < 0.35:
            return dict(source=PunchSource.DEVICE, device=zk)
        return dict(source=PunchSource.WEB, ip="10.0.0.%d" % (sum(map(ord, user.username)) % 200 + 10),
                    browser_id=f"demo-{user.username}")
