from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.permissions import can_edit_basic, can_manage_basic, can_view_basic, list_scope
from apps.monthly_basic.types import BasicStatus
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


class PermissionTests(BaseUserTestCase):
    def mk(self, name, role, dept=None):
        return User.objects.create_user(username=name, password="x", role=role, department=dept or self.department)

    def test_matrix(self):
        hr = self.mk("hr", UserTypes.HR)
        owner = self.mk("owner", UserTypes.OWNER)
        owner2 = self.mk("owner2", UserTypes.OWNER)
        other = Department.objects.create(name="Other")
        mgr = self.mk("mgr", UserTypes.MANAGER)
        mgr_owner = self.mk("mo", UserTypes.OWNER)
        other_agent = self.mk("oa", UserTypes.AGENT, other)
        a = self.agent

        self.assertTrue(can_manage_basic(hr, a) and can_edit_basic(hr, a))
        self.assertFalse(can_manage_basic(hr, owner))
        self.assertFalse(can_manage_basic(hr, self.superuser))
        self.assertTrue(can_manage_basic(owner, owner2))
        self.assertTrue(can_manage_basic(mgr, a))
        self.assertFalse(can_manage_basic(mgr, other_agent))
        self.assertFalse(can_manage_basic(mgr, mgr_owner))
        self.assertTrue(can_manage_basic(hr, hr))
        self.assertFalse(can_edit_basic(hr, hr))
        self.assertTrue(can_edit_basic(owner, owner))
        self.assertFalse(can_manage_basic(a, a))

        given = MonthlyBasic(user=a, period="2026-10", status=BasicStatus.GIVEN)
        draft = MonthlyBasic(user=a, period="2026-10", status=BasicStatus.DRAFT)
        self.assertTrue(can_view_basic(a, a, given))
        self.assertFalse(can_view_basic(a, a, draft))
        self.assertFalse(can_view_basic(a, a, None))
        self.assertTrue(can_view_basic(mgr, a, draft))

        self.assertIsNone(list_scope(a))
        self.assertEqual(set(list_scope(mgr)), set(User.objects.filter(department=self.department, is_active=True, is_superuser=False)
                                        .exclude(role=UserTypes.OWNER)))
        self.assertIn(other_agent, list_scope(hr))
        self.assertNotIn(owner, list_scope(hr))
