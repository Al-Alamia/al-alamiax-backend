from apps.teams.models import Team
from apps.users.models import Department, User
from apps.users.types import UserTypes


class ScopeFixtureMixin:
    """Creates other_agent, manager, hr, leader (team leader of self.agent)."""

    def make_scope_fixture(self):
        other = Department.objects.create(name="Other")
        mk = lambda name, role, dept: User.objects.create_user(
            username=name, password="x", email=f"{name}@t.com", role=role,
            project=self.project, department=dept)
        self.other_agent = mk("other_agent", UserTypes.AGENT, other)
        self.manager = mk("manager", UserTypes.MANAGER, self.department)
        self.hr = mk("hr", UserTypes.HR, other)
        self.leader = mk("leader", UserTypes.AGENT, other)
        team = Team.objects.create(name="T", department=self.department, leader=self.leader)
        team.agents.add(self.agent)
