from apps.mcp_server.eligibility import is_eligible
from apps.mcp_server.tests.base import McpTestCase


class EligibilityTests(McpTestCase):
    def test_roles(self):
        self.assertFalse(is_eligible(self.agent))
        for u in (self.manager, self.hr, self.owner, self.superuser):
            self.assertTrue(is_eligible(u))

    def test_must_change_password(self):
        self.manager.must_change_password = True
        self.assertFalse(is_eligible(self.manager))

    def test_inactive(self):
        self.manager.is_active = False
        self.assertFalse(is_eligible(self.manager))
