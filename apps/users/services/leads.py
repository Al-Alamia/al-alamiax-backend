from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q

from apps.activity.services.events import record_event
from apps.users.lead_roles import LEADER, resolve_role
from apps.users.lead_permissions import active_assignment
from apps.users.models import LeadAssignment, LeadReturn, LeadUpdate
from apps.users.types import AssignmentKinds, DepartmentCodes, LeadStatuses, LeadUpdateTypes
from utils.working_days import return_days_left


def apply_lead_filters(qs, params):
    """Pipeline list filters; ``params`` is any mapping (query params or a dict of the same keys)."""
    if params.get("search"):
        term = params["search"]
        qs = qs.filter(Q(name__icontains=term) | Q(phone__icontains=term))
    for field in ("status", "call_status", "stock_market"):
        if params.get(field):
            qs = qs.filter(**{field: params[field]})
    if params.get("project"):
        qs = qs.filter(project_id=params["project"])
    if params.get("created_by"):
        qs = qs.filter(user_id=params["created_by"])
    if params.get("assigned_to"):
        qs = qs.filter(
            Exists(
                LeadAssignment.objects.filter(
                    lead=OuterRef("pk"), is_active=True, agent_id=params["assigned_to"]
                )
            )
        )
    if params.get("unassigned") == "true":
        qs = qs.filter(
            ~Exists(
                LeadAssignment.objects.filter(
                    lead=OuterRef("pk"), is_active=True, kind=AssignmentKinds.SALES.value
                )
            )
        )
    if params.get("returned") == "true":
        qs = qs.filter(return_count__gt=0)
    if params.get("date_from"):
        qs = qs.filter(date__date__gte=params["date_from"])
    if params.get("date_to"):
        qs = qs.filter(date__date__lte=params["date_to"])
    return qs


class LeadRuleError(Exception):
    """A lead business rule was violated; surfaced as a 400 `{"message"}`."""


def log_update(lead, by, type: str, from_value: str = "", to_value: str = "", note: str = "") -> LeadUpdate:
    return LeadUpdate.objects.create(
        lead=lead, by=by, type=type, from_value=from_value, to_value=to_value, note=note
    )


def assign_leads(actor, leads: list, agent, kind: str) -> list:
    try:
        return _assign_leads(actor, leads, agent, kind)
    except IntegrityError:
        raise LeadRuleError("Lead was assigned concurrently, retry")


@transaction.atomic
def _assign_leads(actor, leads: list, agent, kind: str) -> list:
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
        record_event(actor, "lead.assigned", subject=agent, target=lead,
                     label=lead.name or lead.phone, data={"kind": kind})
    return assignments


@transaction.atomic
def return_lead(actor, lead, reason: str) -> LeadReturn:
    assignment = active_assignment(lead, AssignmentKinds.SALES.value)
    if assignment is None or assignment.agent_id != actor.uuid:
        raise LeadRuleError("Only the assigned sales agent can return this lead")
    if lead.return_count >= 1:
        raise LeadRuleError("Lead already returned once")
    if return_days_left(assignment.created_at) <= 0:
        raise LeadRuleError("Return window closed (5 working days)")
    reason = (reason or "").strip()
    if not reason:
        raise LeadRuleError("Reason is required")
    assignment.is_active = False
    assignment.save(update_fields=["is_active"])
    old_status = lead.status
    lead.status = LeadStatuses.NEW.value
    lead.return_count += 1
    lead.save(update_fields=["status", "return_count"])
    record = LeadReturn.objects.create(
        lead=lead, assignment=assignment, returned_by=actor, reason=reason
    )
    log_update(
        lead, actor, LeadUpdateTypes.RETURNED.value,
        from_value=old_status, to_value=lead.status, note=reason,
    )
    record_event(actor, "lead.returned", subject=actor, target=lead,
                 label=lead.name or lead.phone, data={"reason": reason})
    return record
