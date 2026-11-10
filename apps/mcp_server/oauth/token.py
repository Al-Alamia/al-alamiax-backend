import base64
import hashlib
import hmac
import json
import re
from datetime import datetime

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt

from apps.mcp_server.eligibility import is_eligible
from apps.mcp_server.models import OAuthAuthorizationCode, OAuthClient, OAuthGrant, OAuthToken

from .base_url import resource_url
from .errors import OAuthError
from .metadata import json_response, preflight
from .tokens import hash_token, issue_pair, rotate_refresh

VERIFIER_RE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")


def _now() -> datetime:
    return datetime.now()


def _respond(data, status=200):
    response = json_response(data, status)
    response["Cache-Control"] = "no-store"
    response["Pragma"] = "no-cache"
    return response


def _params(request) -> dict:
    if (request.content_type or "").startswith("application/json"):
        try:
            data = json.loads(request.body or b"{}")
        except ValueError:
            raise OAuthError("invalid_request", "Malformed JSON body")
        if not isinstance(data, dict):
            raise OAuthError("invalid_request", "Body must be a JSON object")
        return {k: v for k, v in data.items() if isinstance(v, str)}
    try:
        return {k: v for k, v in request.POST.items()}
    except Exception:
        raise OAuthError("invalid_request", "Malformed request body")


def _has_control(value) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in value)


def _required(p, *names):
    missing = [n for n in names if not p.get(n)]
    if missing:
        raise OAuthError("invalid_request", "Missing parameter: " + ", ".join(missing))


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not VERIFIER_RE.fullmatch(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed.encode(), (challenge or "").encode())


def _exchange_code(request, p, client):
    _required(p, "code", "redirect_uri", "code_verifier")
    invalid = OAuthError("invalid_grant", "Invalid authorization code")
    row = (OAuthAuthorizationCode.objects.select_related("user")
           .filter(code_hash=hash_token(p["code"])).first())
    if row is None or row.user is None or row.client_id != client.pk:
        raise invalid
    if row.used_at is not None:
        # Reuse: revoke everything issued from this code (committed, not rolled back).
        OAuthToken.objects.filter(code=row, revoked_at__isnull=True).update(revoked_at=_now())
        raise invalid
    now = _now()
    if row.expires_at <= now or p["redirect_uri"] != row.redirect_uri:
        raise invalid
    if p.get("resource") and p["resource"] != resource_url(request):
        raise invalid
    if row.resource and p.get("resource") and p["resource"] != row.resource:
        raise invalid
    if not _pkce_ok(p["code_verifier"], row.code_challenge) or not is_eligible(row.user):
        raise invalid
    grant = OAuthGrant.objects.active().filter(user=row.user, client=client).first()
    if grant is None:
        raise invalid
    with transaction.atomic():
        claimed = OAuthAuthorizationCode.objects.filter(
            pk=row.pk, used_at__isnull=True).update(used_at=now)
        if claimed:
            grant.last_used_at = now
            grant.save(update_fields=["last_used_at", "updated_at"])
            return issue_pair(grant, code=row)
    OAuthToken.objects.filter(code=row, revoked_at__isnull=True).update(revoked_at=_now())
    raise invalid


@csrf_exempt
def token(request):
    if request.method == "OPTIONS":
        response = preflight("POST, OPTIONS")
        response["Cache-Control"] = "no-store"
        response["Pragma"] = "no-cache"
        return response
    if request.method != "POST":
        return _respond({"error": "method_not_allowed"}, 405)
    try:
        p = _params(request)
        grant_type = p.get("grant_type")
        if grant_type not in ("authorization_code", "refresh_token"):
            raise OAuthError("unsupported_grant_type",
                             "grant_type must be authorization_code or refresh_token")
        _required(p, "client_id")
        if _has_control(p["client_id"]):
            raise OAuthError("invalid_client", "Unknown client_id", 401)
        client = OAuthClient.objects.filter(client_id=p["client_id"]).first()
        if client is None:
            raise OAuthError("invalid_client", "Unknown client_id", 401)
        if grant_type == "authorization_code":
            result = _exchange_code(request, p, client)
        else:
            _required(p, "refresh_token")
            result = rotate_refresh(p["refresh_token"], client)
        client.last_used_at = _now()
        client.save(update_fields=["last_used_at", "updated_at"])
        return _respond(result)
    except OAuthError as e:
        return _respond({"error": e.error, "error_description": e.description}, e.status)
