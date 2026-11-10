import uuid as uuid_lib
from datetime import date

from django.db.models import Q

from apps.attendance.models import AttendanceDay, AttendanceSettings
from apps.attendance.permissions import can_decide, can_view, is_hr_plus, scoped_users
from apps.attendance.serializers import balance_data
from apps.attendance.services import leave as leave_svc
from apps.attendance.services import requests as request_svc
from apps.attendance.services.day_summary import day_summary
from apps.attendance.services.periods import period_key_for, period_range
from apps.attendance.types import DayStatus, RequestKind, RequestStatus
from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.common import is_payroll_viewer, limit_schema, list_result, user_brief
from apps.users.admin_permissions import can_view_user
from apps.users.models import Department, User
from apps.users.types import UserTypes

SCOPES = ("approvals", "mine", "all")


def _uuid(raw):
    try:
        return uuid_lib.UUID(str(raw))
    except ValueError:
        return None


def _can_see(viewer, target) -> bool:
    return can_view(viewer, target) and can_view_user(viewer, target)


def _target(viewer, raw):
    """The ``user_uuid`` arg (default: the viewer); not visible == not found."""
    if raw is None:
        return viewer
    target = User.objects.select_related("department").filter(pk=raw).first()
    if target is None or not _can_see(viewer, target):
        raise ToolError("User not found", "not_found")
    return target


def visible_request(user, request_uuid):
    """The attendance request ``request_uuid`` if ``user`` may see it (same rule as the REST detail,
    plus ``can_view_user`` so HR never sees OWNER/superuser data); else ToolError not_found."""
    req = request_svc.get_visible_request(user, request_uuid)
    if req is None or not can_view_user(user, req.user):
        raise ToolError("Request not found", "not_found")
    return req


def _time(dt):
    return dt.isoformat() if dt else None


_OFF = (DayStatus.WEEKEND, DayStatus.HOLIDAY, DayStatus.NO_SHIFT)
_GROUPS = {DayStatus.PRESENT: "present", DayStatus.LATE: "late", DayStatus.ABSENT: "absent",
           DayStatus.LEAVE: "on_leave", DayStatus.INCOMPLETE: "incomplete", DayStatus.EXCUSED: "excused"}


def _group(day):
    if day is None:
        return "no_record"
    if day.status in _OFF or not day.is_working_day:
        return "off"
    return _GROUPS[day.status]


def _day_row(u, day):
    row = user_brief(u)
    if day is not None:
        row.update(status=day.status, first_in=_time(day.first_in), last_out=_time(day.last_out),
                   late_minutes=day.late_minutes, early_leave_minutes=day.early_leave_minutes,
                   worked_minutes=day.worked_minutes)
    return row


@tool("attendance_day", title="Attendance of a day",
      description="Who was present, late, absent, on leave or off on a date (default today) among the "
                  "users whose attendance you can see, optionally for one department (name or uuid). "
                  "Reads stored attendance only; days not evaluated yet appear under no_record.",
      schema={"type": "object", "properties": {
          "date": {"type": "string", "format": "date"},
          "department": {"type": "string", "maxLength": 100, "description": "Department name or uuid"},
          "limit": {**limit_schema(), "description": "Max users listed per group"}}},
      visible=is_payroll_viewer)
def attendance_day(user, args):
    d = args.get("date") or date.today()
    users = scoped_users(user)
    if dept := args.get("department", "").strip():
        uid = _uuid(dept)
        depts = Department.objects.filter(uuid=uid) if uid else Department.objects.filter(name__icontains=dept)
        if not depts.exists():
            raise ToolError("Department not found", "not_found")
        users = users.filter(department__in=depts)
    users = [u for u in users.select_related("department").order_by("first_name", "username")
             if can_view_user(user, u)]
    days = {x.user_id: x for x in AttendanceDay.objects.filter(date=d, user__in=users)}
    limit = args["limit"]
    groups = {k: [] for k in ("present", "late", "absent", "on_leave", "incomplete", "excused", "off",
                              "no_record")}
    for u in users:
        groups[_group(days.get(u.pk))].append(_day_row(u, days.get(u.pk)))
    counts = {k: len(v) for k, v in groups.items()}
    data = {"date": d.isoformat(), "counts": counts, "total": len(users),
            "groups": {k: v[:limit] for k, v in groups.items()},
            "truncated": any(len(v) > limit for v in groups.values())}
    return "%s: %d present, %d late, %d absent, %d on leave" % (
        d.isoformat(), counts["present"], counts["late"], counts["absent"], counts["on_leave"]), data


@tool("attendance_summary", title="Attendance summary",
      description="Attendance totals of a user (default you) over a payroll period (YYYY-MM, default "
                  "the current one): present, late, absent, leave days, late minutes, deductions, "
                  "plus leave balances for the period's year.",
      schema={"type": "object", "properties": {
          "user_uuid": {"type": "string", "format": "uuid"},
          "period": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}}})
