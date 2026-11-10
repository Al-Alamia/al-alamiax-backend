from apps.mcp_server.errors import ToolError
from apps.mcp_server.registry import tool
from apps.mcp_server.tools.attendance import request_detail, visible_request
from apps.mcp_server.tools.common import user_brief
from apps.attendance.services import requests as request_svc
from apps.users.lead_permissions import assignable_agents_qs, capabilities, scope_queryset
from apps.users.models import Lead
from apps.users.services.leads import assign_leads as assign_leads_svc
from apps.users.types import AssignmentKinds


@tool("approve_request", title="Approve attendance request", read_only=False,
      description="Approve a pending attendance request you are allowed to decide. Changes real "
                  "attendance/leave data. over_balance (HR only) approves leave beyond the balance.",
      schema={"type": "object", "required": ["request_uuid"], "properties": {
          "request_uuid": {"type": "string", "format": "uuid"},
          "note": {"type": "string", "maxLength": 500, "default": ""},
          "over_balance": {"type": "boolean", "default": False}}})
def approve_request(user, args):
    req = visible_request(user, args["request_uuid"])
    req = request_svc.approve(user, req, args["note"], args["over_balance"])
    return "Approved %s request of %s" % (req.kind, req.user.username), request_detail(user, req)


@tool("reject_request", title="Reject attendance request", read_only=False,
      description="Reject a pending attendance request you are allowed to decide. A note is required.",
      schema={"type": "object", "required": ["request_uuid", "note"], "properties": {
          "request_uuid": {"type": "string", "format": "uuid"},
          "note": {"type": "string", "minLength": 1, "maxLength": 500}}})
def reject_request(user, args):
    req = visible_request(user, args["request_uuid"])
    req = request_svc.reject(user, req, args["note"])
    return "Rejected %s request of %s" % (req.kind, req.user.username), request_detail(user, req)


@tool("assign_leads", title="Assign leads", read_only=False,
      description="Assign leads you can see to a Sales agent (kind: the assignment role). Replaces the "
                  "current assignee of that kind. All-or-nothing.",
      schema={"type": "object", "required": ["lead_uuids", "agent_uuid", "kind"], "properties": {
          "lead_uuids": {"type": "array", "minItems": 1, "maxItems": 100, "uniqueItems": True,
                         "items": {"type": "string", "format": "uuid"}},
          "agent_uuid": {"type": "string", "format": "uuid"},
          "kind": {"type": "string", "enum": list(AssignmentKinds.values)}}},
      visible=lambda u: capabilities(u)["assign"])
def assign_leads(user, args):
    if not capabilities(user)["assign"]:
        raise ToolError("You do not have permission to perform this action", "forbidden")
    agent = assignable_agents_qs(user).select_related("department").filter(pk=args["agent_uuid"]).first()
    if agent is None:
        raise ToolError("Agent can't be assigned", "forbidden")
    ids = set(args["lead_uuids"])
    leads = list(scope_queryset(user, Lead.objects.all()).filter(pk__in=ids))
    if len(leads) != len(ids):
        raise ToolError("Lead not found", "not_found")
    assignments = assign_leads_svc(user, leads, agent, args["kind"])
    return "Assigned %d leads to %s" % (len(assignments), agent.username), {
        "assigned": len(assignments), "agent": user_brief(agent)}
