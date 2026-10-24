
from apps.attendance.permissions import can_correct, can_view, is_hr_plus, scoped_users
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


class ScopeTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        cls = self
        cls.d1 = Department.objects.create(name="D1")
        cls.d2 = Department.objects.create(name="D2")

        def mk(name, role, dept, **kw):
            return User.objects.create(username=name, role=role, department=dept, **kw)

        cls.agent = mk("a1", UserTypes.AGENT, cls.d1)
        cls.agent2 = mk("a2", UserTypes.AGENT, cls.d1)
        cls.other = mk("o1", UserTypes.AGENT, cls.d2)
        cls.manager = mk("m1", UserTypes.MANAGER, cls.d1)
        cls.hr = mk("h1", UserTypes.HR, cls.d2)
        cls.owner = mk("w1", UserTypes.OWNER, None)
        cls.root = mk("r1", UserTypes.AGENT, None, is_superuser=True)

    def test_hr_plus(self):
        self.assertTrue(all(is_hr_plus(u) for u in (self.hr, self.owner, self.root)))
        self.assertFalse(is_hr_plus(self.manager) or is_hr_plus(self.agent))

    def test_scoped_users(self):
        self.assertEqual(set(scoped_users(self.agent)), {self.agent})
        self.assertEqual(set(scoped_users(self.manager)), {self.agent, self.agent2, self.manager})
        self.assertEqual(set(scoped_users(self.hr)), set(User.objects.filter(is_active=True)))

    def test_can_view_and_correct(self):
        self.assertTrue(can_view(self.agent, self.agent))
        self.assertFalse(can_view(self.agent, self.agent2))
        self.assertTrue(can_view(self.manager, self.agent))
        self.assertFalse(can_view(self.manager, self.other))
        self.assertTrue(can_view(self.hr, self.other))
        self.assertFalse(can_correct(self.agent, self.agent))
        self.assertTrue(can_correct(self.manager, self.agent))
        self.assertFalse(can_correct(self.manager, self.other))
        self.assertTrue(can_correct(self.owner, self.other))

    def test_manager_without_department_sees_only_self(self):
        m = User.objects.create(username="m2", role=UserTypes.MANAGER, department=None)
        self.assertEqual(set(scoped_users(m)), {m})
        self.assertFalse(can_correct(m, self.agent))
