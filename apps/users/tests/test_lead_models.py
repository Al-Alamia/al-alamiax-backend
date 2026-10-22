from django.db import IntegrityError, transaction

from apps.users.models import LeadAssignment
from apps.users.tests.lead_fixtures import LeadPipelineTestCase


class LeadModelTests(LeadPipelineTestCase):
    def test_lead_defaults(self):
        lead = self.make_lead(self.mk_agent)
        self.assertEqual(lead.status, "new")
        self.assertEqual(lead.call_status, "pending")
        self.assertIs(lead.is_hidden, False)
        self.assertEqual(lead.return_count, 0)

    def test_one_active_assignment_per_kind(self):
        lead = self.make_lead(self.mk_agent)
        self.assign(lead, self.sales_agent, kind="sales")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.assign(lead, self.sales_agent2, kind="sales")
        self.assign(lead, self.sales_agent2, kind="cs")
        self.assertEqual(LeadAssignment.objects.filter(lead=lead, is_active=True).count(), 2)
