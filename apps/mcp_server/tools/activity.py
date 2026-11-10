from datetime import datetime

from django.db.models import Q

from apps.activity.permissions import can_view_activity, scope_user_ids, scope_users, visible_events
from apps.activity.services.presence import presence_rows
from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.common import limit_schema, list_result
from apps.users.admin_permissions import can_view_user
from apps.users.models import User


def _vis(viewer, u) -> bool:
    return u is not None and (u.pk == viewer.pk or can_view_user(viewer, u))


def _ref(viewer, u):
    if not _vis(viewer, u):
        return None
    return {"uuid": str(u.uuid), "name": u.get_full_name().strip() or u.username}


@tool("team_activity", title="Team activity",
      description="Recent activity events (newest first) and online presence for the users you "
                  "supervise, optionally for one user and a date range.",
      schema={"type": "object", "properties": {
          "user_uuid": {"type": "string", "format": "uuid"},
          "from": {"type": "string", "format": "date"},
          "to": {"type": "string", "format": "date"},
          "limit": limit_schema()}})
def team_activity(user, args):
    if not can_view_activity(user):
        raise ToolError("You do not have permission to do that.", "forbidden")
    qs = visible_events(user)
    if args.get("from"):
        qs = qs.filter(created_at__date__gte=args["from"])
    if args.get("to"):
        qs = qs.filter(created_at__date__lte=args["to"])
    users = scope_users(user).select_related("department")
    if args.get("user_uuid"):
        target = User.objects.filter(pk=args["user_uuid"]).first()
        ids = scope_user_ids(user)
        if (target is None or not _vis(user, target)
                or (ids is not None and target.pk not in ids and target.pk != user.pk)):
            raise ToolError("User not found", "not_found")
        qs = qs.filter(Q(actor_id=target.pk) | Q(subject_id=target.pk))
        users = users.filter(pk=target.pk)
    limit = args["limit"]
    qs = qs.order_by("-created_at", "-pk")[:limit + 1]

    def event(e):
        return {"uuid": str(e.uuid), "created_at": e.created_at.isoformat(), "verb": e.verb,
                "area": e.area, "actor": _ref(user, e.actor), "subject": _ref(user, e.subject),
                "target_type": e.target_type, "target_label": e.target_label, "data": e.data}

    res = list_result(qs, event, limit)
    rows = presence_rows([u for u in users if _vis(user, u)], datetime.now())
    res["presence"] = [{"uuid": r["user"]["uuid"], "name": r["user"]["name"], "role": r["user"]["role"],
                        "online": r["online"], "last_seen": r["last_seen"],
                        "current_page": r["current_page"], "today_seconds": r["today_seconds"]}
                       for r in rows]
    return "%d events, %d users%s" % (res["count"], len(res["presence"]),
                                      " (truncated)" if res["truncated"] else ""), res
