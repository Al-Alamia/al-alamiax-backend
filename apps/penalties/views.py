import uuid as uuid_lib
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.permissions import AuthenticatedReadHRWrite
from apps.attendance.views import error
from apps.users.models import User
from apps.users.views.pagination import DefaultPagination

from .models import Penalty, PenaltyType
from .permissions import can_add, can_manage_types, can_view, penalty_targets, visible_penalties
from .serializers import penalty_data, type_data, user_brief
from .services import PenaltyError, create_penalty, period_total, void_penalty
from .types import PenaltyKind

MAX_VALUE = Decimal("99999999.99")
MAX_TARGETS = 50


class _Invalid(Exception):
    pass


def _invalid(message: str) -> Response:
    return error(message, "invalid", 400)


def _not_found() -> Response:
    return error("Not found", "not_found", 404)


def _uuid(value) -> Optional[uuid_lib.UUID]:
    try:
        return uuid_lib.UUID(str(value))
    except ValueError:
        return None


def _body(request) -> Optional[dict]:
    data = request.data
    return data if isinstance(data, dict) or hasattr(data, "getlist") else None


def _present(body, name):
    value = body.get(name)
    return None if value in (None, "") else value


def _value(raw, field: str) -> Decimal:
    try:
        d = Decimal(str(raw))
    except InvalidOperation:
        raise _Invalid(f"'{field}' must be a number.")
    if not d.is_finite() or d > MAX_VALUE:
        raise _Invalid(f"'{field}' must be a number up to {MAX_VALUE}.")
    return d


