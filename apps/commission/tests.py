from django.apps import apps

from apps.treasury.models import TreasuryOutcome
from apps.users.tests.base import BaseUserTestCase


class LegacyRemovedTests(BaseUserTestCase):
    def test_commission_salary_endpoint_gone(self):
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.get("/api/commission/salary").status_code, 404)

    def test_user_leads_endpoint_gone(self):
        self.authenticate_as(self.superuser)
        self.assertEqual(self.client.post("/api/users/user-leads").status_code, 404)

    def test_models_gone(self):
        with self.assertRaises(LookupError):
            apps.get_model("commission", "Commission")
        self.assertNotIn("from_salary", [f.name for f in TreasuryOutcome._meta.get_fields()])
