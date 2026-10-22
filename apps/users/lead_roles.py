from dataclasses import dataclass

from .types import DepartmentCodes, UserTypes

OWNER = "owner"
MANAGER = "manager"
LEADER = "leader"
AGENT = "agent"


@dataclass(frozen=True)
class LeadRole:
    department: str
    level: str
    team_member_ids: frozenset  # uuids of agents in teams the user leads

    @property
    def is_admin(self) -> bool:
        return self.level in (OWNER, MANAGER)


def resolve_role(user) -> LeadRole:
    # Imported lazily: apps.commission.models imports from apps.users
    from apps.commission.models import Team

    department = user.department.code if user.department else DepartmentCodes.OTHER.value

    team_member_ids = frozenset()
    if user.is_superuser or user.role == UserTypes.OWNER:
        level = OWNER
    elif user.role == UserTypes.MANAGER:
        level = MANAGER
    else:
        teams = Team.objects.filter(leader=user)
        if teams.exists():
            level = LEADER
            team_member_ids = frozenset(
                teams.exclude(agents=None).values_list("agents__uuid", flat=True)
            )
        else:
            level = AGENT
    return LeadRole(department=department, level=level, team_member_ids=team_member_ids)
