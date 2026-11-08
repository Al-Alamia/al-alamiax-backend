from django.core.management import call_command

from apps.reports.models import ReportField, ReportSection, ReportSubmission, ReportType, ReportValue
from apps.users.models import User
from apps.users.types import UserTypes

from .base import ReportsTestCase

EXPECTED = {
    "Twitter/X": [("accounts", "accounts", True), ("tweets", "number", True), ("messages", "number", False),
                  ("replies", "number", False), ("follows", "number", False)],
    "TikTok": [("accounts", "accounts", True), ("follows", "number", False),
               ("messages", "number", False), ("posts", "number", False)],
    "WhatsApp": [("accounts", "accounts", True), ("messages", "number", False)],
    "Telegram": [("accounts", "accounts", True), ("messages", "number", False)],
    "Jaco": [("accounts", "accounts", False), ("messages", "number", False), ("follows", "number", False)],
}


class SeedReportsDemoTests(ReportsTestCase):
    def setUp(self):
        super().setUp()
        for i in range(3):
            User.objects.create_user(
                username=f"mkt{i}", password="pass123", email=f"mkt{i}@test.com",
                role=UserTypes.AGENT, project=self.project, department=self.marketing)

    def counts(self):
        return (ReportType.objects.count(), ReportSection.objects.count(), ReportField.objects.count(),
                ReportSubmission.objects.count(), ReportValue.objects.count())

    def test_seed_and_idempotent(self):
        call_command("seed_reports_demo", verbosity=0)
        rt = ReportType.objects.get(name="Social media daily")
        self.assertEqual(ReportType.objects.filter(name="Social media daily").count(), 1)
        self.assertEqual(rt.frequency, "daily")
        self.assertEqual(list(rt.departments.all()), [self.marketing])
        sections = list(rt.sections.order_by("order"))
        self.assertEqual([s.name for s in sections], list(EXPECTED))
        for s in sections:
            got = [(f.label.lower(), f.kind, f.required) for f in s.fields.order_by("order")]
            self.assertEqual(got, [(l.lower(), k, r) for l, k, r in EXPECTED[s.name]])
        self.assertTrue(ReportSubmission.objects.filter(report_type=rt).exists())
        self.assertTrue(ReportSubmission.objects.filter(is_late=True).exists())
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.color, "#64748b")

        before = self.counts()
        call_command("seed_reports_demo", verbosity=0)
        self.assertEqual(self.counts(), before)
