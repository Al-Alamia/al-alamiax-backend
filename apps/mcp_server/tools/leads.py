import uuid as uuid_lib
from datetime import date
from decimal import Decimal

from rest_framework.exceptions import PermissionDenied

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_key_for
from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.common import limit_schema, list_result, user_brief
from apps.monthly_basic.services import BasicError, period_bounds
from apps.subscriptions import permissions as sub_perms
from apps.subscriptions.models import Subscription
from apps.subscriptions.reports import sales_totals as compute_sales_totals
from apps.subscriptions.serializers import money, user_ref
from apps.subscriptions.services import paid_amount
from apps.subscriptions.types import SubscriptionKind
from apps.users.admin_permissions import can_view_user
from apps.users.lead_permissions import active_assignment, scope_queryset
from apps.users.models import Lead
from apps.users.services.leads import apply_lead_filters
from apps.users.types import AssignmentKinds, LeadStatuses


ZERO = Decimal("0.00")


def _uuid(raw):
    try:
        return uuid_lib.UUID(str(raw))
    except ValueError:
        return None


def _agent_ref(assignment):
    """Same shape as the pipeline list serializer (uuid + username)."""
    if assignment is None:
        return None
    return {"uuid": str(assignment.agent.pk), "username": assignment.agent.username,
            "assigned_at": assignment.created_at}


def _lead_item(lead):
    return {
        "uuid": str(lead.pk),
        "name": lead.name,
        "phone": lead.phone,
        "status": lead.status,
        "project": {"uuid": str(lead.project_id), "name": lead.project.name} if lead.project_id else None,
        "sales_agent": _agent_ref(active_assignment(lead, AssignmentKinds.SALES.value)),
        "cs_agent": _agent_ref(active_assignment(lead, AssignmentKinds.CS.value)),
        "date": lead.date,
        "created_at": lead.created_at,
    }


@tool("search_leads", title="Search leads",
      description="Leads you can see in the lead pipeline (same scoping as the pipeline list). "
                  "Search by name or phone, filter by status, active assignee, project (name or "
                  "uuid) and lead date range.",
      schema={"type": "object", "properties": {
          "query": {"type": "string", "maxLength": 100,
                    "description": "Matches lead name or phone"},
          "status": {"type": "string", "enum": [s.value for s in LeadStatuses]},
          "assignee_uuid": {"type": "string", "format": "uuid"},
          "project": {"type": "string", "maxLength": 100, "description": "Project name or uuid"},
          "created_from": {"type": "string", "format": "date"},
          "created_to": {"type": "string", "format": "date"},
          "limit": limit_schema()}})
def search_leads(user, args):
    params = {"search": args.get("query", "").strip(), "status": args.get("status"),
              "assigned_to": args.get("assignee_uuid"),
              "date_from": args.get("created_from"), "date_to": args.get("created_to")}
    project = args.get("project", "").strip()
    project_name = ""
    if project:
        if _uuid(project):
            params["project"] = _uuid(project)
        else:
            project_name = project
    qs = scope_queryset(
        user, Lead.objects.select_related("user", "project").prefetch_related("assignments__agent"))
    qs = apply_lead_filters(qs, params)
    if project_name:
        qs = qs.filter(project__name__icontains=project_name)
    qs = qs.order_by("-date", "-created_at")[:args["limit"] + 1]
    result = list_result(qs, _lead_item, args["limit"])
    return "%d leads%s" % (result["count"], " (truncated)" if result["truncated"] else ""), result


def _agent_brief(viewer, agent):
    if agent is not None and can_view_user(viewer, agent):
        return user_brief(agent)
    return {"uuid": str(agent.pk), "username": agent.username} if agent else None


def _subscription_summary(sub):
    return {"uuid": str(sub.pk), "kind": sub.kind, "amount": money(sub.total_amount),
            "currency": sub.currency, "paid_amount": money(paid_amount(sub)),
            "status": sub.status()}


def _lead_subscriptions(user, lead):
    """Subscriptions of the lead the viewer may see, or None when the viewer may not see them."""
    if not sub_perms.has_access(user) or not sub_perms.lead_can(user, lead)["view"]:
        return None
    try:
        subs = sub_perms.scope_subscriptions(user, Subscription.objects.filter(lead=lead))
    except PermissionDenied:
        return None
    return [_subscription_summary(s) for s in subs.order_by("-start_date", "-created_at")]


@tool("get_lead", title="Get lead",
      description="One lead you can see: details, assignments, recent status history (last 20) "
                  "and, when you may see them, its subscriptions.",
      schema={"type": "object", "required": ["lead_uuid"], "properties": {
          "lead_uuid": {"type": "string", "format": "uuid"}}})
