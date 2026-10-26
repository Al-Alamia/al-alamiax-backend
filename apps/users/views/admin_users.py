import uuid as uuid_lib

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.permissions import is_hr_plus
from apps.attendance.views import error
from apps.users.admin_permissions import assignable_roles, can_view_user, visible_users
from apps.users.models import User
from apps.users.types import UserTypes
from apps.users.serializers.admin import detail, list_item, option, user_name
from apps.users.services.users import UserAdminError, create_user, set_active, update_user
from apps.users.views.pagination import DefaultPagination

MAX_OPTIONS = 200
SEARCH_FIELDS = ("username", "first_name", "last_name", "crm_username")


def _can_list(viewer) -> bool:
    return is_hr_plus(viewer) or (viewer.role == UserTypes.MANAGER and viewer.department_id is not None)


def _forbidden():
    return error("You are not allowed to view users", "forbidden", 403)


def _not_found():
    return error("Not found", "not_found", 404)


def _body(request):
    data = request.data
    return data if isinstance(data, dict) or hasattr(data, "getlist") else None


def _uuid(value):
    try:
        return uuid_lib.UUID(str(value))
    except ValueError:
        return None


def _filtered(viewer, params):
    qs = visible_users(viewer).select_related("department", "project", "profile")
    if search := params.get("search", "").strip():
        query = Q()
        for field in SEARCH_FIELDS:
            query |= Q(**{f"{field}__icontains": search})
        qs = qs.filter(query)
    if role := params.get("role"):
        qs = qs.filter(role=role)
    for name in ("department", "project"):
        if raw := params.get(name):
            uid = _uuid(raw)
            qs = qs.filter(**{f"{name}__uuid": uid}) if uid else qs.none()
    if (active := params.get("is_active")) in ("true", "false"):
        qs = qs.filter(is_active=active == "true")
    return qs.order_by("-is_active", "role", "username")


def _service_error(exc: UserAdminError):
    return error(exc.message, exc.type, exc.status)


def _list(request):
    viewer = request.user
    if not _can_list(viewer):
        return _forbidden()
    pager = DefaultPagination()
    page = pager.paginate_queryset(_filtered(viewer, request.query_params), request)
    response = pager.get_paginated_response([list_item(request, u) for u in page])
    response.data["can_create"] = is_hr_plus(viewer)
    response.data["assignable_roles"] = assignable_roles(viewer)
    return response


def _create(request):
    body = _body(request)
    if body is None:
        return error("Request body must be a JSON object.", "invalid", 400)
    try:
        user = create_user(request.user, body)
    except UserAdminError as exc:
        return _service_error(exc)
    return Response(detail(request, User.objects.select_related("department", "project", "profile").get(pk=user.pk)),
                    status=201)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def users(request):
    return _list(request) if request.method == "GET" else _create(request)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def options(request):
    viewer = request.user
    if not _can_list(viewer):
        return _forbidden()
    qs = (visible_users(viewer).filter(is_active=True).select_related("department")
          .order_by("first_name", "last_name", "username")[:MAX_OPTIONS])
    return Response([option(u) for u in sorted(qs, key=lambda u: user_name(u).lower())])


def _target(request, uuid):
    user = User.objects.select_related("department", "project", "profile").filter(uuid=uuid).first()
    return user if user is not None and can_view_user(request.user, user) else None


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def user_detail(request, uuid):
    user = _target(request, uuid)
    if user is None:
        return _not_found()
    if request.method == "PATCH":
        body = _body(request)
        if body is None:
            return error("Request body must be a JSON object.", "invalid", 400)
        try:
            update_user(request.user, user, body)
        except UserAdminError as exc:
            return _service_error(exc)
        user = _target(request, uuid) or user
    return Response(detail(request, user))


def _toggle(request, uuid, active):
    user = _target(request, uuid)
    if user is None:
        return _not_found()
    try:
        set_active(request.user, user, active)
    except UserAdminError as exc:
        return _service_error(exc)
    return Response(detail(request, _target(request, uuid) or user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def deactivate(request, uuid):
    return _toggle(request, uuid, False)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def activate(request, uuid):
    return _toggle(request, uuid, True)
