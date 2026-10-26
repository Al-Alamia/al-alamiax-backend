from apps.attendance.models import WebPunchPolicy
from apps.attendance.services import web_policy
from apps.users.tests.base import BaseUserTestCase
from apps.users.tests.user_admin_factories import make_device


class TrustedDeviceCheckTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        WebPunchPolicy.objects.create(department=self.department, require_trusted_device=True)
        self.agent.department = self.department
        self.agent.save()

    def test_only_approved_device_is_trusted(self):
        make_device(self.agent, "p", status="pending")
        make_device(self.agent, "r", status="rejected")
        make_device(self.agent, "a", status="approved")
        self.assertEqual(web_policy.check(self.agent, "p", "1.1.1.1"), "untrusted_device")
        self.assertEqual(web_policy.check(self.agent, "r", "1.1.1.1"), "untrusted_device")
        self.assertIsNone(web_policy.check(self.agent, "a", "1.1.1.1"))
