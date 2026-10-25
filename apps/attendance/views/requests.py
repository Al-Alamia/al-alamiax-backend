import uuid as uuid_lib
from datetime import date, datetime
from typing import Optional

from django.db.models import Q
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.models import AttendanceSettings, LeaveType, Request
from apps.attendance.permissions import can_decide, can_view, is_hr_plus, scoped_users
from apps.attendance.serializers import RequestSerializer
from apps.attendance.services import requests as svc
from apps.attendance.services.periods import period_key_for, period_range
from apps.attendance.services.requests import RequestError
from apps.attendance.types import RequestKind, RequestStatus
from apps.attendance.views import error
from apps.users.models import User
from apps.users.types import UserTypes
from apps.users.views.pagination import DefaultPagination

PARSERS = [MultiPartParser, FormParser, JSONParser]


class _Invalid(Exception):
    pass


def _uuid(value) -> Optional[uuid_lib.UUID]:
    try:
        return uuid_lib.UUID(str(value))
    except ValueError:
        return None


def _not_found() -> Response:
    return error("Not found", "not_found", 404)


def _bad(message: str, type: str = "validation") -> Response:
    return error(message, type, 400)


def _forbidden(exc) -> Response:
    return error(str(exc.detail), "forbidden", 403)


def _ctx(request, with_days=False) -> dict:
    return {"request": request, "viewer": request.user, "today": svc._today(), "with_days": with_days}


def _queryset():
    return Request.objects.select_related("user__department", "created_by", "decided_by", "leave_type")


def _get_visible(request, uuid) -> Optional[Request]:
    req = _queryset().filter(uuid=uuid).first()
    return req if req is not None and can_view(request.user, req.user) else None


def _present(data, name):
    value = data.get(name)
    return None if value in (None, "") else value


def _by_uuid(model, value, label):
    uid = _uuid(value)
    obj = model.objects.filter(uuid=uid).first() if uid else None
    if obj is None:
        raise _Invalid(f"Invalid {label}.")
    return obj


def _parse_date(value, name) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise _Invalid(f"'{name}' must be a YYYY-MM-DD date.")


def _parse_data(body) -> dict:
    """Convert the request body (multipart or JSON) into the types ``services.requests`` expects.
    Empty strings and nulls mean "not provided"."""
    out = {}
    if (v := _present(body, "kind")) is not None:
        out["kind"] = v
    for name in ("start_date", "end_date"):
        if (v := _present(body, name)) is not None:
            out[name] = _parse_date(v, name)
    if (v := _present(body, "user")) is not None:
        out["user"] = _by_uuid(User, v, "user")
    if (v := _present(body, "leave_type")) is not None:
        out["leave_type"] = _by_uuid(LeaveType, v, "leave type")
    if (v := _present(body, "cancels")) is not None:
        out["cancels"] = _by_uuid(Request, v, "cancels")
    if (v := _present(body, "minutes")) is not None:
        try:
            out["minutes"] = int(str(v))
        except ValueError:
            raise _Invalid("'minutes' must be a whole number.")
    if (v := _present(body, "punch_time")) is not None:
        try:
            punch_time = datetime.fromisoformat(str(v))
        except ValueError:
            raise _Invalid("'punch_time' must be an ISO datetime.")
        if punch_time.tzinfo is not None:
            raise _Invalid("'punch_time' must not include a timezone offset.")
        out["punch_time"] = punch_time
    if body.get("details") is not None:
        out["details"] = str(body["details"])
    return out


def _body(request):
    data = request.data
    return data if isinstance(data, dict) or hasattr(data, "getlist") else None


def _flag(value) -> bool:
    return value is True or str(value).lower() in ("true", "1")


