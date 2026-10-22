from django.db.models import Exists, OuterRef, Q
from rest_framework.exceptions import PermissionDenied

from utils.working_days import return_days_left

from .lead_roles import AGENT, LEADER, OWNER, LeadRole, resolve_role
from .models import LeadAssignment
from .types import AssignmentKinds, DepartmentCodes

DENIED_MESSAGE = "You do not have access to leads"
_MARKETING = DepartmentCodes.MARKETING.value
_SALES = DepartmentCodes.SALES.value


def _active_assignments(lead):
    """Active assignments of a lead, reusing a prefetched `assignments` cache when present."""
    cache = getattr(lead, "_prefetched_objects_cache", {})
    if "assignments" in cache:
        return [a for a in lead.assignments.all() if a.is_active]
    return list(lead.assignments.filter(is_active=True))


def active_assignment(lead, kind: str):
    for assignment in _active_assignments(lead):
        if assignment.kind == kind:
            return assignment
    return None


def _creator_ids(user, role: LeadRole):
    return set(role.team_member_ids) | {user.uuid}


def scope_queryset(user, qs, *, hidden: bool = False):
    role = resolve_role(user)
    if hidden:
        if not role.is_admin:
            raise PermissionDenied(DENIED_MESSAGE)
        return qs.filter(is_hidden=True).distinct()

    qs = qs.filter(is_hidden=False)
    if role.is_admin:
        return qs.distinct()

    if role.department == _MARKETING:
        if role.level == LEADER:
            return qs.filter(user_id__in=_creator_ids(user, role)).distinct()
        return qs.filter(user=user).distinct()

    if role.department == _SALES:
        if role.level == LEADER:
            ids = _creator_ids(user, role)
            has_sales = LeadAssignment.objects.filter(
                lead=OuterRef("pk"), is_active=True, kind=AssignmentKinds.SALES.value
            )
            return qs.filter(
                Q(assignments__is_active=True, assignments__agent_id__in=ids)
                | ~Exists(has_sales)
            ).distinct()
        return qs.filter(assignments__is_active=True, assignments__agent=user).distinct()

    raise PermissionDenied(DENIED_MESSAGE)


def row_can(user, lead, role: LeadRole = None) -> dict:
    role = role or resolve_role(user)
    can = dict.fromkeys(
        ("edit", "status", "note", "assign", "return", "hide", "delete"), False
    )

    if role.is_admin:
        can.update(edit=True, status=True, note=True, assign=True, hide=True, delete=True)
        return can

    if role.department == _MARKETING:
        in_scope = (
            lead.user_id in _creator_ids(user, role)
            if role.level == LEADER
            else lead.user_id == user.uuid
        )
        can.update(edit=in_scope, note=in_scope)
        return can

    if role.department == _SALES:
        active = _active_assignments(lead)
        if role.level == LEADER:
            ids = _creator_ids(user, role)
            has_sales = any(a.kind == AssignmentKinds.SALES.value for a in active)
            in_scope = (not has_sales) or any(a.agent_id in ids for a in active)
            can.update(edit=in_scope, status=in_scope, note=in_scope, assign=True)
            return can
        assigned = any(a.agent_id == user.uuid for a in active)
        can.update(edit=assigned, status=assigned, note=assigned)
        sales = active_assignment(lead, AssignmentKinds.SALES.value)
        can["return"] = bool(
            sales
            and sales.agent_id == user.uuid
            and lead.return_count == 0
            and return_days_left(sales.created_at) > 0
        )
    return can


def capabilities(user) -> dict:
    role = resolve_role(user)
    return {
        "create": role.is_admin or (role.department == _MARKETING),
        "assign": role.is_admin or (role.department == _SALES and role.level == LEADER),
        "view_hidden": role.is_admin,
        "delete_by_phones": role.is_admin,
        "delete_by_phones_all_projects": role.level == OWNER,
        "upload": role.level == OWNER,
        "department": role.department,
        "level": role.level,
    }
