import json
import re
import secrets
import time
from urllib.parse import urlparse

from django.views.decorators.csrf import csrf_exempt

from apps.attendance.services.web_policy import client_ip
from apps.mcp_server import ratelimit
from apps.mcp_server.models import OAuthClient

from .metadata import json_response, preflight

MAX_REDIRECT_URIS = 10
LOCAL_NETLOC = re.compile(r"^(localhost|127\.0\.0\.1)(:[0-9]+)?$", re.IGNORECASE)


def _error(error, description):
    return json_response({"error": error, "error_description": description}, 400)


def _valid_redirect_uri(uri) -> bool:
    if not isinstance(uri, str) or not uri or len(uri) > 2000:
        return False
    if "\\" in uri or any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in uri):
        return False
    try:
        parsed = urlparse(uri)
        parsed.port  # raises ValueError on a bad port
    except ValueError:
        return False
    if parsed.fragment or "#" in uri or not parsed.hostname:
        return False
    if parsed.username is not None or "@" in parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and bool(LOCAL_NETLOC.match(parsed.netloc))


@csrf_exempt
def register(request):
    if request.method == "OPTIONS":
        return preflight("POST, OPTIONS")
    if request.method != "POST":
        return json_response({"error": "method_not_allowed"}, 405)
    if not ratelimit.hit("register:" + client_ip(request), 10, 3600):
        return json_response({"error": "rate_limited"}, 429)
    try:
        body = json.loads(request.body.decode("utf-8") or "")
    except (ValueError, UnicodeDecodeError):
        return _error("invalid_client_metadata", "Body must be a JSON object.")
    if not isinstance(body, dict):
        return _error("invalid_client_metadata", "Body must be a JSON object.")

    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECT_URIS:
        return _error("invalid_redirect_uri", "redirect_uris must be a list of 1 to 10 URIs.")
    if not all(_valid_redirect_uri(u) for u in uris):
        return _error(
            "invalid_redirect_uri",
            "Each redirect URI must be https, or http on localhost/127.0.0.1, without a fragment.")

    method = body.get("token_endpoint_auth_method")
    if method is not None and method != "none":
        return _error("invalid_client_metadata", "Only token_endpoint_auth_method 'none' is supported.")

    name = body.get("client_name", "AI client")
    if name is None or name == "":
        name = "AI client"
    if not isinstance(name, str) or len(name) > 100:
        return _error("invalid_client_metadata", "client_name must be a string of at most 100 characters.")

    client = OAuthClient.objects.create(
        client_id=secrets.token_urlsafe(24), client_name=name, redirect_uris=uris)
    return json_response({
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_id_issued_at": int(time.time()),
    }, 201)
