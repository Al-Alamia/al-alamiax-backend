import importlib

from apps.users.lead_roles import resolve_role
from apps.users.tests.lead_fixtures import LeadPipelineTestCase

guess_department_code = importlib.import_module(
    "apps.users.migrations.0042_department_code"
).guess_department_code


class ResolveRoleTests(LeadPipelineTestCase):
    def test_owner_superuser(self):
        self.assertEqual(resolve_role(self.owner).level, "owner")

    def test_manager(self):
        r = resolve_role(self.manager)
        self.assertEqual((r.level, r.department), ("manager", "sales"))
        self.assertTrue(r.is_admin)

    def test_leader_from_team(self):
        r = resolve_role(self.sales_leader)
        self.assertEqual(r.level, "leader")
        self.assertIn(self.sales_agent.uuid, r.team_member_ids)

    def test_agent(self):
        r = resolve_role(self.mk_agent)
        self.assertEqual((r.level, r.department), ("agent", "marketing"))
        self.assertFalse(r.is_admin)

    def test_outsider_is_other(self):
        self.assertEqual(resolve_role(self.outsider).department, "other")

    def test_no_department_is_other(self):
        self.mk_agent.department = None
        self.assertEqual(resolve_role(self.mk_agent).department, "other")

    def test_guess_department_code(self):
        names = ["Marketing", "قسم التسويق", "Sales Team", "مبيعات", "Technical", "HR"]
        self.assertEqual(
            [guess_department_code(n) for n in names],
            ["marketing", "marketing", "sales", "sales", "technical", "other"],
        )
