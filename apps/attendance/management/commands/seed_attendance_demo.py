import random
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save

from apps.attendance.models import (DeductionPolicy, DeductionTier, Holiday, LeaveAllowance, LeaveType,
                                    Punch, Request, Shift, ShiftAssignment)
from apps.attendance.services import requests as request_service
from apps.attendance.services.evaluate import recalculate
from apps.attendance.services.leave import working_dates
from apps.attendance.services.shifts import resolve_shift, shift_window
from apps.attendance.types import PunchSource, RequestKind, RequestStatus, TierKind
from apps.users.models import Department, User, ZKConfig, fp_signal
from apps.users.types import UserTypes

DEMO_PASSWORD = "demo12345"
WEEKEND = [4, 5]  # Fri, Sat
GLOBAL_TIERS = [(TierKind.LATE, 15, 0.25), (TierKind.LATE, 60, 0.5), (TierKind.LATE, 120, 1),
                (TierKind.EARLY_LEAVE, 30, 0.25), (TierKind.EARLY_LEAVE, 120, 0.5)]
DEPARTMENT_TIERS = [(TierKind.LATE, 10, 0.25), (TierKind.LATE, 45, 0.5),
                    (TierKind.EARLY_LEAVE, 20, 0.25)]
FALLBACK_DEPARTMENTS = ["Demo Sales", "Demo Marketing"]
DEMO_TAG = "[demo]"  # prefix of every seeded request's details; how reset finds them
LEAVE_TYPES = [  # name, pay %, uses balance, yearly allowance, requires attachment
    ("Annual", 100, True, 21, False), ("Sick", 100, False, 0, True),
    ("Half-paid", 50, False, 0, False), ("Unpaid", 0, False, 0, False)]
TINY_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")


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
            new_users = self._demo_users(start)
            departments = self._departments()
            assignments = self._assignments(departments, morning, night, start, days)
            self._holidays(start, end)
            self._policies(departments[-1])
            users = list(User.objects.filter(is_active=True, department__in=departments)
                         .order_by("username"))
            reset_ranges = self._delete_requests() if options["reset"] else []
            if options["reset"]:
                # only demo punches go; recalculate below upserts/deletes the affected days
                demo_users = User.objects.filter(punches__is_demo=True).distinct()
                users = sorted({*users, *demo_users}, key=lambda u: u.username)
                Punch.objects.filter(is_demo=True).delete()
            punches = self._punches(users, start, end, rng)
            evaluated = recalculate(start, end, users, now=datetime.now())
            for user, first, last in reset_ranges:  # leave/excuse days outside the punch range too
                recalculate(first, last, [user], now=datetime.now())
            self._leave_types()
            requests = self._requests(users, start)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded attendance demo {start} .. {end}: shifts={Shift.objects.count()}, "
            f"assignments created={assignments}, users created={new_users} (seeded {len(users)}), "
            f"punches created={punches}, days evaluated={evaluated}, requests created={requests}"))

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

    def _demo_users(self, start: date) -> int:
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
                # joined at the start of the range, or evaluation would skip every seeded day
                User.objects.create_user(username=username, password=DEMO_PASSWORD, role=role,
                                         department=dept, date_joined=datetime.combine(start, time.min))
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

    # ------------------------------------------------------------------ leave & requests

    @staticmethod
    def _delete_requests() -> list:
        """Delete demo requests (and the punches approving them made); return (user, first, last) to re-evaluate."""
        demo = Request.objects.filter(details__startswith=DEMO_TAG)
        ranges = {}
        for r in demo:
            first, last = ranges.get(r.user, (r.start_date, r.end_date))
            ranges[r.user] = (min(first, r.start_date), max(last, r.end_date))
        Punch.objects.filter(request__in=demo).delete()
        demo.filter(cancels__isnull=False).delete()  # cancels is PROTECT: cancellations go first
        demo.delete()
        return [(user, first, last) for user, (first, last) in ranges.items()]

    def _leave_types(self):
        for name, pay, uses_balance, allowance, needs_file in LEAVE_TYPES:
            LeaveType.objects.get_or_create(name=name, defaults=dict(
                pay_percent=pay, uses_balance=uses_balance, yearly_allowance=allowance,
                requires_attachment=needs_file))

    def _requests(self, users, start: date) -> int:
        """Requests of every kind and status, filed through the service so days and notices are real."""
        if Request.objects.filter(details__startswith=DEMO_TAG).exists():
            return 0
        staff = User.objects.filter(is_active=True).order_by("username")
        hr = staff.filter(Q(is_superuser=True) | Q(role__in=[UserTypes.HR, UserTypes.OWNER])).first()
        requesters = [u for u in users if u.role == UserTypes.AGENT and not u.is_superuser][:2]
        annual = LeaveType.objects.get(name="Annual")
        for user, days in zip(requesters, (25, 15)):  # per-user overrides of the 21-day default
            LeaveAllowance.objects.get_or_create(user=user, leave_type=annual, year=date.today().year,
                                                 defaults={"days": days})
        before = Request.objects.count()
        for index, user in enumerate(requesters):
            manager = staff.filter(role=UserTypes.MANAGER, department=user.department_id).exclude(pk=user.pk).first()
            decider = manager or hr
            if decider is not None:
                _RequestSeeder(user, decider, hr, start).run(full=index == 0)
        return Request.objects.count() - before


