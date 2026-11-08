import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.reports.errors import ReportError
from apps.reports.models import ReportSubmission, ReportType
from apps.reports.services.audience import required_users
from apps.reports.services.definition import save_definition
from apps.reports.services.periods import period_for
from apps.reports.services.submissions import save_submission
from apps.users.models import Department, Project

TYPE_NAME = "Social media daily"
DEFAULT_COLOR = "#64748b"
PALETTE = ["#0ea5e9", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#14b8a6", "#ec4899", "#84cc16"]
DAYS = 10
MISSING_CHANCE = 0.1
LATE_CHANCE = 0.05
SEED = 20261108

# section -> [(label, kind, required)]
SECTIONS = [
    ("Twitter/X", [("Accounts", "accounts", True), ("Tweets", "number", True), ("Messages", "number", False),
                   ("Replies", "number", False), ("Follows", "number", False)]),
    ("TikTok", [("Accounts", "accounts", True), ("Follows", "number", False),
                ("Messages", "number", False), ("Posts", "number", False)]),
    ("WhatsApp", [("Accounts", "accounts", True), ("Messages", "number", False)]),
    ("Telegram", [("Accounts", "accounts", True), ("Messages", "number", False)]),
    ("Jaco", [("Accounts", "accounts", False), ("Messages", "number", False), ("Follows", "number", False)]),
]


def _definition():
    return [{"name": s, "fields": [{"label": l, "kind": k, "required": r} for l, k, r in fields]}
            for s, fields in SECTIONS]


class Command(BaseCommand):
    help = "Seed the 'Social media daily' report type with demo submissions (idempotent)"

    @transaction.atomic
    def handle(self, *args, **options):
        rt, created = ReportType.objects.get_or_create(
            name=TYPE_NAME, defaults={"description": "Daily social media activity per account."})
        if created:
            rt.departments.set(Department.objects.filter(code="marketing"))
            save_definition(rt, _definition())
        fields = {(f.section.name, f.label): f for f in
                  rt.sections.prefetch_related("fields").all() for f in f.fields.all()}

        rng = random.Random(SEED)
        today = date.today()
        users = list(required_users(rt).order_by("username"))
        made = 0
        for user in users:
            for offset in range(DAYS - 1, -1, -1):
                day = today - timedelta(days=offset)
                # draw every time so the sequence stays stable across runs
                skip, late = rng.random() < MISSING_CHANCE, rng.random() < LATE_CHANCE
                values = {}
                for (section, label), field in fields.items():
                    if field.kind == "accounts":
                        values[str(field.uuid)] = [f"{user.username}_{section.lower().replace('/', '')}_{i}"
                                                   for i in range(1, rng.randint(1, 3) + 1)]
                    elif field.kind == "number":
                        values[str(field.uuid)] = (rng.randint(0, 40) if field.required or rng.random() < 0.85 else None)
                start, _ = period_for(rt, day)
                if skip or ReportSubmission.objects.filter(
                        report_type=rt, user=user, period_start=start).exists():
                    continue
                try:
                    sub = save_submission(rt, user, day, values, day)
                except ReportError:
                    continue  # locked / not required that day
                if late:
                    sub.is_late = True
                    sub.save(update_fields=["is_late", "updated_at"])
                made += 1
        # guarantee a couple of late rows exist
        if created and not ReportSubmission.objects.filter(report_type=rt, is_late=True).exists():
            ReportSubmission.objects.filter(report_type=rt).order_by("period_start")[:2].update(is_late=True)

        recolored = 0
        for i, project in enumerate(Project.objects.filter(color=DEFAULT_COLOR).order_by("name", "uuid")):
            project.color = PALETTE[i % len(PALETTE)]
            project.save(update_fields=["color", "updated_at"])
            recolored += 1
        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Found'} '{TYPE_NAME}'; {made} submissions; {recolored} project colours"))