def get_lead(user, args):
    lead = (scope_queryset(user, Lead.objects.select_related("user", "project")
                           .prefetch_related("assignments__agent", "assignments__assigned_by"))
            .filter(uuid=args["lead_uuid"]).first())
    if lead is None:
        raise ToolError("Lead not found", "not_found")
    data = _lead_item(lead)
    data["description"] = lead.description
    data["call_status"] = lead.call_status
    data["return_count"] = lead.return_count
    data["created_by"] = _agent_brief(user, lead.user) if lead.user_id else None
    data["assignments"] = [
        {"kind": a.kind, "agent": _agent_brief(user, a.agent), "active": a.is_active,
         "assigned_at": a.created_at}
        for a in lead.assignments.all()]
    data["history"] = [
        {"type": u.type, "from": u.from_value, "to": u.to_value, "note": u.note,
         "by": {"uuid": str(u.by.pk), "username": u.by.username} if u.by else None,
         "created_at": u.created_at}
        for u in lead.updates.select_related("by").order_by("-created_at")[:20]]
    subs = _lead_subscriptions(user, lead)
    if subs is not None:
        data["subscriptions"] = subs
    return "Lead %s (%s)" % (lead.name, lead.status), data


def _subscription_item(sub):
    paid = sum((p.amount for p in sub.payments.all()), ZERO)
    return {
        "uuid": str(sub.pk),
        "lead": {"uuid": str(sub.lead.pk), "name": sub.lead.name, "phone": sub.lead.phone},
        "kind": sub.kind, "plan_name": sub.plan_name, "market": sub.market,
        "currency": sub.currency, "total_amount": money(sub.total_amount),
        "paid_amount": money(paid), "remaining_amount": money(sub.total_amount - paid),
        "status": sub.status(),
        "start_date": sub.start_date.isoformat(), "end_date": sub.end_date.isoformat(),
        "seller": user_ref(sub.seller),
        "cancelled_at": sub.cancelled_at.isoformat() if sub.cancelled_at else None,
    }


@tool("list_subscriptions", title="List subscriptions",
      description="Subscriptions you can see (same scoping as the subscriptions list), optionally "
                  "filtered by lead, seller, kind and start-date range.",
      schema={"type": "object", "properties": {
          "lead_uuid": {"type": "string", "format": "uuid"},
          "seller_uuid": {"type": "string", "format": "uuid"},
          "kind": {"type": "string", "enum": [k.value for k in SubscriptionKind]},
          "from": {"type": "string", "format": "date"},
          "to": {"type": "string", "format": "date"},
          "limit": limit_schema()}})
def list_subscriptions(user, args):
    try:
        qs = sub_perms.scope_subscriptions(user, Subscription.objects.all())
    except PermissionDenied as e:
        raise ToolError(str(e.detail), "forbidden")
    if not sub_perms.has_access(user):
        raise ToolError(sub_perms.DENIED_MESSAGE, "forbidden")
    start, end = args.get("from"), args.get("to")
    if start and end and start > end:
        raise ToolError("from must not be after to", "invalid_arguments")
    if start:
        qs = qs.filter(start_date__gte=start)
    if end:
        qs = qs.filter(start_date__lte=end)
    if args.get("seller_uuid"):
        qs = qs.filter(seller_id=args["seller_uuid"])
    if args.get("lead_uuid"):
        qs = qs.filter(lead_id=args["lead_uuid"])
    if args.get("kind"):
        qs = qs.filter(kind=args["kind"])
    qs = (qs.select_related("lead", "seller").prefetch_related("payments")
          .order_by("-start_date", "-created_at", "uuid")[:args["limit"] + 1])
    result = list_result(qs, _subscription_item, args["limit"])
    return ("%d subscriptions%s" % (result["count"], " (truncated)" if result["truncated"] else "")), result


def _bucket(b):
    return {"deal_count": b["deal_count"], "sales_amount": money(b["sales_amount"]),
            "american_deal_count": b["american_deal_count"],
            "american_sales_amount": money(b["american_sales_amount"])}


@tool("sales_totals", title="Sales totals",
      description="Your own sales totals (deal count and collected amount in SAR, total and by "
                  "new/renewal) for a payroll period.",
      schema={"type": "object", "properties": {
          "period": {"type": "string", "pattern": r"^\d{4}-\d{2}$",
                     "description": "YYYY-MM payroll period, defaults to the current one"}}})
def sales_totals(user, args):
    key = args.get("period") or period_key_for(date.today(), AttendanceSettings.get().period_start_day)
    try:
        start, end = period_bounds(key)
    except BasicError:
        raise ToolError("Invalid period", "invalid_arguments")
    raw = compute_sales_totals(user, start, end)
    data = _bucket(raw)
    data["by_kind"] = {str(k): _bucket(v) for k, v in raw["by_kind"].items()}
    data["period"] = {"key": key, "start": str(start), "end": str(end)}
    return "%d deals in %s" % (data["deal_count"], key), data