def _date(raw, field: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise _Invalid(f"'{field}' must be a YYYY-MM-DD date.")


def _by_uuid(model, raw, label: str):
    uid = _uuid(raw)
    obj = model.objects.filter(uuid=uid).first() if uid else None
    if obj is None:
        raise _Invalid(f"Invalid {label}.")
    return obj


# ---- types ----

def _type_values(body: dict, current: Optional[PenaltyType]) -> dict:
    partial, out = current is not None, {}
    if "name" in body or not partial:
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise _Invalid("name is required (max 100 characters).")
        name = name.strip()
        clash = PenaltyType.objects.filter(name=name)
        if partial:
            clash = clash.exclude(pk=current.pk)
        if clash.exists():
            raise _Invalid("A penalty type with this name already exists.")
        out["name"] = name
    if "kind" in body or not partial:
        if body.get("kind") not in PenaltyKind.values:
            raise _Invalid("Invalid kind.")
        out["kind"] = body["kind"]
    if "default_value" in body or not partial:
        raw = body.get("default_value")
        if raw is None or isinstance(raw, bool):
            raise _Invalid("'default_value' is required.")
        value = _value(raw, "default_value")
        if value <= 0:
            raise _Invalid("'default_value' must be greater than zero.")
        out["default_value"] = value.quantize(Decimal("0.01"))
    if "is_active" in body:
        if not isinstance(body["is_active"], bool):
            raise _Invalid("is_active must be a boolean.")
        out["is_active"] = body["is_active"]
    return out


@api_view(["GET", "POST"])
@permission_classes([AuthenticatedReadHRWrite])
def types(request):
    if request.method == "GET":
        qs = PenaltyType.objects.order_by("name")
        if request.query_params.get("active") in ("1", "true"):
            qs = qs.filter(is_active=True)
        return Response([type_data(t) for t in qs])
    body = _body(request)
    if body is None:
        return _invalid("Request body must be a JSON object.")
    try:
        values = _type_values(body, None)
        with transaction.atomic():
            t = PenaltyType.objects.create(**values)
    except _Invalid as exc:
        return _invalid(str(exc))
    except IntegrityError:
        return _invalid("A penalty type with this name already exists.")
    return Response(type_data(t), status=201)


@api_view(["PATCH"])
@permission_classes([AuthenticatedReadHRWrite])
def type_detail(request, uuid):
    t = PenaltyType.objects.filter(uuid=uuid).first()
    if t is None:
        return _not_found()
    body = _body(request)
    if body is None:
        return _invalid("Request body must be a JSON object.")
    try:
        values = _type_values(body, t)
        with transaction.atomic():
            for k, v in values.items():
                setattr(t, k, v)
            t.save()
    except _Invalid as exc:
        return _invalid(str(exc))
    except IntegrityError:
        return _invalid("A penalty type with this name already exists.")
    return Response(type_data(t))


# ---- penalties ----

def _queryset():
    return Penalty.objects.select_related("user", "penalty_type", "created_by", "voided_by")


def _filtered(viewer, params):
    qs = visible_penalties(viewer)
    qs = qs.select_related("user", "penalty_type", "created_by", "voided_by")
    if params.get("scope") == "mine":
        qs = qs.filter(user=viewer)
    if v := params.get("user"):
        uid = _uuid(v)
        qs = qs.filter(user__uuid=uid) if uid else qs.none()
    if v := params.get("kind"):
        qs = qs.filter(kind=v)
    if v := params.get("type"):
        if v == "custom":
            qs = qs.filter(penalty_type__isnull=True)
        else:
            uid = _uuid(v)
            qs = qs.filter(penalty_type__uuid=uid) if uid else qs.none()
    if v := params.get("status"):
        if v == "active":
            qs = qs.filter(voided_at__isnull=True)
        elif v == "voided":
            qs = qs.filter(voided_at__isnull=False)
    if v := params.get("from"):
        qs = qs.filter(date__gte=_date(v, "from"))
    if v := params.get("to"):
        qs = qs.filter(date__lte=_date(v, "to"))
    if v := params.get("search"):
        qs = qs.filter(Q(title__icontains=v) | Q(description__icontains=v)
                       | Q(user__first_name__icontains=v) | Q(user__last_name__icontains=v)
                       | Q(user__username__icontains=v))
    return qs


def _create_data(body: dict) -> dict:
    data = {"user": _by_uuid(User, _present(body, "user"), "user"),
            "date": _date(_present(body, "date"), "date")}
    if (v := _present(body, "penalty_type")) is not None:
        data["penalty_type"] = _by_uuid(PenaltyType, v, "penalty type")
    if (v := _present(body, "value")) is not None:
        data["value"] = _value(v, "value")
    for name in ("title", "kind", "description"):
        if (v := _present(body, name)) is not None:
            data[name] = str(v)
    return data


def _create(request):
    body = _body(request)
    if body is None:
        return _invalid("Request body must be a JSON object.")
    try:
        penalty = create_penalty(request.user, _create_data(body))
    except _Invalid as exc:
        return _invalid(str(exc))
    except PenaltyError as exc:
        return error(exc.message, exc.type, exc.status)
    penalty = _queryset().get(pk=penalty.pk)
    return Response(penalty_data(penalty, request.user), status=201)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def penalty_list(request):
    if request.method == "POST":
        return _create(request)
    try:
        qs = _filtered(request.user, request.query_params)
    except _Invalid as exc:
        return _invalid(str(exc))
    pager = DefaultPagination()
    page = pager.paginate_queryset(qs, request)
    return pager.get_paginated_response([penalty_data(p, request.user) for p in page])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def void(request, uuid):
    penalty = _queryset().filter(pk__in=visible_penalties(request.user).values("pk"), uuid=uuid).first()
    if penalty is None:
        return _not_found()
    body = _body(request)
    reason = body.get("reason") if body is not None else None
    try:
        penalty = void_penalty(request.user, penalty, reason if isinstance(reason, str) else "")
    except PenaltyError as exc:
        return error(exc.message, exc.type, exc.status)
    return Response(penalty_data(_queryset().get(pk=penalty.pk), request.user))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def period_total_view(request):
    uid = _uuid(request.query_params.get("user"))
    target = User.objects.filter(uuid=uid).first() if uid else None
    if target is None:
        return _invalid("Invalid user.")
    if not can_view(request.user, target):
        return error("You may not view this user.", "forbidden", 403)
    try:
        return Response(period_total(target, request.query_params.get("period", "")))
    except ValueError:
        return _invalid("'period' must be YYYY-MM.")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def meta(request):
    return Response({"can_add": can_add(request.user), "can_manage_types": can_manage_types(request.user)})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def targets(request):
    qs = penalty_targets(request.user)
    if v := request.query_params.get("search"):
        qs = qs.filter(Q(first_name__icontains=v) | Q(last_name__icontains=v) | Q(username__icontains=v))
    return Response([user_brief(u) for u in qs.order_by("first_name", "last_name", "username")[:MAX_TARGETS]])
