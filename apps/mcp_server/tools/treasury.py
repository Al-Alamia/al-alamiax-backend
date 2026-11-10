from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.common import is_top, limit_schema, list_result
from apps.treasury import serializers as s
from apps.treasury.models import ProjectGroup
from apps.treasury.services import ledger
from apps.treasury.views.ledger import _filtered_entries
from apps.users.admin_permissions import can_view_user

GROUP = {"type": "string", "format": "uuid", "description": "Project group uuid (omit for all)"}
FROM = {"type": "string", "format": "date"}
TO = {"type": "string", "format": "date"}


def _params(args):
    """Translate tool args to the REST list filters."""
    p = {}
    if args.get("group_uuid"):
        if not ProjectGroup.objects.filter(pk=args["group_uuid"]).exists():
            raise ToolError("Project group not found", "not_found")
        p["group"] = str(args["group_uuid"])
    if args.get("from"):
        p["date_from"] = args["from"].isoformat()
    if args.get("to"):
        p["date_to"] = args["to"].isoformat()
    return p


def _entry(viewer, e):
    d = s.entry_data(e)
    cb = e.created_by
    if cb is not None and not (cb.pk == viewer.pk or can_view_user(viewer, cb)):
        d["created_by"] = None
    return d


@tool("treasury_balance", title="Treasury balance",
      description="Treasury income, outcome and net (reversals netted; money as 2-decimal strings), "
                  "optionally for one project group and a date range. Owner-level only.",
      schema={"type": "object", "properties": {"group_uuid": GROUP, "from": FROM, "to": TO}},
      visible=is_top)
def treasury_balance(user, args):
    if not is_top(user):
        raise ToolError("Only the owner can access the treasury.", "forbidden")
    t = s.totals_data(ledger.totals(_filtered_entries(_params(args)).order_by()))
    return "Treasury net %s (in %s, out %s)" % (t["net"], t["income"], t["outcome"]), t


@tool("list_treasury_entries", title="Treasury entries",
      description="Treasury ledger entries, newest first, optionally filtered by project group, date "
                  "range, kind (in/out) and category. Reversed entries and reversals are included.",
      schema={"type": "object", "properties": {
          "group_uuid": GROUP, "from": FROM, "to": TO,
          "kind": {"type": "string", "enum": ["in", "out"]},
          "category": {"type": "string", "enum": ["income", "advance", "operating", "other"]},
          "limit": limit_schema()}},
      visible=is_top)
def list_treasury_entries(user, args):
    if not is_top(user):
        raise ToolError("Only the owner can access the treasury.", "forbidden")
    p = _params(args)
    if args.get("kind"):
        p["direction"] = args["kind"]
    if args.get("category"):
        p["category"] = args["category"]
    limit = args["limit"]
    qs = _filtered_entries(p).order_by("-date", "-created_at")[:limit + 1]
    res = list_result(qs, lambda e: _entry(user, e), limit)
    return "%d treasury entries%s" % (res["count"], " (truncated)" if res["truncated"] else ""), res
