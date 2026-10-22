from django.db import transaction

from apps.users.lead_roles import LEADER, resolve_role
from apps.users.models import LeadAssignment, LeadUpdate
from apps.users.types import AssignmentKinds, DepartmentCodes, LeadStatuses, LeadUpdateTypes


class LeadRuleError(Exception):
    """A lead business rule was violated; surfaced as a 400 `{"message"}`."""


def log_update(lead, by, type: str, from_value: str = "", to_value: str = "", note: str = "") -> LeadUpdate:
    return LeadUpdate.objects.create(
        lead=lead, by=by, type=type, from_value=from_value, to_value=to_value, note=note
    )


@transaction.atomic
def assign_leads(actor, leads: list, agent, kind: str) -> list:
    if resolve_role(agent).department != DepartmentCodes.SALES.value:
        raise LeadRuleError("Agent is not in Sales")
    actor_role = resolve_role(actor)
    if actor_role.level == LEADER and agent != actor and agent.uuid not in actor_role.team_member_ids:
        raise LeadRuleError("Agent is not in your team")
    assignments = []
    for lead in leads:
        LeadAssignment.objects.filter(lead=lead, kind=kind, is_active=True).update(is_active=False)
        assignments.append(
            LeadAssignment.objects.create(
                lead=lead, agent=agent, kind=kind, assigned_by=actor, is_active=True
            )
        )
        if kind == AssignmentKinds.SALES.value and lead.status == LeadStatuses.NEW.value:
            lead.status = LeadStatuses.ASSIGNED.value
            lead.save(update_fields=["status"])
        log_update(lead, actor, LeadUpdateTypes.ASSIGNED.value, to_value=agent.username, note=kind)
    return assignments
