from django.db import IntegrityError, transaction

from apps.reports.models import ReportType
from apps.reports.tests.base import ReportsTestCase


class ReportTypeTests(ReportsTestCase):
    def test_name_unique_case_insensitive(self):
        ReportType.objects.create(name="Daily")
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReportType.objects.create(name="daily")
