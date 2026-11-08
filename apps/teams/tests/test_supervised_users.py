from apps.teams.models import Team
from apps.teams.permissions import is_leader, supervised_users
from apps.users.models import Department, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes


class SupervisedUsersTests(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.other_dept = Department.objects.create(name="Other")
        self.hr = User.objects.create_user(username="hr", password="x", role=UserTypes.HR)
        self.manager = User.objects.create_user(
            username="mgr", password="x", role=UserTypes.MANAGER, department=self.department)
        self.far = User.objects.create_user(
            username="far", password="x", role=UserTypes.AGENT, department=self.other_dept)
        self.leader = User.objects.create_user(
            username="lead", password="x", role=UserTypes.AGENT, department=self.other_dept)
        self.a1 = User.objects.create_user(username="a1", password="x", department=self.other_dept)
        self.a2 = User.objects.create_user(username="a2", password="x", department=self.other_dept)

    def ids(self, viewer):
        return set(supervised_users(viewer).values_list("pk", flat=True))

    def test_hr_sees_all_active(self):
        gone = User.objects.create_user(username="gone", password="x", is_active=False)
        ids = self.ids(self.hr)
        self.assertEqual(ids, set(User.objects.filter(is_active=True).values_list("pk", flat=True)))
        self.assertNotIn(gone.pk, ids)
        self.assertEqual(self.ids(self.superuser), ids)

    def test_manager_sees_own_department(self):
        ids = self.ids(self.manager)
        self.assertEqual(ids, {self.superuser.pk, self.agent.pk, self.manager.pk})

    def test_manager_without_department_sees_self(self):
        m = User.objects.create_user(username="m2", password="x", role=UserTypes.MANAGER)
        self.assertEqual(self.ids(m), {m.pk})
        t = Team.objects.create(name="T", department=self.other_dept, leader=m)
        t.agents.add(self.a1)
        self.assertEqual(self.ids(m), {m.pk, self.a1.pk})

    def test_leader_sees_agents_of_active_teams(self):
        t = Team.objects.create(name="T", department=self.other_dept, leader=self.leader)
        t.agents.add(self.a1)
        dead = Team.objects.create(
            name="D", department=self.other_dept, leader=self.leader, is_active=False)
        dead.agents.add(self.a2)
        self.assertEqual(self.ids(self.leader), {self.leader.pk, self.a1.pk})
        self.assertTrue(is_leader(self.leader))

    def test_inactive_team_not_leader(self):
        Team.objects.create(name="D", department=self.other_dept, leader=self.leader, is_active=False)
        self.assertFalse(is_leader(self.leader))

    def test_agent_sees_self(self):
        self.assertEqual(self.ids(self.agent), {self.agent.pk})
        self.assertFalse(is_leader(self.agent))

    def test_leader_of_a_agent_in_b(self):
        a = Team.objects.create(name="A", department=self.other_dept, leader=self.leader)
        a.agents.add(self.a1)
        b = Team.objects.create(name="B", department=self.other_dept, leader=self.far)
        b.agents.add(self.leader, self.a2)
        self.assertEqual(self.ids(self.leader), {self.leader.pk, self.a1.pk})