def attendance_summary(user, args):
    target = _target(user, args.get("user_uuid"))
    start_day = AttendanceSettings.get().period_start_day
    key = args.get("period") or period_key_for(date.today(), start_day)
    try:
        start, end = period_range(key, start_day)
    except ValueError:
        raise ToolError("period must be YYYY-MM", "invalid_arguments")
    days = list(AttendanceDay.objects.filter(user=target, date__gte=start, date__lte=end))
    summary = day_summary(days)
    data = {"user": user_brief(target),
            "period": {"key": key, "start": start.isoformat(), "end": end.isoformat()},
            "summary": summary, "leave": {"year": end.year,
                                          "balances": [balance_data(r) for r in
                                                       leave_svc.balances(target, end.year)]}}
    return "%s %s: %d present, %d late, %d absent" % (
        target.username, key, summary["present"], summary["late"], summary["absent"]), data


def _request_item(req):
    lt = req.leave_type
    return {
        "uuid": str(req.pk), "user": user_brief(req.user), "kind": req.kind, "status": req.status,
        "start_date": req.start_date, "end_date": req.end_date,
        "leave_type": {"uuid": str(lt.pk), "name": lt.name} if lt else None,
        "leave_days": float(req.leave_days), "minutes": req.minutes, "punch_time": req.punch_time,
        "details": req.details, "decision_note": req.decision_note,
        "decided_by": req.decided_by.username if req.decided_by else None,
        "decided_at": req.decided_at, "created_at": req.created_at,
    }


def _requests_queryset(viewer, args):
    """Mirrors the REST list (views/requests.py::_list_queryset): scope, then filters."""
    qs = request_svc.request_queryset()
    scope = args["scope"]
    if scope == "mine":
        qs = qs.filter(user=viewer)
    elif scope == "approvals":
        qs = qs.filter(status=RequestStatus.PENDING, user__in=scoped_users(viewer))
    elif not is_hr_plus(viewer):
        visible = Q(user=viewer)
        if viewer.role == UserTypes.MANAGER and viewer.department_id is not None:
            visible |= Q(user__department_id=viewer.department_id)
        qs = qs.filter(visible)
    if args.get("user_uuid"):
        qs = qs.filter(user__uuid=args["user_uuid"])
    if args.get("kind"):
        qs = qs.filter(kind=args["kind"])
    if args.get("status"):
        qs = qs.filter(status=args["status"])
    if args.get("from"):
        qs = qs.filter(end_date__gte=args["from"])
    if args.get("to"):
        qs = qs.filter(start_date__lte=args["to"])
    return qs


@tool("list_requests", title="List attendance requests",
      description="Attendance requests (leave, excuses, missed punch, ...). scope: approvals (pending "
                  "requests you can decide, default), mine (your own) or all (every request you can "
                  "see). Filter by status, kind, user and a date range overlapping the request.",
      schema={"type": "object", "properties": {
          "scope": {"type": "string", "enum": list(SCOPES), "default": "approvals"},
          "status": {"type": "string", "enum": [s.value for s in RequestStatus]},
          "kind": {"type": "string", "enum": [k.value for k in RequestKind]},
          "user_uuid": {"type": "string", "format": "uuid"},
          "from": {"type": "string", "format": "date"},
          "to": {"type": "string", "format": "date"},
          "limit": limit_schema()}})
def list_requests(user, args):
    reqs = (r for r in _requests_queryset(user, args) if can_view_user(user, r.user))
    if args["scope"] == "approvals":
        reqs = (r for r in reqs if can_decide(user, r))
    items = []
    for r in reqs:
        items.append(r)
        if len(items) > args["limit"]:
            break
    result = list_result(items, _request_item, args["limit"])
    return "%d requests%s" % (result["count"], " (truncated)" if result["truncated"] else ""), result


@tool("get_request", title="Get attendance request",
      description="One attendance request with its decision details, the attendance days it affected "
                  "and whether you can approve/reject it.",
      schema={"type": "object", "required": ["request_uuid"], "properties": {
          "request_uuid": {"type": "string", "format": "uuid"}}})
def get_request(user, args):
    req = visible_request(user, args["request_uuid"])
    data = _request_item(req)
    data.update(
        created_by=req.created_by.username if req.created_by else None,
        cancels=str(req.cancels_id) if req.cancels_id else None,
        over_balance=req.over_balance,
        has_attachment=bool(req.attachment),
        can_decide=req.status == RequestStatus.PENDING and can_decide(user, req),
        days=[{"date": x.date.isoformat(), "status": x.status}
              for x in req.attendance_days.order_by("date")])
    return "%s %s request (%s)" % (req.user.username, req.kind, req.status), data


@tool("leave_balances", title="Leave balances",
      description="Leave balances (allowance, used, pending, remaining per leave type) of a user "
                  "(default you) for a year (default current).",
      schema={"type": "object", "properties": {
          "user_uuid": {"type": "string", "format": "uuid"},
          "year": {"type": "integer", "minimum": 2000, "maximum": 2100}}})
def leave_balances(user, args):
    target = _target(user, args.get("user_uuid"))
    year = args.get("year") or date.today().year
    rows = [balance_data(r) for r in leave_svc.balances(target, year)]
    return "%d leave balances for %s (%d)" % (len(rows), target.username, year), {
        "user": user_brief(target), "year": year, "balances": rows}
