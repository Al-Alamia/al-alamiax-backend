import uuid
from datetime import datetime

from django.db.models import Count, Q
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.views.pagination import DefaultPagination

from apps.users.models import Department, Project, User
from apps.users.types import UserTypes

from .models import Notification, NotificationRecipient
from .permissions import can_send, sees_all_sent
from .queries import active_rows, visible_rows
from .serializers import InboxItemSerializer, SentItemSerializer, _sender
from .services import notify, resolve_audience
from .types import NotificationKinds


def _now() -> datetime:
    return datetime.now()


def _error(message, type, status):
    return Response({"message": message, "type": type}, status=status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def inbox(request):
    now = _now()
    qs = visible_rows(request.user)
    if request.query_params.get("unread") in ("1", "true", "True"):
        qs = qs.filter(read_at__isnull=True)
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    data = InboxItemSerializer(page, many=True, context={"now": now}).data
    return paginator.get_paginated_response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def unread_count(request):
    n = active_rows(request.user, _now()).filter(read_at__isnull=True).count()
    return Response({"unread": n})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def read(request):
    uuids = request.data.get("uuids") if hasattr(request.data, "get") else None
    if not isinstance(uuids, list):
        return _error("uuids must be a list.", "invalid_body", 400)
    valid = []
    for s in uuids:
        try:
            valid.append(uuid.UUID(str(s)))
        except ValueError:
            continue
    updated = visible_rows(request.user).filter(
        read_at__isnull=True, notification__uuid__in=valid
    ).update(read_at=_now())
    return Response({"updated": updated})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def read_all(request):
    now = _now()
    ids = list(active_rows(request.user, now).filter(read_at__isnull=True).values_list("pk", flat=True))
    updated = NotificationRecipient.objects.filter(pk__in=ids).update(read_at=now)
    return Response({"updated": updated})


def _sent_qs(user):
    qs = Notification.objects.filter(kind=NotificationKinds.MANUAL).select_related("sender")
    if not sees_all_sent(user):
        qs = qs.filter(sender=user)
    return qs


def _parse_uuids(raw, model):
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("must be a list")
    ids = []
    for s in raw:
        try:
            ids.append(uuid.UUID(str(s)))
        except (ValueError, AttributeError):
            raise ValueError(f"invalid uuid: {s}")
    ids = list(dict.fromkeys(ids))
    if model.objects.filter(pk__in=ids).count() != len(ids):
        raise ValueError("unknown target")
    return ids


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send(request):
    if not can_send(request.user):
        return _error("You are not allowed to send notifications.", "forbidden", 403)
    data = request.data
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return _error("message is required.", "invalid_body", 400)
    if len(message) > 1000:
        return _error("message must be at most 1000 characters.", "invalid_body", 400)
    title = data.get("title") or ""
    link = data.get("link") or ""
    if not isinstance(title, str) or len(title) > 120 or not isinstance(link, str) or len(link) > 300:
        return _error("title or link is invalid.", "invalid_body", 400)

    now = _now()
    expires_at = None
    if data.get("expires_at") not in (None, ""):
        try:
            expires_at = parse_datetime(str(data["expires_at"]))
        except ValueError:
            expires_at = None
        if expires_at is None:
            return _error("expires_at is invalid.", "invalid_body", 400)
        expires_at = expires_at.replace(tzinfo=None)
        if expires_at <= now:
            return _error("expires_at must be in the future.", "invalid_body", 400)

    try:
        users = _parse_uuids(data.get("users"), User)
        departments = _parse_uuids(data.get("departments"), Department)
        projects = _parse_uuids(data.get("projects"), Project)
    except ValueError as e:
        return _error(str(e), "invalid_target", 400)
    roles = data.get("roles") or []
    if not isinstance(roles, list) or any(r not in UserTypes.values for r in roles):
        return _error("Unknown role.", "invalid_target", 400)
    roles = list(dict.fromkeys(roles))
    everyone = data.get("everyone") is True

    if not (users or departments or projects or roles or everyone):
        return _error("Pick at least one target.", "no_targets", 400)

    try:
        recipients = list(resolve_audience(
            request.user, users=users, departments=departments, projects=projects,
            roles=roles, everyone=everyone,
        ))
    except PermissionDenied as e:
        return _error(str(e.detail), "forbidden", 403)
    if not recipients:
        return _error("The selected audience has no recipients.", "no_recipients", 400)

    audience = {}
    if users:
        audience["users"] = [str(u) for u in users]
    if departments:
        audience["departments"] = [str(d) for d in departments]
    if projects:
        audience["projects"] = [str(p) for p in projects]
    if roles:
        audience["roles"] = roles
    if everyone:
        audience["everyone"] = True

    n = notify(recipients, message, title=title, link=link, sender=request.user,
               expires_at=expires_at, audience=audience)
    n = _annotated(Notification.objects.filter(pk=n.pk).select_related("sender")).get()
    return Response(SentItemSerializer(n).data, status=201)


def _annotated(qs):
    return qs.annotate(
        recipients_count=Count("recipients"),
        read_count=Count("recipients", filter=Q(recipients__read_at__isnull=False)),
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sent(request):
    if not can_send(request.user):
        return _error("You are not allowed to view sent notifications.", "forbidden", 403)
    qs = _annotated(_sent_qs(request.user)).order_by("-created_at")
    paginator = DefaultPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response(SentItemSerializer(page, many=True).data)


def _get_sent(request, uuid):
    if not can_send(request.user):
        return None
    return _sent_qs(request.user).filter(pk=uuid).first()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sent_recipients(request, uuid):
    n = _get_sent(request, uuid)
    if n is None:
        return _error("Not found.", "not_found", 404)
    rows = n.recipients.select_related("user").order_by("user__first_name", "user__username")
    return Response([{"user": _sender(r.user), "read_at": r.read_at} for r in rows])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def sent_retract(request, uuid):
    n = _get_sent(request, uuid)
    if n is None:
        return _error("Not found.", "not_found", 404)
    if n.retracted_at is None:
        n.retracted_at = _now()
        n.save(update_fields=["retracted_at"])
    n = _annotated(Notification.objects.filter(pk=n.pk).select_related("sender")).get()
    return Response(SentItemSerializer(n).data)
