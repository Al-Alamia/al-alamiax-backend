"""Seed a development database with connected demo data for every app.

    python manage.py seed               # refuses unless DEBUG is on
    python manage.py seed --months 4    # history length (payroll periods)

Data goes through the domain services wherever they exist, so derived rows (lead logs,
installments, treasury entries, monthly basics, salaries, notifications, update history)
are produced the same way the API produces them. Everything runs in one transaction.
Seeded users are named ``seed_*``; running again when they exist does nothing.
"""
import io
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone

from apps.attendance.management.commands import seed_attendance_demo
from apps.attendance.models import (AttendanceDay, AttendanceSettings, Punch, Request, Shift, ShiftAssignment,
                                    WebPunchPolicy)
from apps.attendance.services.periods import period_key_for, period_range
from apps.monthly_basic import services as basic_service
from apps.notifications.models import NotificationRecipient
from apps.notifications.services import notify
from apps.payroll_config.models import ExchangeRate
from apps.payroll_config.services import save_rates, set_basic
from apps.purposes.models import Purpose
from apps.salaries import services as salary_service
from apps.subscriptions import services as subscription_service
from apps.teams import services as team_service
from apps.teams.models import CommissionPlan
from apps.teams.types import PlanKind, PlanMetric, TierKind, TierVariant
from apps.treasury.services import advances as advance_service
from apps.treasury.services import importer, ledger
from apps.treasury.types import Category, Direction
from apps.users.models import (Department, FingerPrintID, Lead, LeadScreenshot, Project,
                               User, UserFile, ZKConfig, fp_signal)
from apps.users.services import leads as lead_service
from apps.users.types import (AssignmentKinds, CallStatuses, DepartmentCodes, DeviceStatus, FileCategory,
                              LeadStatuses, LeadUpdateTypes, StockMarkets, UserTypes)

DEMO_PASSWORD = "demo12345"  # same as seed_attendance_demo
MARKER = "seed_owner"
DEPARTMENTS = [  # name, code
    ("Sales", DepartmentCodes.SALES), ("Marketing", DepartmentCodes.MARKETING),
    ("Technical", DepartmentCodes.TECHNICAL), ("Administration", DepartmentCodes.OTHER)]
USERS = [  # username, first, last, role, department name, title, basic salary
    ("seed_owner", "Omar", "Farouk", UserTypes.OWNER, "Administration", "Owner", None),
    ("seed_hr", "Hana", "Saleh", UserTypes.HR, "Administration", "HR Specialist", "12000"),
    ("seed_sales_manager", "Karim", "Nabil", UserTypes.MANAGER, "Sales", "Sales Manager", "18000"),
    ("seed_marketing_manager", "Mona", "Adel", UserTypes.MANAGER, "Marketing", "Marketing Manager", "17000"),
    ("seed_sales_lead", "Youssef", "Hassan", UserTypes.AGENT, "Sales", "Team Leader", "11000"),
    ("seed_sales_1", "Ahmed", "Samir", UserTypes.AGENT, "Sales", "Sales Agent", "8000"),
    ("seed_sales_2", "Sara", "Mostafa", UserTypes.AGENT, "Sales", "Sales Agent", "8000"),
    ("seed_sales_3", "Mahmoud", "Ali", UserTypes.AGENT, "Sales", "Sales Agent", "7500"),
    ("seed_sales_4", "Nour", "Ibrahim", UserTypes.AGENT, "Sales", "Sales Agent", "7500"),
    ("seed_marketing_1", "Laila", "Fathy", UserTypes.AGENT, "Marketing", "Marketing Agent", "7000"),
    ("seed_marketing_2", "Tarek", "Gamal", UserTypes.AGENT, "Marketing", "Marketing Agent", "7000"),
    ("seed_marketing_3", "Dina", "Ashraf", UserTypes.AGENT, "Marketing", "Marketing Agent", "6500"),
    ("seed_tech_1", "Mostafa", "Ezzat", UserTypes.AGENT, "Technical", "Developer", "15000"),
]
FIRST = ["Ali", "Fatma", "Khaled", "Reem", "Hassan", "Yara", "Walid", "Salma", "Amr", "Noha",
         "Sherif", "Rana", "Hesham", "Aya", "Ramy", "Mai", "Fady", "Heba", "Ziad", "Nada"]
