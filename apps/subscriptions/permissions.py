from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from apps.attendance.services.locks import is_date_closed
from apps.users.lead_permissions import scope_queryset
from apps.users.lead_roles import LEADER, MANAGER, OWNER, resolve_role
from apps.users.models import Lead, LeadAssignment, User
from apps.users.types import AssignmentKinds, DepartmentCodes

DENIED_MESSAGE = "You do not have access to subscriptions"
_SALES = DepartmentCodes.SALES.value


def _is_owner(role) -> bool:
    return role.level == OWNER


def _is_sales_manager(role) -> bool:
    return role.level == MANAGER and role.department == _SALES


def _is_sales_leader(role) -> bool:
    return role.level == LEADER and role.department == _SALES


def _sees_all(role) -> bool:
    return _is_owner(role) or _is_sales_manager(role)


def has_access(user) -> bool:
    role = resolve_role(user)
    return _is_owner(role) or role.department == _SALES


def _lead_in_scope(user, lead) -> bool:
    return scope_queryset(user, Lead.objects.filter(pk=lead.pk)).exists()


def scope_subscriptions(user, qs):
    role = resolve_role(user)
    if _sees_all(role):
        return qs
    if role.department != _SALES or role.level == MANAGER:
        raise PermissionDenied(DENIED_MESSAGE)
    seller_ids = {user.pk} | (set(role.team_member_ids) if role.level == LEADER else set())
    # Seller match is not filtered by hidden leads; the lead-scope part excludes them.
    lead_scope = scope_queryset(user, Lead.objects.all()).values("pk")
    return qs.filter(Q(lead_id__in=lead_scope) | Q(seller_id__in=seller_ids))


def lead_can(user, lead) -> dict:
    none = {"view": False, "create": False, "choose_seller": False}
    if not has_access(user):
        return none
    role = resolve_role(user)
    if _sees_all(role):
        return {"view": True, "create": not lead.is_hidden, "choose_seller": True}
    in_scope = _lead_in_scope(user, lead)
    if _is_sales_leader(role):
        return {"view": in_scope, "create": in_scope and not lead.is_hidden, "choose_seller": in_scope}
    if role.department != _SALES or role.level == MANAGER:
        return none
    active = LeadAssignment.objects.filter(
        lead=lead, agent=user, is_active=True,
        kind__in=(AssignmentKinds.SALES.value, AssignmentKinds.CS.value),
    ).exists()
    return {"view": in_scope, "create": active and not lead.is_hidden, "choose_seller": False}


def can_manage(user, sub) -> bool:
    role = resolve_role(user)
    if _sees_all(role):
        return True
    if _is_sales_leader(role):
        return sub.seller_id in (set(role.team_member_ids) | {user.pk}) or _lead_in_scope(user, sub.lead)
    return False


def row_can(user, sub) -> dict:
    cancelled = sub.cancelled_at is not None
    manage = can_manage(user, sub)
    return {
        "edit": manage and not cancelled,
        "cancel": manage and not cancelled,
        "delete": manage and not sub.payments.exists(),
        "add_payment": (lead_can(user, sub.lead)["create"] or sub.seller_id == user.pk) and not cancelled,
    }


def payment_can(user, payment) -> bool:
    allowed = payment.recorded_by_id == user.pk or can_manage(user, payment.subscription)
    ok = allowed and not is_date_closed(payment.paid_on)
    return {"edit": ok, "delete": ok}


def seller_choices(lead):
    return User.objects.filter(lead_assignments__lead=lead).distinct().order_by("username")
