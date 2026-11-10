from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .base_url import public_base, resource_url

CORS_HEADERS = "Authorization, Content-Type, MCP-Protocol-Version"


def json_response(data, status=200):
    response = JsonResponse(data, status=status)
    response["Access-Control-Allow-Origin"] = "*"
    return response


def preflight(methods="GET, POST, OPTIONS"):
    response = HttpResponse(status=204)
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = methods
    response["Access-Control-Allow-Headers"] = CORS_HEADERS
    return response


@csrf_exempt
def protected_resource_metadata(request, *args, **kwargs):
    if request.method == "OPTIONS":
        return preflight("GET, OPTIONS")
    if request.method != "GET":
        return json_response({"error": "method_not_allowed"}, 405)
    base = public_base(request)
    return json_response({
        "resource": resource_url(request),
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["mcp"],
    })


@csrf_exempt
def authorization_server_metadata(request):
    if request.method == "OPTIONS":
        return preflight("GET, OPTIONS")
    if request.method != "GET":
        return json_response({"error": "method_not_allowed"}, 405)
    base = public_base(request)
    return json_response({
        "issuer": base,
        "authorization_endpoint": base + "/oauth/authorize",
        "token_endpoint": base + "/oauth/token",
        "registration_endpoint": base + "/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": ["mcp"],
    })