class _RequestSeeder:
    """One user's demo requests. Each step takes its own unused working day, so nothing overlaps."""

    def __init__(self, user, decider, hr, start: date):
        today = date.today()
        self.user, self.decider, self.hr = user, decider, hr
        self.past = working_dates(user, start, today - timedelta(days=1))[::-1]  # newest first
        self.future = [d for d in working_dates(user, today + timedelta(days=1), today + timedelta(days=60))
                       if d.year == today.year]
        self.lt = {t.name: t for t in LeaveType.objects.all()}

    def day(self, future=False):
        days = self.future if future else self.past
        return days.pop(0) if days else None

    def file(self, kind, day, note="", **extra):
        attachment = extra.pop("attachment", None)
        data = dict(user=self.user, kind=kind, start_date=day, details=f"{DEMO_TAG} {note or kind}", **extra)
        return request_service.submit(self.user, data, attachment)

    def leave(self, name, future=False, attachment=None):
        day = self.day(future)
        if day is None:
            return None
        return self.file(RequestKind.LEAVE, day, f"{name} leave", leave_type=self.lt[name],
                         attachment=attachment)

    def run(self, full: bool):
        svc, decider = request_service, self.decider
        approve = lambda r: r and svc.approve(decider, r, "Approved (demo)")
        reject = lambda r: r and svc.reject(decider, r, "Rejected (demo)")
        sick = lambda: ContentFile(TINY_PDF, name="sick-note.pdf")

        self.leave("Annual")  # pending
        approve(self.leave("Annual"))
        reject(self.leave("Unpaid"))
        approve(self.leave("Sick", attachment=sick()))
        if not full:
            day = self.day()
            if day:
                approve(self.file(RequestKind.LATE_EXCUSE, day, "Traffic", minutes=30))
            day = self.day()
            if day:
                self.file(RequestKind.GENERAL, day, "Please update my contact details")
            return

        approved = self.leave("Annual")
        approved = approve(approved)
        if approved:  # started and approved: needs a cancellation request
            self.file(RequestKind.CANCELLATION, approved.start_date, "Plans changed", cancels=approved)
        approved = self.leave("Annual")
        approved = approve(approved)
        if approved:
            approve(self.file(RequestKind.CANCELLATION, approved.start_date, "Not needed", cancels=approved))
        future = self.leave("Annual", future=True)
        future = approve(future)
        if future:  # not started yet: the requester cancels directly
            svc.cancel(self.user, future)
        pending = self.leave("Unpaid", future=True)
        if pending:
            svc.cancel(self.user, pending)
        revoked = self.leave("Half-paid")
        revoked = approve(revoked)
        if revoked and self.hr is not None:
            svc.revoke(self.hr, revoked, "Entered by mistake (demo)")

        for kind, minutes, decide in ((RequestKind.LATE_EXCUSE, 30, approve),
                                      (RequestKind.EARLY_EXCUSE, 45, None),
                                      (RequestKind.EARLY_EXCUSE, 20, reject)):
            day = self.day()
            if day:
                req = self.file(kind, day, "Appointment", minutes=minutes)
                if decide:
                    decide(req)
        for decide in (approve, reject, None):
            day = self.day()
            if day:
                punch_time = datetime.combine(day, time(9, 5))
                req = self.file(RequestKind.MISSED_PUNCH, day, "Forgot to punch", punch_time=punch_time)
                if decide:
                    decide(req)
        for decide in (approve, None):
            day = self.day()
            if day:
                req = self.file(RequestKind.GENERAL, day, "Please issue an employment letter")
                if decide:
                    decide(req)
