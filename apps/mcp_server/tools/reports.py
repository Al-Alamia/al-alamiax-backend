from datetime import date, datetime

from apps.dashboard.registry import build_all
from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.reports.models import ReportType
from apps.reports.permissions import can_view_board
from apps.reports.services.board import build_board
from apps.users.services.marketing_dashboard import build_dashboard
from apps.users.admin_permissions import can_view_user
from apps.users.models import User

_FORBIDDEN = "You do not have permission to do that."


@tool("list_report_types", title="Report types",
      description="Active report types (uuid, name, frequency) you can open the board for.",
      schema={"type": "object", "properties": {}})
def list_report_types(user, args):
    if not can_view_board(user):
        raise ToolError(_FORBIDDEN, "forbidden")
    items = [{"uuid": str(t.uuid), "name": t.name, "frequency": t.frequency}
             for t in ReportType.objects.filter(is_active=True)]
    return "%d report types" % len(items), {"items": items, "count": len(items), "truncated": False}


@tool("report_board", title="Report board",
      description="Submission board of a report type for the period containing a date (default today): "
                  "per-user status, values and totals for the users you supervise.",
      schema={"type": "object", "required": ["report_type_uuid"], "properties": {
          "report_type_uuid": {"type": "string", "format": "uuid"},
          "date": {"type": "string", "format": "date"},
          "project_uuid": {"type": "string", "format": "uuid"}}})
def report_board(user, args):
    if not can_view_board(user):
        raise ToolError(_FORBIDDEN, "forbidden")
    rt = ReportType.objects.filter(pk=args["report_type_uuid"]).first()
    if rt is None:
        raise ToolError("Report type not found", "not_found")
    today = date.today()
    project = args.get("project_uuid")
    data = build_board(rt, user, args.get("date") or today, today, project and str(project))
    data["period"] = {k: v.isoformat() for k, v in data["period"].items()}
    visible = {r["user"]["uuid"] for r in data["rows"]
               if _can_see(user, r["user"]["uuid"])}
    data["rows"] = [r for r in data["rows"] if r["user"]["uuid"] in visible]
    return "Board %s: %d rows" % (rt.name, len(data["rows"])), data


def _can_see(viewer, uid) -> bool:
    if str(viewer.pk) == str(uid):
        return True
    target = User.objects.filter(pk=uid).first()
    return target is not None and can_view_user(viewer, target)


@tool("marketing_dashboard", title="Marketing dashboard",
      description="Lead counts for a month (YYYY-MM, default current): totals, per-project, daily series "
                  "and per-user rows for the users you supervise.",
      schema={"type": "object", "properties": {
          "month": {"type": "string", "pattern": r"^\d{4}-\d{2}$"}}})
def marketing_dashboard(user, args):
    raw = args.get("month")
    try:
        d = datetime.strptime(raw, "%Y-%m").date() if raw else date.today().replace(day=1)
    except ValueError:
        raise ToolError("month must be YYYY-MM", "invalid_arguments")
    data = build_dashboard(user, "month", d)
    data["users"] = [u for u in data["users"] if _can_see(user, u["uuid"])]
    return "Marketing %s: %d leads" % (d.strftime("%Y-%m"), data["total"]), data


@tool("home_dashboard", title="Home dashboard",
      description="Your role-scoped home dashboard widgets (attendance period, requests, salary, reports, "
                  "team, leads, treasury...) exactly as the app shows them.",
      schema={"type": "object", "properties": {}})
def home_dashboard(user, args):
    data = build_all(user, datetime.now())
    return "Dashboard with %d widgets" % len(data["widgets"]), data
