import json
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from apps.mcp_server import ratelimit
from apps.mcp_server.models import OAuthGrant
from apps.mcp_server.oauth.base_url import public_base
from apps.mcp_server.oauth.tokens import resolve_access
from apps.mcp_server.registry import call_tool, load_tools, tool_descriptor, visible_tools

SUPPORTED_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
DEFAULT_VERSION = "2025-06-18"
INSTRUCTIONS = (
    "Al-AlamiaX CRM/HR tools. You act as the signed-in user and see only what they can see in "
    "the app. Identify people, leads and requests by uuid (use search_users / search_leads / "
    "list_requests first). Periods are payroll period keys like 2026-11; months are YYYY-MM. "
    "Write tools change real data: confirm with the user first."
)
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
ALLOW_HEADERS = "Authorization, Content-Type, MCP-Protocol-Version, Mcp-Session-Id"
EXPOSE_HEADERS = "WWW-Authenticate, Mcp-Protocol-Version"


def _cors(response, origin=None):
    response["Access-Control-Allow-Origin"] = origin or "*"
    response["Access-Control-Expose-Headers"] = EXPOSE_HEADERS
    if origin:
        response["Vary"] = "Origin"
    return response


def _json(data, status=200, origin=None):
    return _cors(JsonResponse(data, status=status, safe=False), origin)


def _allowed_origins(request):
    base = public_base(request)
    parts = urlsplit(base)
    own = "%s://%s" % (parts.scheme, parts.netloc)
    allowed = {o.rstrip("/") for o in getattr(settings, "MCP_ALLOWED_ORIGINS", [])}
    allowed.add(own.rstrip("/"))
    return allowed


def _bearer(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
        return parts[1].strip()
    return None


def _unauthorized(request, sent, origin):
    challenge = 'Bearer resource_metadata="%s/.well-known/oauth-protected-resource"' % public_base(request)
    if sent:
        challenge += ', error="invalid_token"'
    response = _json({"error": "invalid_token" if sent else "unauthorized"}, 401, origin)
    response["WWW-Authenticate"] = challenge
    return response


def _err(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _ok(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _touch(grant):
    now = datetime.now()
    if grant.last_used_at is None or now - grant.last_used_at > timedelta(seconds=60):
        OAuthGrant.objects.filter(pk=grant.pk).update(last_used_at=now)


def _handle(msg, user, grant):
    """Return a response dict, or None for notifications."""
    if (not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0"
            or not isinstance(msg.get("method"), str)):
        msg_id = msg.get("id") if isinstance(msg, dict) else None
        return _err(msg_id, INVALID_REQUEST, "Invalid Request")
    is_notification = "id" not in msg
    msg_id = msg.get("id")
    method = msg["method"]
    params = msg.get("params")
    if is_notification:
        return None
    if params is not None and not isinstance(params, dict):
        return _err(msg_id, INVALID_PARAMS, "params must be an object")
    params = params or {}

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else DEFAULT_VERSION
        return _ok(msg_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "al-alamiax", "version": "1.0"},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return _ok(msg_id, {})
    if method == "tools/list":
        return _ok(msg_id, {"tools": [tool_descriptor(t) for t in visible_tools(user)]})
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return _err(msg_id, INVALID_PARAMS, "name must be a string")
        arguments = params.get("arguments")
        result = call_tool(user, name, arguments if arguments is not None else {},
                           grant=grant, client_name=grant.client.client_name)
        return _ok(msg_id, result)
    return _err(msg_id, METHOD_NOT_FOUND, "Method not found: %s" % method)


@csrf_exempt
def mcp_endpoint(request):
    if request.method == "OPTIONS":
        response = HttpResponse(status=204)
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = ALLOW_HEADERS
        response["Access-Control-Expose-Headers"] = EXPOSE_HEADERS
        return response
    if request.method != "POST":
        response = _json({"error": "method_not_allowed"}, 405)
        response["Allow"] = "POST"
        return response

    origin = request.META.get("HTTP_ORIGIN")
    if origin is not None and origin.rstrip("/") not in _allowed_origins(request):
        return _json({"error": "forbidden_origin"}, 403)

    raw = _bearer(request)
    token = resolve_access(raw) if raw else None
    if token is None:
        return _unauthorized(request, raw is not None, origin)
    grant = token.grant
    user = grant.user

    limit = getattr(settings, "MCP_RATE_LIMIT_PER_MIN", 120)
    if not ratelimit.hit("mcp:rl:%s" % grant.uuid, limit, 60):
        response = _json({"error": "rate_limited"}, 429, origin)
        response["Retry-After"] = "60"
        return response

    _touch(grant)
    load_tools()

    try:
        body = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _json(_err(None, PARSE_ERROR, "Parse error"), 200, origin)

    if isinstance(body, list):
        if not body:
            return _json(_err(None, INVALID_REQUEST, "Invalid Request"), 200, origin)
        responses = [r for r in (_handle(m, user, grant) for m in body) if r is not None]
        if not responses:
            return _cors(HttpResponse(status=202), origin)
        return _json(responses, 200, origin)

    response = _handle(body, user, grant)
    if response is None:
        return _cors(HttpResponse(status=202), origin)
    return _json(response, 200, origin)
