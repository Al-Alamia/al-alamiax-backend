from datetime import timedelta
from itertools import count

from django.utils import timezone

from apps.teams.models import Team
from apps.users.models import Department, Lead, LeadAssignment, User
from apps.users.tests.base import BaseUserTestCase
from apps.users.types import UserTypes

_phone_counter = count(1)


class LeadPipelineTestCase(BaseUserTestCase):
    def setUp(self):
        super().setUp()
        self.marketing = Department.objects.create(name="Marketing", code="marketing")
        self.sales = Department.objects.create(name="Sales", code="sales")

        self.mk_agent = self._user("mk_agent", UserTypes.AGENT, self.marketing)
        self.mk_leader = self._user("mk_leader", UserTypes.AGENT, self.marketing)
        self.mk_team = Team.objects.create(name="Marketing Team", department=self.marketing, leader=self.mk_leader)
        self.mk_team.agents.set([self.mk_agent])

        self.sales_agent = self._user("sales_agent", UserTypes.AGENT, self.sales)
        self.sales_agent2 = self._user("sales_agent2", UserTypes.AGENT, self.sales)
        self.sales_leader = self._user("sales_leader", UserTypes.AGENT, self.sales)
        self.sales_team = Team.objects.create(name="Sales Team", department=self.sales, leader=self.sales_leader)
        self.sales_team.agents.set([self.sales_agent])

        self.manager = self._user("manager", UserTypes.MANAGER, self.sales)
        self.owner = self.superuser
        self.outsider = self.agent

    def _user(self, username, role, department):
        return User.objects.create_user(
            username=username,
            password="pass123",
            email=f"{username}@test.com",
            role=role,
            department=department,
            project=self.project,
        )

    def make_lead(self, creator, **fields):
        data = {
            "user": creator,
            "phone": f"010{next(_phone_counter):08d}",
            "name": "Test Lead",
            "project": self.project,
        }
        data.update(fields)
        return Lead.objects.create(**data)

    def assign(self, lead, agent, kind="sales", days_ago=0, by=None):
        assignment = LeadAssignment.objects.create(
            lead=lead, agent=agent, kind=kind, assigned_by=by, is_active=True
        )
        if days_ago:
            LeadAssignment.objects.filter(pk=assignment.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago)
            )
            assignment.refresh_from_db()
        return assignment
