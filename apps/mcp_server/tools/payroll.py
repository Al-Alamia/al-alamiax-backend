from itertools import islice

from apps.attendance.models import AttendanceSettings
from apps.attendance.services.periods import period_range
from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.common import is_payroll_viewer, limit_schema, list_result, visible_ref
from apps.monthly_basic import views as basic_views
from apps.monthly_basic.models import MonthlyBasic
from apps.monthly_basic.permissions import can_manage_basic, can_view_basic, list_scope
from apps.penalties.permissions import can_view, visible_penalties
from apps.penalties.serializers import penalty_data
from apps.salaries import views as salary_views
from apps.salaries.models import Salary
from apps.salaries.types import SalaryStatus
from apps.treasury import serializers as treasury_serializers
from apps.treasury.types import AdvanceStatus
from apps.treasury.views.advances import advances_queryset
from apps.users.admin_permissions import can_view_user
from apps.users.models import User

PERIOD = {"type": "string", "pattern": r"^\d{4}-\d{2}$", "description": "Payroll period YYYY-MM (default current)"}


def _vis_user(viewer, u):
    return u is not None and (u.pk == viewer.pk or can_view_user(viewer, u))


def _user_ref(viewer, u):
    return visible_ref(viewer, u, lambda x: {"uuid": str(x.uuid), "name": x.get_full_name() or x.username})


def _target(raw):
    return User.objects.select_related("department").filter(pk=raw).first()


@tool("get_salary", title="Salary of a user",
      description="Computed salary of a user for a payroll period (YYYY-MM, default current): basic net, "
                  "commission parts with overrides, totals, errors, and whether it was given.",
      schema={"type": "object", "required": ["user_uuid"], "properties": {
          "user_uuid": {"type": "string", "format": "uuid"}, "period": PERIOD}},
      visible=is_payroll_viewer)
def get_salary(user, args):
    target = _target(args["user_uuid"])
    key, start, end = salary_views.resolve_period(args.get("period"))
    given = target is not None and Salary.objects.filter(
        user=target, period=key, status=SalaryStatus.GIVEN).exists()
    if (target is None or not can_view_user(user, target)
            or not (can_manage_basic(user, target) or (user.pk == target.pk and given))):
        raise ToolError("User not found", "not_found")
    data = salary_views.detail_data(user, target, key, start, end)
    if data["given_by"] is not None:
        data["given_by"] = _user_ref(user, Salary.objects.select_related("given_by").get(
            user=target, period=key).given_by)
    for part in data["parts"]:
        o = part.get("override")
        if o and o.get("by") is not None:
            by = User.objects.filter(pk=o["by"]["uuid"]).first()
            part["override"] = {**o, "by": o["by"] if _vis_user(user, by) else None}
    return "Salary %s of %s: %s" % (key, target.username, data["total"]), data


@tool("list_salaries", title="Salaries of a period",
      description="Salary rows (basic net, commission, total, given or draft) of the users you may see for "
                  "a payroll period (YYYY-MM, default current), optionally for one department.",
      schema={"type": "object", "properties": {
          "period": PERIOD, "department": {"type": "string", "format": "uuid"}, "limit": limit_schema()}},
      visible=is_payroll_viewer)
def list_salaries(user, args):
    key, start, end = salary_views.resolve_period(args.get("period"))
    users, given_ids = salary_views.list_users(user, key, department_uuid=args.get("department"))
    if users is None:
        raise ToolError("You do not have permission to do that.", "forbidden")
    closed = salary_views.closed_period(start, end)
    overridden = set(Salary.objects.filter(period=key, overrides__isnull=False)
                     .values_list("user_id", flat=True))
    limit = args["limit"]
    visible = (u for u in users if can_view_user(user, u))

    def rows():
        for u in islice(visible, limit + 1):
            yield salary_views.list_row(user, u, key, u.pk in given_ids, overridden, closed)[0]

    res = list_result(rows(), lambda r: r, limit)
    res.update(period=key, start=start.isoformat(), end=end.isoformat())
    return "%d salaries for %s%s" % (res["count"], key, " (truncated)" if res["truncated"] else ""), res


