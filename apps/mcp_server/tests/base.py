from apps.activity.tests.helpers import ScopeFixtureMixin
from apps.users.models import User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


class McpTestCase(ScopeFixtureMixin, BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.make_scope_fixture()
        self.owner = User.objects.create_user(
            username="owner", password="x", email="owner@t.com", role=UserTypes.OWNER,
            project=self.project, department=self.department)