def _list_queryset(viewer, params):
    qs = _queryset()
    scope = params.get("scope")
    if scope == "mine":
        qs = qs.filter(user=viewer)
    elif scope == "approvals":
        qs = qs.filter(status=RequestStatus.PENDING, user__in=scoped_users(viewer))
    elif not is_hr_plus(viewer):
        visible = Q(user=viewer)
        if viewer.role == UserTypes.MANAGER and viewer.department_id is not None:
            visible |= Q(user__department_id=viewer.department_id)
        qs = qs.filter(visible)
    if v := params.get("user"):
        qs = qs.filter(user__uuid=_uuid(v)) if _uuid(v) else qs.none()
    if v := params.get("kind"):
        qs = qs.filter(kind=v)
    if v := params.get("status"):
        qs = qs.filter(status=v)
    for name, lookup in (("date_from", "end_date__gte"), ("date_to", "start_date__lte")):
        if v := params.get(name):
            qs = qs.filter(**{lookup: _parse_date(v, name)})
    return qs, scope


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@parser_classes(PARSERS)
def request_list(request):
    if request.method == "POST":
        return _submit(request)
    try:
        qs, scope = _list_queryset(request.user, request.query_params)
    except _Invalid as exc:
        return _bad(str(exc))
    items = list(qs)
    if scope == "approvals":
        items = [r for r in items if can_decide(request.user, r)]
    pager = DefaultPagination()
    page = pager.paginate_queryset(items, request)
    return pager.get_paginated_response(RequestSerializer(page, many=True, context=_ctx(request)).data)


def _submit(request):
    body = _body(request)
    if body is None:
        return _bad("Request body must be a JSON object", "invalid_body")
    try:
        data = _parse_data(body)
        req = svc.submit(request.user, data, request.FILES.get("attachment"))
    except _Invalid as exc:
        return _bad(str(exc))
    except RequestError as exc:
        return _bad(exc.message, exc.type)
    except PermissionDenied as exc:
        return _forbidden(exc)
    req = _queryset().get(pk=req.pk)
    return Response(RequestSerializer(req, context=_ctx(request, True)).data, status=201)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
@parser_classes(PARSERS)
def request_detail(request, uuid):
    req = _get_visible(request, uuid)
    if req is None:
        return _not_found()
    if request.method == "PATCH":
        body = _body(request)
        if body is None:
            return _bad("Request body must be a JSON object", "invalid_body")
        try:
            data = _parse_data(body)
            data.pop("user", None)
            data.pop("kind", None)
            req = svc.edit(request.user, req, data, request.FILES.get("attachment"))
        except _Invalid as exc:
            return _bad(str(exc))
        except RequestError as exc:
            return _bad(exc.message, exc.type)
        except PermissionDenied as exc:
            return _forbidden(exc)
        req = _queryset().get(pk=req.pk)
    return Response(RequestSerializer(req, context=_ctx(request, True)).data)


def _action(request, uuid, run):
    req = _get_visible(request, uuid)
    if req is None:
        return _not_found()
    try:
        run(req, request.data if _body(request) is not None else {})
    except RequestError as exc:
        return _bad(exc.message, exc.type)
    except PermissionDenied as exc:
        return _forbidden(exc)
    req = _queryset().get(pk=req.pk)
    return Response(RequestSerializer(req, context=_ctx(request, True)).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes(PARSERS)
def approve(request, uuid):
    return _action(request, uuid, lambda r, b: svc.approve(
        request.user, r, b.get("note") or "", _flag(b.get("over_balance"))))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes(PARSERS)
def reject(request, uuid):
    return _action(request, uuid, lambda r, b: svc.reject(request.user, r, b.get("note") or ""))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes(PARSERS)
def cancel(request, uuid):
    return _action(request, uuid, lambda r, b: svc.cancel(request.user, r))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes(PARSERS)
def revoke(request, uuid):
    return _action(request, uuid, lambda r, b: svc.revoke(request.user, r, b.get("note") or ""))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def period(request):
    raw = request.query_params.get("user")
    if raw:
        uid = _uuid(raw)
        target = User.objects.filter(uuid=uid).select_related("department").first() if uid else None
    else:
        target = request.user
    if target is None:
        return _bad("Invalid user", "invalid_user")
    if not can_view(request.user, target):
        return error("Not allowed to view this user", "forbidden", 403)
    start_day = AttendanceSettings.get().period_start_day
    key = request.query_params.get("period") or period_key_for(svc._today(), start_day)
    try:
        start, end = period_range(key, start_day)
    except ValueError:
        return _bad("period must be YYYY-MM", "invalid_period")
    qs = _queryset().filter(user=target, start_date__lte=end, end_date__gte=start).order_by("start_date")
    return Response(RequestSerializer(qs, many=True, context=_ctx(request)).data)