@tool("get_monthly_basic", title="Monthly basic of a user",
      description="Monthly basic salary record of a user for a payroll period (YYYY-MM, default current): "
                  "inputs (kpi, gift, adjustments), breakdown, advance installments and status.",
      schema={"type": "object", "required": ["user_uuid"], "properties": {
          "user_uuid": {"type": "string", "format": "uuid"}, "period": PERIOD}},
      visible=is_payroll_viewer)
def get_monthly_basic(user, args):
    target = _target(args["user_uuid"])
    key, start, end = basic_views.resolve_period(args.get("period"))
    record = MonthlyBasic.objects.filter(user=target, period=key).first() if target else None
    if target is None or not can_view_user(user, target) or not can_view_basic(user, target, record):
        raise ToolError("User not found", "not_found")
    data = basic_views.detail_data(user, target, key, start, end)
    if record is not None and data["given_by"] is not None:
        data["given_by"] = _user_ref(user, record.given_by)
    return "Monthly basic %s of %s: %s" % (key, target.username, data["status"]), data


def _penalty_row(viewer, p):
    d = penalty_data(p, viewer)
    d["created_by"] = _user_ref(viewer, p.created_by)
    d["voided_by"] = _user_ref(viewer, p.voided_by)
    return d


@tool("list_penalties", title="Penalties",
      description="Penalties of the users you may see, newest first, optionally for one user and/or a "
                  "payroll period (YYYY-MM, by penalty date). Voided penalties are hidden unless "
                  "include_voided is true.",
      schema={"type": "object", "properties": {
          "user_uuid": {"type": "string", "format": "uuid"}, "period": PERIOD,
          "include_voided": {"type": "boolean", "default": False}, "limit": limit_schema()}},
      visible=is_payroll_viewer)
def list_penalties(user, args):
    qs = visible_penalties(user).select_related(
        "user", "user__department", "penalty_type", "created_by", "voided_by")
    if raw := args.get("user_uuid"):
        target = _target(raw)
        if target is None or not can_view_user(user, target) or not can_view(user, target):
            raise ToolError("User not found", "not_found")
        qs = qs.filter(user=target)
    if args.get("period"):
        try:
            start, end = period_range(args["period"], AttendanceSettings.get().period_start_day)
        except (ValueError, TypeError):
            raise ToolError("Invalid period.", "invalid_arguments")
        qs = qs.filter(date__range=(start, end))
    if not args.get("include_voided"):
        qs = qs.filter(voided_at__isnull=True)
    limit = args["limit"]
    rows = (p for p in qs if can_view_user(user, p.user) or p.user_id == user.pk)
    res = list_result(islice(rows, limit + 1), lambda p: _penalty_row(user, p), limit)
    return "%d penalties%s" % (res["count"], " (truncated)" if res["truncated"] else ""), res


def _advance_row(viewer, a):
    d = treasury_serializers.advance_data(a, viewer)
    d["requested_by"] = _user_ref(viewer, a.requested_by)
    d["decided_by"] = _user_ref(viewer, a.decided_by)
    return d


@tool("list_advances", title="Salary advances",
      description="Salary advances (amount, installments, schedule, status) of the users you may see, "
                  "newest first, optionally by status or user.",
      schema={"type": "object", "properties": {
          "status": {"type": "string", "enum": [s.value for s in AdvanceStatus]},
          "user_uuid": {"type": "string", "format": "uuid"}, "limit": limit_schema()}},
      visible=is_payroll_viewer)
def list_advances(user, args):
    scope = list_scope(user)
    if scope is None:
        raise ToolError("You cannot list advances.", "forbidden")
    qs = advances_queryset().filter(user__in=scope)
    if raw := args.get("user_uuid"):
        target = _target(raw)
        if target is None or not can_view_user(user, target) or not scope.filter(pk=target.pk).exists():
            raise ToolError("User not found", "not_found")
        qs = qs.filter(user=target)
    if args.get("status"):
        qs = qs.filter(status=args["status"])
    limit = args["limit"]
    rows = (a for a in qs if can_view_user(user, a.user))
    res = list_result(islice(rows, limit + 1), lambda a: _advance_row(user, a), limit)
    return "%d advances%s" % (res["count"], " (truncated)" if res["truncated"] else ""), res
