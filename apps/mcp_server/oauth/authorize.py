import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.views.decorators.http import require_GET
from rest_framework.decorators import (
    api_view, authentication_classes, parser_classes, permission_classes)
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activity.services.events import record_event
from apps.users.AuthenticationClasses import EnforcedJWTAuthentication
from apps.mcp_server.eligibility import is_eligible
from apps.mcp_server.models import OAuthAuthorizationCode, OAuthClient, OAuthGrant

from .base_url import frontend_base, resource_url
from .tokens import hash_token

REQUEST_TTL = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now()


def _with_query(uri: str, params: dict) -> str:
    parts = urlparse(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + [
        (k, v) for k, v in params.items() if v not in (None, "")]
    return urlunparse(parts._replace(query=urlencode(query)))


def _error_redirect(redirect_uri, state, error, description):
    return HttpResponseRedirect(_with_query(
        redirect_uri, {"error": error, "error_description": description, "state": state}))


@require_GET
def authorize(request):
    q = request.GET
    client = OAuthClient.objects.filter(client_id=q.get("client_id", "")).first()
    redirect_uri = q.get("redirect_uri", "")
    if client is None or redirect_uri not in (client.redirect_uris or []):
        return HttpResponse("Invalid client_id or redirect_uri.", status=400,
                            content_type="text/plain")
    state = q.get("state", "")
    if q.get("response_type") != "code":
        return _error_redirect(redirect_uri, state, "unsupported_response_type",
                               "response_type must be 'code'.")
    challenge = q.get("code_challenge", "")
    if not challenge or len(challenge) > 128 or q.get("code_challenge_method") != "S256":
        return _error_redirect(redirect_uri, state, "invalid_request",
                               "PKCE with code_challenge_method=S256 is required.")
    resource = q.get("resource", "")
    if resource and resource != resource_url(request):
        return _error_redirect(redirect_uri, state, "invalid_target",
                               "resource does not match this server.")
    row = OAuthAuthorizationCode.objects.create(
        request_id=secrets.token_urlsafe(24), client=client, redirect_uri=redirect_uri,
        code_challenge=challenge, state=state, resource=resource,
        expires_at=_now() + REQUEST_TTL)
    return HttpResponseRedirect(
        frontend_base(request) + "/oauth/consent?" + urlencode({"request": row.request_id}))


def _not_found():
    return Response({"type": "not_found",
                     "message": "Authorization request expired or not found"}, status=404)


def _not_eligible():
    return Response({"type": "not_eligible",
                     "message": "Your role can't connect AI apps."}, status=403)


def _pending(request_id):
    return (OAuthAuthorizationCode.objects.select_related("client")
            .filter(request_id=request_id, used_at__isnull=True, user__isnull=True,
                    code_hash__isnull=True, expires_at__gt=_now()).first())


# api_view is CSRF-exempt, so accept only the Authorization header (never cookies or
# body tokens) and only JSON bodies; a cross-site form POST can then not authenticate.
@api_view(["GET", "POST"])
@authentication_classes([EnforcedJWTAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def consent(request):
    user = request.user
    data = request.query_params if request.method == "GET" else request.data
    request_id = data.get("request")
    row = _pending(request_id) if isinstance(request_id, str) and request_id else None
    if row is None:
        return _not_found()
    if not is_eligible(user):
        return _not_eligible()
    client = row.client

    if request.method == "GET":
        return Response({
            "client_name": client.client_name,
            "redirect_host": urlparse(row.redirect_uri).netloc,
            "user": {"name": user.get_full_name() or user.username, "role": user.role},
            "eligible": True,
        })

    decision = data.get("decision")
    if decision not in ("approve", "deny"):
        return Response({"type": "validation_error",
                         "message": "decision must be 'approve' or 'deny'."}, status=400)

    now = _now()
    with transaction.atomic():
        claimed = OAuthAuthorizationCode.objects.filter(
            pk=row.pk, used_at__isnull=True, user__isnull=True, code_hash__isnull=True,
            expires_at__gt=now)
        if decision == "deny":
            if not claimed.update(used_at=now):
                return _not_found()
            return Response({"redirect_to": _with_query(
                row.redirect_uri, {"error": "access_denied", "state": row.state})})

        raw = "amx_ac_" + secrets.token_urlsafe(32)
        if not claimed.update(user=user, code_hash=hash_token(raw)):
            return _not_found()
        grant = OAuthGrant.objects.active().filter(user=user, client=client).first()
        if grant is None:
            try:
                with transaction.atomic():
                    grant = OAuthGrant.objects.create(user=user, client=client)
            except IntegrityError:
                # A concurrent approve created the active grant first.
                grant = OAuthGrant.objects.active().get(user=user, client=client)
            else:
                record_event(user, "mcp.grant_created", target=grant, label=client.client_name)
    return Response({"redirect_to": _with_query(
        row.redirect_uri, {"code": raw, "state": row.state})})
