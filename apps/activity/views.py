import uuid as uuid_lib
from datetime import datetime, timedelta

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.permissions import is_hr_plus
from apps.attendance.views import error
from apps.users.models import User
from apps.users.views.pagination import DefaultPagination

from .models import Area, PageView
from .permissions import can_view_activity, scope_user_ids, scope_users, visible_events
from .serializers import event_json
from .services.presence import heartbeat, presence_for, presence_rows

AUTH = [IsAuthenticated]


class ActivityPagination(DefaultPagination):
    page_size = 30
    max_page_size = 100


def _forbidden():
    return error("Forbidden", "forbidden", 403)


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@api_view(["POST"])
@permission_classes(AUTH)
def heartbeat_view(request):
    path = request.data.get("path") if hasattr(request.data, "get") else None
    try:
        heartbeat(request.user, path, datetime.now())
    except ValueError as e:
        return error(str(e), "invalid", 400)
    return Response(status=204)


@api_view(["GET"])
@permission_classes(AUTH)
def access(request):
    return Response({"can_view": can_view_activity(request.user)})


@api_view(["GET"])
@permission_classes(AUTH)
def events(request):
    viewer = request.user
    if not can_view_activity(viewer):
        return _forbidden()
    q = request.query_params
    qs = visible_events(viewer)

    area = q.get("area")
    if area:
        if area not in Area.values:
            return error("Invalid area", "invalid", 400)
        qs = qs.filter(area=area)

    for key, lookup in (("from", "created_at__date__gte"), ("to", "created_at__date__lte")):
        if q.get(key):
            d = _parse_date(q.get(key))
            if d is None:
                return error(f"Invalid '{key}' date", "invalid", 400)
            qs = qs.filter(**{lookup: d})

    user = q.get("user")
    if user:
        try:
            uid = uuid_lib.UUID(user)
        except ValueError:
            return error("Invalid user", "invalid", 400)
        target = User.objects.filter(uuid=uid).values_list("pk", flat=True).first()
        ids = scope_user_ids(viewer)
        if target is None or (ids is not None and target not in ids and target != viewer.pk):
            qs = qs.none()
        else:
            role = q.get("role")
            if role == "actor":
                qs = qs.filter(actor_id=target)
            elif role == "subject":
                qs = qs.filter(subject_id=target)
            else:
                qs = qs.filter(Q(actor_id=target) | Q(subject_id=target))

    qs = qs.order_by("-created_at", "-pk")
    paginator = ActivityPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response([event_json(e) for e in page])


@api_view(["GET"])
@permission_classes(AUTH)
def presence(request):
    viewer = request.user
    if not can_view_activity(viewer):
        return _forbidden()
    users = scope_users(viewer)
    search = (request.query_params.get("search") or "").strip()
    if search:
        users = users.filter(Q(username__icontains=search) | Q(first_name__icontains=search)
                             | Q(last_name__icontains=search))
    rows = presence_rows(users, datetime.now())
    status = request.query_params.get("status", "all")
    if status == "online":
        rows = [r for r in rows if r["online"]]
    elif status == "offline":
        rows = [r for r in rows if not r["online"]]
    return Response({"results": rows})


@api_view(["GET"])
@permission_classes(AUTH)
def user_detail(request, user_uuid):
    viewer = request.user
    if not can_view_activity(viewer):
        return _forbidden()
    if is_hr_plus(viewer):
        target = User.objects.filter(uuid=user_uuid).first()
    else:
        target = scope_users(viewer).filter(uuid=user_uuid).first()
    if target is None:
        return error("Not found", "not_found", 404)

    now = datetime.now()
    raw = request.query_params.get("date")
    day = _parse_date(raw) if raw else now.date()
    if day is None:
        return error("Invalid date", "invalid", 400)

    views = PageView.objects.filter(user=target, started_at__date=day)
    rows = [{
        "path": pv.path,
        "started_at": pv.started_at.isoformat(),
        "last_seen_at": pv.last_seen_at.isoformat(),
        "seconds": int((pv.last_seen_at - pv.started_at).total_seconds()),
    } for pv in views.order_by("-started_at", "-created_at")[:200]]
    seconds = sum(
        int((s - st).total_seconds())
        for st, s in views.values_list("started_at", "last_seen_at"))
    events_30d = visible_events(viewer).filter(
        Q(actor=target) | Q(subject=target),
        created_at__gte=now - timedelta(days=30)).count()
    return Response({
        "presence": presence_for(target, now),
        "date": day.isoformat(),
        "page_views": rows,
        "stats": {"today_seconds": seconds, "pages_today": views.count(),
                  "events_30d": events_30d},
    })
