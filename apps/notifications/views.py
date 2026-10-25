import uuid
from datetime import datetime

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.users.views.pagination import DefaultPagination

from .models import NotificationRecipient
from .queries import active_rows, visible_rows
from .serializers import InboxItemSerializer


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
