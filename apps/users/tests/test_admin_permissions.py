from apps.users import admin_permissions as p
from apps.users.models import Department
from apps.users.types import UserTypes
from apps.users.tests.base import BaseUserTestCase
from apps.users.tests.user_admin_factories import make_user


class AdminPermissionsTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        da = Department.objects.create(name="Dept A")
        db = Department.objects.create(name="Dept B")
        self.owner = make_user("t_owner", UserTypes.OWNER)
        self.owner2 = make_user("t_owner2", UserTypes.OWNER)
        self.hr = make_user("t_hr", UserTypes.HR)
        self.mgr_a = make_user("t_mgr_a", UserTypes.MANAGER, da)
        self.mgr_b = make_user("t_mgr_b", UserTypes.MANAGER, db)
        self.a1 = make_user("t_a1", department=da)
        self.a2 = make_user("t_a2", department=da)
        self.b1 = make_user("t_b1", department=db)
        self.su = make_user("t_su", UserTypes.AGENT, is_superuser=True, is_staff=True)

    def names(self, qs):
        return set(qs.values_list("username", flat=True))

    def test_visible_users(self):
        hr = self.names(p.visible_users(self.hr))
        self.assertNotIn("t_su", hr)
        self.assertNotIn("t_owner", hr)
        self.assertIn("t_a1", hr)
        ow = self.names(p.visible_users(self.owner))
        self.assertIn("t_owner2", ow)
        self.assertNotIn("t_su", ow)
        self.assertIn("t_su", self.names(p.visible_users(self.su)))
        self.assertEqual(self.names(p.visible_users(self.mgr_a)), {"t_mgr_a", "t_a1", "t_a2"})
        self.assertEqual(p.visible_users(self.a1).count(), 0)

    def test_can_view_user(self):
        self.assertTrue(p.can_view_user(self.a1, self.a1))
        self.assertFalse(p.can_view_user(self.a1, self.a2))
        self.assertTrue(p.can_view_user(self.mgr_a, self.a1))
        self.assertFalse(p.can_view_user(self.mgr_a, self.b1))
        self.assertFalse(p.can_view_user(self.hr, self.owner))
        self.assertFalse(p.can_view_user(self.owner, self.su))

    def test_assignable_roles(self):
        A, M, H, O = UserTypes.AGENT, UserTypes.MANAGER, UserTypes.HR, UserTypes.OWNER
        self.assertEqual(p.assignable_roles(self.hr), [A, M, H])
        self.assertEqual(p.assignable_roles(self.owner), [A, M, H, O])
        self.assertEqual(p.assignable_roles(self.a1), [])
        self.assertEqual(p.assignable_roles(self.mgr_a), [])

    def test_can_manage_user(self):
        self.assertFalse(p.can_manage_user(self.hr, self.owner))
        self.assertTrue(p.can_manage_user(self.owner, self.owner2))
        self.assertFalse(p.can_manage_user(self.mgr_a, self.a1))
        self.assertTrue(p.can_manage_user(self.hr, self.a1))

    def test_devices(self):
        self.assertTrue(p.can_manage_devices(self.mgr_a, self.a1))
        self.assertFalse(p.can_manage_devices(self.mgr_a, self.b1))
        self.assertFalse(p.can_manage_devices(self.mgr_a, self.mgr_a))
        self.a1.is_active = False
        self.assertFalse(p.can_manage_devices(self.mgr_a, self.a1))
        self.assertFalse(p.can_manage_devices(self.hr, self.owner))
        self.assertTrue(p.can_manage_devices(self.owner, self.owner))
        self.assertTrue(p.can_view_devices(self.a1, self.a1))
        self.assertFalse(p.can_view_devices(self.a1, self.a2))

    def test_files(self):
        self.assertTrue(p.can_view_files(self.mgr_a, self.a1))
        self.assertFalse(p.can_manage_files(self.mgr_a, self.a1))
        self.assertTrue(p.can_view_files(self.a1, self.a1))
        self.assertFalse(p.can_view_files(self.a1, self.a2))
        self.assertTrue(p.can_manage_files(self.hr, self.a1))

    def test_history(self):
        self.assertTrue(p.can_view_history(self.hr, self.a1))
        self.assertFalse(p.can_view_history(self.mgr_a, self.a1))
        self.assertFalse(p.can_view_history(self.hr, self.owner))

    def test_device_approvers(self):
        got = p.device_approvers(self.a1)
        self.assertIn(self.hr, got)
        self.assertIn(self.owner, got)
        self.assertIn(self.mgr_a, got)
        self.assertNotIn(self.mgr_b, got)
        self.assertNotIn(self.a1, got)
        self.assertLessEqual(len(got), 20)
        ids = [u.pk for u in got]
        self.assertGreater(ids.index(self.mgr_a.pk), ids.index(self.hr.pk))

    def test_device_approvers_capped(self):
        for i in range(25):
            make_user(f"t_hr_extra{i:02d}", UserTypes.HR)
        self.assertEqual(len(p.device_approvers(self.a1)), 20)
