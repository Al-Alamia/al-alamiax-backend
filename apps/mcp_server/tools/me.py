from apps.mcp_server.registry import tool, visible_tools
from apps.mcp_server.tools.common import user_brief


@tool("whoami", title="Who am I",
      description="Show the authenticated user: role, department and the tool names available to them.",
      schema={"type": "object", "properties": {}})
def whoami(user, args):
    data = user_brief(user)
    data["is_superuser"] = bool(user.is_superuser)
    data["tools"] = sorted(t.name for t in visible_tools(user))
    return "Signed in as %s (%s)" % (data["username"], data["role"]), data