LAST = ["Mansour", "Kamal", "Zaki", "Fouad", "Lotfy", "Shawky", "Badr", "Helmy", "Rizk", "Sabry"]
PURPOSES = ["Follow-up call", "Contract signing", "Training session", "Client visit", "Internal meeting"]
RATES = {"SAR": Decimal("13.1500"), "USD": Decimal("49.3000"), "AED": Decimal("13.4200")}
TINY_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF\n")


def _png(color) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, format="PNG")
    return buf.getvalue()


def _months_back(d: date, n: int) -> date:
    idx = d.year * 12 + d.month - 1 - n
    return date(idx // 12, idx % 12 + 1, 1)


class _SeedAttendance(seed_attendance_demo.Command):
    """The attendance demo seeder, pointed at the seeded departments and users."""

    def __init__(self, departments, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seed_departments = departments

    def _departments(self):
        return self.seed_departments

    def _demo_users(self, start):
        return 0


class Command(BaseCommand):
    help = "Seed demo data into every table (users, leads, attendance, payroll, treasury, ...)"

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=4,
                            help="Payroll periods of history to generate (2-12, default 4)")
        parser.add_argument("--force", action="store_true", help="Allow running when DEBUG is off")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to seed unless DEBUG is on; pass --force to override")
        months = options["months"]
        if not 2 <= months <= 12:
            raise CommandError("--months must be between 2 and 12")
        if User.objects.filter(username=MARKER).exists():
            self.stdout.write(f"Seed data already exists ({MARKER} found); nothing to do")
            return

        self.rng = random.Random(7)
        self.today = date.today()
        self.start_day = AttendanceSettings.get().period_start_day
        current = period_key_for(self.today, self.start_day)
        # oldest first; the current (open) period is last
        self.periods = [self._shift_key(current, -i) for i in range(months, -1, -1)]
        self.history_start = period_range(self.periods[0], self.start_day)[0]
        self.counts = {}

        # creating a user would otherwise try to reach the fingerprint device
        was_connected = post_save.disconnect(fp_signal, sender=User)
        try:
            with transaction.atomic():
                self._run()
        finally:
            if was_connected:
                post_save.connect(fp_signal, sender=User)

        width = max(map(len, self.counts))
        for name, value in self.counts.items():
            self.stdout.write(f"  {name.ljust(width)}  {value}")
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {self.periods[0]} .. {self.periods[-1]}. Seed users log in with password "
            f"'{DEMO_PASSWORD}' and an approved device id 'seed-device-<username>'."))

    def _run(self):
        self._step("organisation", self._organisation)
        self._step("users & devices", self._users)
        self._step("payroll config", self._payroll_config)
        self._step("teams & plans", self._teams)
        self._step("leads", self._leads)
        self._step("subscriptions", self._subscriptions)
        self._step("attendance", self._attendance)
        self._step("penalties", lambda: call_command("seed_penalties_demo", stdout=io.StringIO()))
        self._step("treasury", self._treasury)
        self._step("advances", self._advances)
        self._step("monthly basics & salaries", self._payroll)
        self._step("notifications & misc", self._misc)

    def _step(self, label, fn):
        self.stdout.write(f"Seeding {label}...")
        fn()

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _shift_key(key, n):
        idx = int(key[:4]) * 12 + int(key[5:7]) - 1 + n
        return f"{idx // 12:04d}-{idx % 12 + 1:02d}"

    def _bounds(self, key):
        return period_range(key, self.start_day)

    def _count(self, name, n=1):
        self.counts[name] = self.counts.get(name, 0) + n

    def _past_day(self, start, end=None):
        end = min(end or self.today, self.today)
        return start + timedelta(days=self.rng.randint(0, max(0, (end - start).days)))

    # ------------------------------------------------------------------ organisation & users

    def _organisation(self):
        self.projects = []
        for name, color in (("Alamia Capital", (30, 64, 175)), ("Alamia Trade", (5, 150, 105))):
            project = Project.objects.filter(name=name).first()
            if project is None:
                project = Project(name=name)
                project.logo.save(f"{name.lower().replace(' ', '-')}.png", ContentFile(_png(color)),
                                  save=False)
                project.save()
                self._count("projects")
            self.projects.append(project)
        self.departments = {}
        for name, code in DEPARTMENTS:
            dept, created = Department.objects.get_or_create(name=name, defaults={"code": code})
            if dept.code != code:
                dept.code = code
                dept.save()
            self.departments[name] = dept
            self._count("departments", int(created))
        for name in PURPOSES:
            self._count("purposes", int(Purpose.objects.get_or_create(name=name)[1]))
        self.zk, created = ZKConfig.objects.get_or_create(
            ip="10.0.0.250", defaults=dict(port=4370, timeout=5, password="0", force_udp=False,
                                           ommit_ping=True, is_default=False, last_uid=0,
                                           name="Seed office device"))
        self._count("zk devices", int(created))

    def _users(self):
        joined = datetime.combine(self.history_start - timedelta(days=30), time(9))
        self.users = {}
        for i, (username, first, last, role, dept, title, _) in enumerate(USERS):
            user = User.objects.create_user(
                username=username, password=DEMO_PASSWORD, first_name=first, last_name=last,
                email=f"{username}@example.com", role=role, title=title,
                department=self.departments[dept], project=self.projects[i % 2],
                fp_id=str(9000 + i), crm_username=username, date_joined=joined)
            profile = user.profile
            profile.phone = f"0100{1000000 + i:07d}"
            profile.about = f"{title} in {dept}."
            profile.save()
            FingerPrintID.objects.create(
                user=user, unique_id=f"seed-device-{username}", name="Seed browser",
                status=DeviceStatus.APPROVED, decided_at=timezone.now(), user_agent="Mozilla/5.0 (seed)")
            self.users[username] = user
        self.owner = self.users["seed_owner"]
        self.hr = self.users["seed_hr"]
        self.admin = (User.objects.filter(is_superuser=True, is_active=True).order_by("date_joined").first()
                      or User.objects.create_superuser("seed_admin", "seed_admin@example.com", DEMO_PASSWORD))
        self.sales = [self.users[f"seed_sales_{i}"] for i in range(1, 5)]
        self.sales_lead = self.users["seed_sales_lead"]
        self.marketing = [self.users[f"seed_marketing_{i}"] for i in range(1, 4)]
        self._count("users", len(self.users))
        # a pending second device and a rejected one, for the device approval screens
        FingerPrintID.objects.create(user=self.sales[0], unique_id="seed-device-pending",
                                     name="New laptop", user_agent="Mozilla/5.0 (seed)")
        FingerPrintID.objects.create(user=self.sales[1], unique_id="seed-device-rejected", name="Unknown",
                                     status=DeviceStatus.REJECTED, decided_by=self.hr,
                                     decided_at=timezone.now(), user_agent="curl/8.0")
        self._count("devices", len(self.users) + 2)
        for user, title, category in ((self.sales[0], "Employment contract", FileCategory.CONTRACT),
                                      (self.sales[0], "National ID", FileCategory.ID),
                                      (self.marketing[0], "Course certificate", FileCategory.CERTIFICATE)):
            f = UserFile(user=user, title=title, category=category, size=len(TINY_PDF),
                         content_type="application/pdf", uploaded_by=self.hr)
            f.file.save("document.pdf", ContentFile(TINY_PDF), save=False)
            f.save()
            self._count("user files")

    # ------------------------------------------------------------------ payroll config & teams

    def _payroll_config(self):
        first_month = _months_back(self.today, len(self.periods))
        for username, *_, amount in USERS:
            if amount:
                set_basic(self.users[username], first_month, amount, "Starting salary", self.hr,
                          today=first_month)
                self._count("basic salaries")
        # two raises in the middle of the history
        raise_month = _months_back(self.today, 1)
        for user, amount in ((self.sales[0], "8800"), (self.marketing[0], "7600")):
            set_basic(user, raise_month, amount, "Annual raise", self.hr, today=raise_month)
            self._count("basic salaries")
        for n in range(len(self.periods) + 1):
            month = _months_back(self.today, n)
            for currency, rate in RATES.items():
                ExchangeRate.objects.update_or_create(
                    month=month, currency=currency,
                    defaults={"rate_to_egp": rate + Decimal(n) / 10, "created_by": self.hr})
                self._count("exchange rates")
        steps = [{"min_leads": 3, "amount": "50"}, {"min_leads": 6, "amount": "120"},
                 {"min_leads": 10, "amount": "250"}]
        for dept, price in (("Marketing", "15"), ("Sales", "0")):
            save_rates(self.departments[dept], first_month, price, steps if dept == "Marketing" else steps[:1],
                       self.hr, today=first_month)
            self._count("department rates")

    def _teams(self):
        sales = self.departments["Sales"]
        self.team = team_service.create_team("Falcons", sales, self.sales_lead, self.sales[:3], True, self.owner)
        team_service.create_team("Eagles", sales, None, [self.sales[3]], False, self.owner)
        self._count("teams", 2)
        first_month = _months_back(self.today, len(self.periods))
        plans = [
            (dict(kind=PlanKind.PERSONAL, department=sales, metric=PlanMetric.DEAL_COUNT), None,
             [dict(min_value=1, max_value=4, kind=TierKind.UNIT, value="150"),
              dict(min_value=5, max_value=None, kind=TierKind.UNIT, value="250")]),
            (dict(kind=PlanKind.PERSONAL, department=self.departments["Marketing"],
                  metric=PlanMetric.LEAD_COUNT), None,
             [dict(min_value=10, max_value=29, kind=TierKind.FLAT, value="500"),
              dict(min_value=30, max_value=None, kind=TierKind.FLAT, value="1200")]),
            (dict(kind=PlanKind.PERSONAL, user=self.sales[0], metric=PlanMetric.SALES_AMOUNT), None,
             [dict(min_value="0.00", max_value=None, kind=TierKind.PERCENT, value="2")]),
            (dict(kind=PlanKind.TEAM, team=self.team, metric=PlanMetric.SALES_AMOUNT), Decimal("40"),
             [dict(min_value="0.00", max_value="49999.99", kind=TierKind.PERCENT, value="1"),
              dict(min_value="50000.00", max_value=None, kind=TierKind.PERCENT, value="2"),
              dict(variant=TierVariant.AMERICAN, min_value="0.00", max_value=None,
                   kind=TierKind.PERCENT, value="3")]),
        ]
        for fields, threshold, tiers in plans:
            plan = CommissionPlan.objects.create(**fields)
            team_service.save_version(plan, first_month, tiers, self.owner, threshold=threshold,
                                      today=first_month)
            self._count("commission plans")
        # a later version of the department deal plan, to show plan history
        plan = CommissionPlan.objects.get(department=sales, metric=PlanMetric.DEAL_COUNT)
        month = _months_back(self.today, 1)
        team_service.save_version(plan, month, [
            dict(min_value=1, max_value=4, kind=TierKind.UNIT, value="175"),
            dict(min_value=5, max_value=None, kind=TierKind.UNIT, value="275")],
            self.owner, threshold=None, today=month)

    # ------------------------------------------------------------------ leads & subscriptions

    def _leads(self, total=90):
        markets = [StockMarkets.SAUDI] * 5 + [StockMarkets.AMERICAN] * 3 + [StockMarkets.EMIRATI, StockMarkets.OTHER]
        outcomes = [LeadStatuses.CONTACTED, LeadStatuses.NO_ANSWER, LeadStatuses.INTERESTED,
                    LeadStatuses.NOT_INTERESTED]
        calls = {LeadStatuses.CONTACTED: CallStatuses.CALLED, LeadStatuses.NO_ANSWER: CallStatuses.NO_ANSWER,
                 LeadStatuses.INTERESTED: CallStatuses.INTERESTED,
                 LeadStatuses.NOT_INTERESTED: CallStatuses.NOT_INTERESTED}
        self.leads = []
        for i in range(total):
            owner = self.marketing[i % len(self.marketing)]
            day = self._past_day(self.history_start)
            name = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
            lead = Lead.objects.create(
                user=owner, phone=f"0111{2000000 + i:07d}", name=name,
                email=f"lead{i}@example.com" if i % 3 else "",
                date=datetime.combine(day, time(self.rng.randint(9, 17), self.rng.randint(0, 59))),
                project=self.projects[i % 2], stock_market=self.rng.choice(markets),
                description="Interested in a trading package" if i % 4 == 0 else "")
            lead_service.log_update(lead, owner, LeadUpdateTypes.CREATED)
            self.leads.append(lead)
        self._count("leads", total)

        assigned = self.leads[: int(total * 0.75)]
        for i, lead in enumerate(assigned):
            agent = self.sales[i % len(self.sales)] if i % 5 else self.sales_lead
            lead_service.assign_leads(self.admin, [lead], agent, AssignmentKinds.SALES)
            self._count("lead assignments")
            status = outcomes[i % len(outcomes)]
            lead.status, lead.call_status = status, calls[status]
            lead.save(update_fields=["status", "call_status", "updated_at"])
            lead_service.log_update(lead, agent, LeadUpdateTypes.STATUS, LeadStatuses.ASSIGNED, status)
            lead_service.log_update(lead, agent, LeadUpdateTypes.CALL_STATUS, CallStatuses.PENDING,
                                    calls[status])
            if i % 6 == 0:
                lead_service.log_update(lead, agent, LeadUpdateTypes.NOTE, note="Asked to call back next week")
        # a returned lead, a hidden one, a callback request and screenshots
        returned = assigned[1]
        agent = returned.assignments.get(is_active=True).agent
        lead_service.return_lead(agent, returned, "Wrong number")
        self._count("lead returns")
        hidden = self.leads[-1]
        hidden.is_hidden = True
        hidden.save(update_fields=["is_hidden", "updated_at"])
        lead_service.log_update(hidden, self.users["seed_marketing_manager"], LeadUpdateTypes.HIDDEN)
        callback = assigned[2]
        callback.call_status = CallStatuses.CALLBACK_REQUESTED
        callback.save(update_fields=["call_status", "updated_at"])
        for lead in self.leads[3:6]:
            shot = LeadScreenshot(lead=lead)
            shot.image.save("screenshot.png", ContentFile(_png((200, 200, 200))), save=False)
            shot.save()
            self._count("lead screenshots")
        self.interested = [l for l in assigned if l.status == LeadStatuses.INTERESTED and l != returned]

    def _subscriptions(self):
        for i, lead in enumerate(self.interested[:14]):
            seller = lead.assignments.get(is_active=True, kind=AssignmentKinds.SALES).agent
            start = max(lead.date.date(), self._past_day(self.history_start))
            currency = {StockMarkets.AMERICAN: "USD", StockMarkets.EMIRATI: "AED"}.get(lead.stock_market, "SAR")
            total = Decimal(self.rng.choice([1500, 2500, 4000, 6000, 9000]))
            sub = subscription_service.create_subscription(self.admin, lead, {
                "kind": "renewal" if i % 5 == 4 else "new", "plan_name": self.rng.choice(
                    ["Basic", "Pro", "Premium"]) + " package", "market": lead.stock_market or StockMarkets.SAUDI,
                "currency": currency, "total_amount": str(total), "start_date": start,
                "end_date": start + timedelta(days=self.rng.choice([90, 180, 365])),
                "seller": str(seller.pk)})
            self._count("subscriptions")
            if i % 3 == 0:  # customer service follow-up
                lead_service.assign_leads(self.admin, [lead], self.sales[(i + 1) % len(self.sales)],
                                          AssignmentKinds.CS)
                self._count("lead assignments")
            if i == 13:
                subscription_service.cancel_subscription(self.admin, sub, "Customer requested a refund")
                continue
            parts = [total] if i % 2 else [total / 2, total / 4]  # fully paid / partially paid
            for n, amount in enumerate(parts):
                subscription_service.add_payment(self.admin, sub, {
                    "amount": str(amount.quantize(Decimal("0.01"))),
                    "paid_on": min(start + timedelta(days=n * 20), self.today),
                    "method": self.rng.choice(["bank_transfer", "cash", "card", "online"]),
                    "transaction_id": f"TX{i:03d}{n}", "note": "Seed payment"})
                self._count("payments")

    # ------------------------------------------------------------------ attendance

    def _attendance(self):
        departments = [self.departments[n] for n in ("Sales", "Marketing", "Technical", "Administration")]
        # a personal shift override (before evaluation, so its days use it) and a web punch policy
        night, _ = Shift.objects.get_or_create(
            name="Night", defaults=dict(start_time=time(22, 0), end_time=time(6, 0),
                                        weekend_days=seed_attendance_demo.WEEKEND, active=True))
        ShiftAssignment.objects.create(user=self.users["seed_tech_1"], shift=night,
                                       effective_from=self._bounds(self.periods[-2])[0])
        WebPunchPolicy.objects.get_or_create(
            department=self.departments["Sales"],
            defaults=dict(require_trusted_device=True, require_office_ip=True,
                          allowed_ips=["10.0.0.0/24", "192.168.11.0/24"]))
        call_command(_SeedAttendance(departments), days=(self.today - self.history_start).days,
                     force=True, stdout=io.StringIO())
        seeded = list(self.users.values())
        self._count("punches", Punch.objects.filter(user__in=seeded).count())
        self._count("attendance days", AttendanceDay.objects.filter(user__in=seeded).count())
        self._count("attendance requests", Request.objects.filter(user__in=seeded).count())

    # ------------------------------------------------------------------ treasury

    def _treasury(self):
        g1 = ledger.create_group(self.owner, "Capital operations", [self.projects[0].pk])
        g2 = ledger.create_group(self.owner, "Trade operations", [self.projects[1].pk])
        self._count("project groups", 2)
        entries = []
        for n in range(len(self.periods)):
            month = _months_back(self.today, n)
            month_end = min(self.today, _months_back(self.today, n - 1) - timedelta(days=1))
            entries.append(ledger.add_entry(self.owner, Direction.IN, Category.INCOME,
                                            str(150000 + n * 12500), month, "Monthly subscriptions income"))
            for details, amount, group, category in (
                    ("Office rent", "25000", None, Category.OPERATING),
                    ("Facebook ads", "18000", g1, Category.OPERATING),
                    ("Google ads", "9500", g2, Category.OPERATING),
                    ("Team dinner", "3200", None, Category.OTHER)):
                entries.append(ledger.add_entry(self.owner, Direction.OUT, category, amount,
                                                self._past_day(month, month_end), details, group))
        self._count("treasury entries", len(entries))
        ledger.reverse_entry(self.owner, entries[-1], "Recorded twice")
        self._count("treasury entries")
        batch_day = self._past_day(_months_back(self.today, 1), self.today)
        rows = [{"date": batch_day.isoformat(), "amount": a, "details": d, "category": "operating",
                 "group": g} for a, d, g in (("1200", "Printer ink", ""), ("4500", "Laptop repair", ""),
                                             ("7800", "Instagram ads", "Capital operations"))]
        importer.import_rows(self.owner, rows, None)
        self._count("import batches")
        self._count("treasury entries", len(rows))
        rows = [{"date": batch_day.isoformat(), "amount": "999", "details": "Wrong sheet", "category": "",
                 "group": ""}]
        wrong = importer.import_rows(self.owner, rows, g2)
        importer.reverse_batch(self.owner, wrong, "Imported the wrong file")
        self._count("import batches")

    def _advances(self):
        current = self.periods[-1]
        approved = advance_service.request_advance(self.sales[0], self.sales[0], "3000", 3, current,
                                                   "Family emergency")
        advance_service.approve_advance(self.users["seed_sales_manager"], approved, "Approved")
        advance_service.request_advance(self.marketing[1], self.marketing[1], "1500", 1,  # stays pending
                                        self._shift_key(current, 1), "Car repair")
        rejected = advance_service.request_advance(self.hr, self.sales[2], "6000", 6, current, "Rent")
        advance_service.reject_advance(self.users["seed_sales_manager"], rejected, "Amount too high")
        withdrawn = advance_service.request_advance(self.sales[3], self.sales[3], "1000", 2, current)
        advance_service.withdraw_advance(self.sales[3], withdrawn)
        cancelled = advance_service.request_advance(self.marketing[2], self.marketing[2], "2000", 2, current)
        advance_service.approve_advance(self.users["seed_marketing_manager"], cancelled)
        advance_service.cancel_advance(self.owner, cancelled, "Paid back in cash")
        self._count("advances", 5)

    # ------------------------------------------------------------------ monthly basics & salaries

    def _payroll(self):
        past = self.periods[:-1]  # ended periods only; the current one stays open
        for key in past:
            users = list(basic_service.included_users(key).order_by("username"))
            for i, user in enumerate(users):
                if user.username.startswith("seed_") and i % 3 == 0:
                    basic_service.update_inputs(self.admin, user, key, {
                        "kpi": "500", "kpi_note": "Hit the monthly target", "gift": "250" if i % 2 else "0",
                        "gift_note": "Eid gift" if i % 2 else "",
                        "days_adjustment": "-0.5", "days_adjustment_note": "Forgiven late day"})
                if key != past[-1] or i % 2 == 0:  # leave some drafts in the latest period
                    basic_service.give(self.admin, user, key)
                    self._count("monthly basics given")
                else:
                    self._count("monthly basics draft")
            for user in users:
                if key != past[-1]:
                    try:
                        salary_service.give(self.admin, user, key)
                        self._count("salaries given")
                    except salary_service.SalaryError as e:
                        self._count(f"salaries skipped ({e.type})")
        # an override on a draft salary in the latest ended period
        key = past[-1]
        for user in self.sales:
            parts = salary_service.compute(user, key)["parts"]
            if parts and basic_service.included_users(key).filter(pk=user.pk).exists():
                salary_service.set_override(self.admin, user, key, parts[0]["key"], "300",
                                            "Manual adjustment agreed with the manager")
                self._count("salary overrides")
                break
        try:
            basic_service.close_period(self.admin, past[0])
            self._count("closed periods")
        except basic_service.BasicError as e:
            self._count(f"period not closed ({e.message})")

    # ------------------------------------------------------------------ notifications & misc

    def _misc(self):
        everyone = list(self.users.values())
        n1 = notify(everyone, "Welcome to the new HR system!", title="Announcement", link="/",
                    sender=self.owner, audience={"everyone": True})
        notify([u for u in everyone if u.department == self.departments["Sales"]],
               "Monthly sales meeting on Sunday at 11:00.", title="Meeting", sender=self.users["seed_sales_manager"],
               audience={"departments": [str(self.departments["Sales"].pk)]},
               expires_at=timezone.now() + timedelta(days=7))
        old = notify([self.sales[0]], "Old notice that was retracted.", title="Retracted", sender=self.hr)
        old.retracted_at = timezone.now()
        old.save(update_fields=["retracted_at", "updated_at"])
        read = NotificationRecipient.objects.filter(notification=n1).order_by("user__username")[::2]
        for r in read:
            r.read_at = timezone.now()
            r.save(update_fields=["read_at", "updated_at"])
