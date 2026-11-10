import uuid

from django.db import transaction
from rest_framework.decorators import (
    api_view, authentication_classes, parser_classes, permission_classes)
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.activity.services.events import record_event
from apps.mcp_server.eligibility import is_eligible
from apps.mcp_server.models import OAuthGrant
from apps.mcp_server.oauth.base_url import public_base
from apps.mcp_server.oauth.tokens import revoke_grant
from apps.users.AuthenticationClasses import EnforcedJWTAuthentication
from apps.users.admin_permissions import is_top
from apps.users.models import User


def _error(kind, message, status):
    return Response({"type": kind, "message": message}, status=status)


# Header-only JWT auth and JSON-only bodies, like the consent endpoint: api_view is
# CSRF-exempt, so cookies must never authenticate these state-changing routes.
@api_view(["GET"])
@authentication_classes([EnforcedJWTAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def grants(request):
    owner = request.user
    raw = request.query_params.get("user")
    if raw:
        if not is_top(request.user):
            return _error("forbidden", "Not allowed to view other users' connections.", 403)
        try:
            owner = User.objects.filter(pk=uuid.UUID(raw)).first()
        except ValueError:
            return _error("validation_error", "user must be a valid UUID.", 400)
        if owner is None:
            return _error("not_found", "User not found", 404)
    rows = (OAuthGrant.objects.active().filter(user=owner).select_related("client")
            .order_by("-created_at"))
    return Response([{
        "uuid": str(g.uuid), "client_name": g.client.client_name,
        "created_at": g.created_at, "last_used_at": g.last_used_at,
    } for g in rows])


@api_view(["DELETE"])
@authentication_classes([EnforcedJWTAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def revoke(request, grant_uuid):
    grant = (OAuthGrant.objects.active().select_related("client", "user")
             .filter(pk=grant_uuid).first())
    if grant is None or (grant.user_id != request.user.pk and not is_top(request.user)):
        return _error("not_found", "Connection not found", 404)
    with transaction.atomic():
        revoke_grant(grant, by=request.user)
        record_event(request.user, "mcp.grant_revoked", subject=grant.user, target=grant,
                     label=grant.client.client_name)
    return Response(status=204)


@api_view(["GET"])
@authentication_classes([EnforcedJWTAuthentication])
@parser_classes([JSONParser])
@permission_classes([IsAuthenticated])
def access(request):
    return Response({"eligible": is_eligible(request.user),
                     "connector_url": public_base(request) + "/mcp"})
