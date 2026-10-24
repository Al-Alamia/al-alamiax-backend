import random
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save

from apps.attendance.models import (DeductionPolicy, DeductionTier, Holiday, Punch,
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
            new_users = self._demo_users()
            departments = self._departments()
            assignments = self._assignments(departments, morning, night, start, days)
            self._holidays(start, end)
            self._policies(departments[-1])
            users = list(User.objects.filter(is_active=True, department__in=departments)
                         .order_by("username"))
            if options["reset"]:
                # only demo punches go; recalculate below upserts/deletes the affected days
                demo_users = User.objects.filter(punches__is_demo=True).distinct()
                users = sorted({*users, *demo_users}, key=lambda u: u.username)
                Punch.objects.filter(is_demo=True).delete()
            punches = self._punches(users, start, end, rng)
            evaluated = recalculate(start, end, users, now=datetime.now())

        self.stdout.write(self.style.SUCCESS(
            f"Seeded attendance demo {start} .. {end}: shifts={Shift.objects.count()}, "
            f"assignments created={assignments}, users created={new_users} (seeded {len(users)}), "
            f"punches created={punches}, days evaluated={evaluated}"))

    def _shifts(self):
        """Existing shifts are reused unchanged; only missing ones are created."""
        morning, _ = Shift.objects.get_or_create(
            name="Morning", defaults=dict(start_time=time(9, 0), end_time=time(17, 0),
                                          weekend_days=WEEKEND, grace_minutes=10, active=True))
        night, _ = Shift.objects.get_or_create(
            name="Night", defaults=dict(start_time=time(22, 0), end_time=time(6, 0),
                                        weekend_days=WEEKEND, grace_minutes=0, active=True))
        return morning, night

    def _departments(self):
        """Up to 2 real departments (by name), then the demo departments that exist or are needed."""
        real = list(Department.objects.exclude(name__in=FALLBACK_DEPARTMENTS).order_by("name")[:2])
        demo = list(Department.objects.filter(name__in=FALLBACK_DEPARTMENTS).order_by("name"))
        for name in FALLBACK_DEPARTMENTS:
            if len(real) + len(demo) >= 2:
                break
            if not any(d.name == name for d in demo):
                demo.append(Department.objects.get_or_create(name=name)[0])
        return real + sorted(demo, key=lambda d: d.name)

    def _demo_users(self) -> int:
        """Create demo users (in the demo departments, never real ones) only on a near-empty install."""
        if User.objects.count() >= 5:
            return 0
        sales, _ = Department.objects.get_or_create(name=FALLBACK_DEPARTMENTS[0])
        marketing, _ = Department.objects.get_or_create(name=FALLBACK_DEPARTMENTS[1])
        spec = [("demo_agent1", UserTypes.AGENT, sales), ("demo_agent2", UserTypes.AGENT, sales),
                ("demo_agent3", UserTypes.AGENT, marketing), ("demo_agent4", UserTypes.AGENT, marketing),
                ("demo_manager", UserTypes.MANAGER, sales)]
        created = 0
        # the post_save signal tries to reach a fingerprint device for every new user
        was_connected = post_save.disconnect(fp_signal, sender=User)
        try:
            for username, role, dept in spec:
                if User.objects.filter(username=username).exists():
                    continue
                User.objects.create_user(username=username, password=DEMO_PASSWORD, role=role,
                                         department=dept)
                created += 1
        finally:
            if was_connected:
                post_save.connect(fp_signal, sender=User)
        return created

    def _assignments(self, departments, morning, night, start: date, days: int) -> int:
        """Only departments with no assignment at all get one; the first of them switches shift."""
        bare = [d for d in departments if not ShiftAssignment.objects.filter(department=d).exists()]
        created = 0
        for index, dept in enumerate(bare):
            ShiftAssignment.objects.create(department=dept, shift=morning, effective_from=start)
            created += 1
            if index == 0:
                ShiftAssignment.objects.create(department=dept, shift=night,
                                               effective_from=start + timedelta(days=days // 2))
                created += 1
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
        """Fill gaps only: a policy that already has tiers (or a department policy) is left alone."""
        global_policy = (DeductionPolicy.objects.filter(department__isnull=True).first()
                         or DeductionPolicy.objects.create())
        if not global_policy.tiers.exists():
            global_policy.monthly_late_allowance, global_policy.absence_days = 3, 1.0
            global_policy.save()
            self._add_tiers(global_policy, GLOBAL_TIERS)
        if not DeductionPolicy.objects.filter(department=department).exists():
            dept_policy = DeductionPolicy.objects.create(department=department, monthly_late_allowance=1,
                                                         absence_days=1.0)
            self._add_tiers(dept_policy, DEPARTMENT_TIERS)

    @staticmethod
    def _add_tiers(policy, tiers):
        for kind, minutes, deduction in tiers:
            DeductionTier.objects.create(policy=policy, kind=kind, min_minutes=minutes,
                                         deduction_days=deduction)

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
                    exists = Punch.objects.filter(user=user,
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
