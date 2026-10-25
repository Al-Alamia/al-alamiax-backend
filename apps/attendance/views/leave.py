from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.models import LeaveAllowance, LeaveType
from apps.attendance.permissions import AuthenticatedReadHRWrite, IsHRPlus, can_view, is_hr_plus
from apps.attendance.serializers import balance_data, leave_allowance_data, leave_type_data
from apps.attendance.services import leave as svc
from apps.attendance.views import error
from apps.attendance.views.config import (_Invalid, _bad, _body, _invalid_body, _is_int, _is_number, _lookup,
                                          _not_found, _parse_date, _uuid)
from apps.users.models import User

MAX_DAYS = Decimal("9999.9")


def _now() -> datetime:
    return datetime.now()


def _decimal(value, field: str) -> Decimal:
    if not _is_number(value):
        raise _Invalid(f"{field} must be a number")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise _Invalid(f"{field} must be a number")
    if not d.is_finite() or not 0 <= d <= MAX_DAYS or d != d.quantize(Decimal("0.1")):
        raise _Invalid(f"{field} must be between 0 and {MAX_DAYS} with at most one decimal place")
    return d


def _flag(body: dict, out: dict, field: str) -> None:
    if field in body:
        if not isinstance(body[field], bool):
            raise _Invalid(f"{field} must be a boolean")
        out[field] = body[field]


def _validate_type(body: dict, current: Optional[LeaveType]) -> dict:
    partial, out = current is not None, {}
    if "name" in body or not partial:
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise _Invalid("name is required (max 100 characters)")
        name = name.strip()
        clash = LeaveType.objects.filter(name=name)
        if partial:
            clash = clash.exclude(pk=current.pk)
        if clash.exists():
            raise _Invalid("A leave type with this name already exists")
        out["name"] = name
    if "pay_percent" in body or not partial:
        v = body.get("pay_percent", 100)
        if not _is_int(v) or not 0 <= v <= 100:
            raise _Invalid("pay_percent must be an integer between 0 and 100")
        out["pay_percent"] = v
    if "yearly_allowance" in body:
        out["yearly_allowance"] = _decimal(body["yearly_allowance"], "yearly_allowance")
    for field in ("uses_balance", "requires_attachment", "is_active"):
        _flag(body, out, field)
    return out


@api_view(["GET", "POST"])
@permission_classes([AuthenticatedReadHRWrite])
def leave_types(request):
    if request.method == "GET":
        qs = LeaveType.objects.order_by("name")
        if not is_hr_plus(request.user):
            qs = qs.filter(is_active=True)
        return Response([leave_type_data(t) for t in qs])
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        values = _validate_type(body, None)
        with transaction.atomic():
            t = LeaveType.objects.create(**values)
    except _Invalid as e:
        return _bad(e.message, e.type)
    except IntegrityError:
        return _bad("A leave type with this name already exists")
    return Response(leave_type_data(t), status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AuthenticatedReadHRWrite])
def leave_type_detail(request, uuid):
    t = LeaveType.objects.filter(pk=uuid).first()
    if t is None or (request.method == "GET" and not t.is_active and not is_hr_plus(request.user)):
        return _not_found()
    if request.method == "GET":
        return Response(leave_type_data(t))
    if request.method == "DELETE":
        try:
            t.delete()
        except ProtectedError:
            return _bad("This leave type is used by requests; deactivate it instead", "in_use")
        return Response(status=204)
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        values = _validate_type(body, t)
    except _Invalid as e:
        return _bad(e.message, e.type)
    for k, v in values.items():
        setattr(t, k, v)
    t.save()
    return Response(leave_type_data(t))


def _year(value, field: str = "year") -> int:
    if not _is_int(value) or not 2000 <= value <= 2100:
        raise _Invalid(f"{field} must be an integer between 2000 and 2100")
    return value


@api_view(["GET", "POST"])
@permission_classes([IsHRPlus])
def leave_allowances(request):
    if request.method == "GET":
        qs = LeaveAllowance.objects.order_by("-year", "user__username", "leave_type__name")
        user_raw, year_raw = request.query_params.get("user"), request.query_params.get("year")
        if user_raw:
            uid = _uuid(user_raw)
            if uid is None:
                return _bad("Invalid user")
            qs = qs.filter(user=uid)
        if year_raw:
            if not year_raw.isdigit():
                return _bad("year must be an integer")
            qs = qs.filter(year=int(year_raw))
        return Response([leave_allowance_data(a) for a in qs])
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        user = _lookup(User, body.get("user"), "user")
        leave_type = _lookup(LeaveType, body.get("leave_type"), "leave_type")
        year, days = _year(body.get("year")), _decimal(body.get("days"), "days")
        with transaction.atomic():
            a = LeaveAllowance.objects.create(user=user, leave_type=leave_type, year=year, days=days)
    except _Invalid as e:
        return _bad(e.message, e.type)
    except IntegrityError:
        return _bad("An allowance already exists for this user, leave type and year", "duplicate")
    return Response(leave_allowance_data(a), status=201)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsHRPlus])
def leave_allowance_detail(request, uuid):
    a = LeaveAllowance.objects.filter(pk=uuid).first()
    if a is None:
        return _not_found()
    if request.method == "DELETE":
        a.delete()
        return Response(status=204)
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        a.days = _decimal(body.get("days"), "days")
    except _Invalid as e:
        return _bad(e.message, e.type)
    a.save()
    return Response(leave_allowance_data(a))


def _scoped_target(request) -> User:
    """The ``user`` query param (default: the viewer), or raise _Invalid / PermissionError when out of scope."""
    raw = request.query_params.get("user")
    if not raw:
        return request.user
    uid = _uuid(raw)
    target = User.objects.filter(pk=uid).first() if uid else None
    if target is None:
        raise _Invalid("Unknown user")
    if not can_view(request.user, target):
        raise PermissionError
    return target


def _forbidden() -> Response:
    return error("You cannot view this user's leave", "forbidden", 403)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def leave_balances(request):
    try:
        target = _scoped_target(request)
        raw = request.query_params.get("year")
        if raw and not raw.isdigit():
            raise _Invalid("year must be an integer")
    except _Invalid as e:
        return _bad(e.message, e.type)
    except PermissionError:
        return _forbidden()
    year = int(raw) if raw else _now().year
    return Response({"year": year, "results": [balance_data(r) for r in svc.balances(target, year)]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def leave_working_days(request):
    try:
        target = _scoped_target(request)
        start, end = (_parse_date(request.query_params.get(k)) for k in ("start", "end"))
        if start is None or end is None:
            raise _Invalid("start and end must be YYYY-MM-DD")
        if end < start:
            raise _Invalid("end must not be before start")
    except _Invalid as e:
        return _bad(e.message, e.type)
    except PermissionError:
        return _forbidden()
    return Response({"days": len(svc.working_dates(target, start, end))})
