import ipaddress
import math
import uuid as uuid_lib
from datetime import date, datetime, time
from typing import Optional

from django.db import IntegrityError, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.attendance.models import (AttendanceSettings, DeductionPolicy, DeductionTier, Holiday, Shift,
                                    ShiftAssignment, WebPunchPolicy)
from apps.attendance.permissions import AuthenticatedReadHRWrite, IsHRPlus, ManagerReadHRWrite
from apps.attendance.serializers import (assignment_data, device_data, holiday_data, policy_data,
                                         settings_data, shift_data, web_punch_policy_data)
from apps.attendance.types import TierKind
from apps.attendance.views import error
from apps.users.models import Department, User, ZKConfig

MAX_GRACE = 120


def _now() -> datetime:
    return datetime.now()


def _body(request) -> Optional[dict]:
    data = request.data
    return data if isinstance(data, dict) or hasattr(data, "getlist") else None


def _uuid(value) -> Optional[uuid_lib.UUID]:
    try:
        return uuid_lib.UUID(str(value))
    except ValueError:
        return None


def _bad(message: str, type: str = "validation") -> Response:
    return error(message, type, 400)


def _not_found() -> Response:
    return error("Not found", "not_found", 404)


def _invalid_body() -> Response:
    return _bad("Request body must be a JSON object", "invalid_body")


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_time(value) -> Optional[time]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


def _parse_date(value) -> Optional[date]:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class _Invalid(Exception):
    def __init__(self, message: str, type: str = "validation"):
        super().__init__(message)
        self.message, self.type = message, type


def _int_in(value, lo: int, hi: int, field: str) -> int:
    if not _is_int(value) or not lo <= value <= hi:
        raise _Invalid(f"{field} must be an integer between {lo} and {hi}")
    return value


def _lookup(model, value, field: str):
    uid = _uuid(value) if value else None
    obj = model.objects.filter(pk=uid).first() if uid else None
    if obj is None:
        raise _Invalid(f"Unknown {field}")
    return obj


def _validate_shift(body: dict, shift: Optional[Shift]) -> dict:
    """Validated model field values; ``shift`` set means a partial update."""
    partial, out = shift is not None, {}
    if "name" in body or not partial:
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise _Invalid("name is required (max 100 characters)")
        name = name.strip()
        clash = Shift.objects.filter(name=name)
        if partial:
            clash = clash.exclude(pk=shift.pk)
        if clash.exists():
            raise _Invalid("A shift with this name already exists")
        out["name"] = name
    for field in ("start_time", "end_time"):
        if field in body or not partial:
            t = _parse_time(body.get(field))
            if t is None:
                raise _Invalid(f"{field} must be HH:MM")
            out[field] = t
    if "weekend_days" in body or not partial:
        days = body.get("weekend_days", [])
        if (not isinstance(days, list) or not all(_is_int(d) and 0 <= d <= 6 for d in days)
                or len(set(days)) != len(days)):
            raise _Invalid("weekend_days must be a list of unique integers 0-6")
        out["weekend_days"] = days
    if "grace_minutes" in body or not partial:
        out["grace_minutes"] = _int_in(body.get("grace_minutes", 0), 0, MAX_GRACE, "grace_minutes")
    if "active" in body:
        if not isinstance(body["active"], bool):
            raise _Invalid("active must be a boolean")
        out["active"] = body["active"]
    return out


@api_view(["GET", "POST"])
@permission_classes([ManagerReadHRWrite])
def shifts(request):
    if request.method == "GET":
        return Response([shift_data(s) for s in Shift.objects.order_by("name")])
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        values = _validate_shift(body, None)
    except _Invalid as e:
        return _bad(e.message, e.type)
    return Response(shift_data(Shift.objects.create(**values)), status=201)


@api_view(["GET", "PATCH"])
@permission_classes([ManagerReadHRWrite])
def shift_detail(request, uuid):
    shift = Shift.objects.filter(pk=uuid).first()
    if shift is None:
        return _not_found()
    if request.method == "GET":
        return Response(shift_data(shift))
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        values = _validate_shift(body, shift)
    except _Invalid as e:
        return _bad(e.message, e.type)
    for k, v in values.items():
        setattr(shift, k, v)
    shift.save()
    return Response(shift_data(shift))


def _validate_assignment(body: dict) -> dict:
    shift = _lookup(Shift, body.get("shift"), "shift")
    dept_raw, user_raw = body.get("department"), body.get("user")
    if bool(dept_raw) == bool(user_raw):
        raise _Invalid("Exactly one of department or user is required")
    effective_from = _parse_date(body.get("effective_from"))
    if effective_from is None:
        raise _Invalid("effective_from must be YYYY-MM-DD")
    department = _lookup(Department, dept_raw, "department") if dept_raw else None
    user = _lookup(User, user_raw, "user") if user_raw else None
    if ShiftAssignment.objects.filter(department=department, user=user,
                                      effective_from=effective_from).exists():
        raise _Invalid("An assignment already exists for this date")
    return {"shift": shift, "department": department, "user": user, "effective_from": effective_from}


@api_view(["GET", "POST"])
@permission_classes([ManagerReadHRWrite])
def shift_assignments(request):
    if request.method == "GET":
        qs = ShiftAssignment.objects.select_related("shift", "department", "user")
        for param, field in (("department", "department"), ("user", "user")):
            raw = request.query_params.get(param)
            if raw:
                uid = _uuid(raw)
                if uid is None:
                    return _bad(f"Invalid {param}")
                qs = qs.filter(**{field: uid})
        return Response([assignment_data(a) for a in qs.order_by("-effective_from", "-created_at")])
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        values = _validate_assignment(body)
        with transaction.atomic():
            a = ShiftAssignment.objects.create(**values)
    except _Invalid as e:
        return _bad(e.message, e.type)
    except IntegrityError:
        return _bad("An assignment already exists for this date")
    return Response(assignment_data(a), status=201)


@api_view(["DELETE"])
@permission_classes([ManagerReadHRWrite])
def shift_assignment_detail(request, uuid):
    a = ShiftAssignment.objects.filter(pk=uuid).first()
    if a is None:
        return _not_found()
    if a.effective_from <= _now().date():
        return _bad("Only assignments that have not started yet can be deleted")
    a.delete()
    return Response(status=204)


@api_view(["GET", "POST"])
@permission_classes([AuthenticatedReadHRWrite])
def holidays(request):
    if request.method == "GET":
        qs = Holiday.objects.select_related("department")
        raw_year = request.query_params.get("year")
        if raw_year:
            if not raw_year.isdigit():
                return _bad("year must be an integer")
            qs = qs.filter(date__year=int(raw_year))
        return Response([holiday_data(h) for h in qs.order_by("date", "name")])
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        d = _parse_date(body.get("date"))
        if d is None:
            raise _Invalid("date must be YYYY-MM-DD")
        name = body.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 150:
            raise _Invalid("name is required (max 150 characters)")
        dept = _lookup(Department, body.get("department"), "department") if body.get("department") else None
        if Holiday.objects.filter(date=d, department=dept).exists():
            raise _Invalid("A holiday already exists for this date")
        with transaction.atomic():
            h = Holiday.objects.create(date=d, name=name.strip(), department=dept)
    except _Invalid as e:
        return _bad(e.message, e.type)
    except IntegrityError:
        return _bad("A holiday already exists for this date")
    return Response(holiday_data(h), status=201)


@api_view(["DELETE"])
@permission_classes([AuthenticatedReadHRWrite])
def holiday_detail(request, uuid):
    h = Holiday.objects.filter(pk=uuid).first()
    if h is None:
        return _not_found()
    h.delete()
    return Response(status=204)


def _policy_fields(body: dict) -> dict:
    out = {}
    if "monthly_late_allowance" in body:
        v = body["monthly_late_allowance"]
        if not _is_int(v) or not 0 <= v <= 31:
            raise _Invalid("monthly_late_allowance must be an integer between 0 and 31")
        out["monthly_late_allowance"] = v
    if "absence_days" in body:
        v = body["absence_days"]
        if not _is_number(v) or not math.isfinite(v) or not 0 <= v <= 1:
            raise _Invalid("absence_days must be a number between 0 and 1")
        out["absence_days"] = float(v)
    return out


def _validate_tiers(raw) -> list:
    if not isinstance(raw, list):
        raise _Invalid("tiers must be a list", "invalid_tiers")
    seen, tiers = set(), []
    for t in raw:
        if not isinstance(t, dict):
            raise _Invalid("Each tier must be an object", "invalid_tiers")
        kind, minutes, days = t.get("kind"), t.get("min_minutes"), t.get("deduction_days")
        if kind not in TierKind.values:
            raise _Invalid("kind must be LATE or EARLY_LEAVE", "invalid_tiers")
        if not _is_int(minutes) or not 1 <= minutes <= 1440:
            raise _Invalid("min_minutes must be an integer between 1 and 1440", "invalid_tiers")
        if not _is_number(days) or not math.isfinite(days) or not 0 <= days <= 1:
            raise _Invalid("deduction_days must be between 0 and 1", "invalid_tiers")
        if (kind, minutes) in seen:
            raise _Invalid("Duplicate tier for the same kind and min_minutes", "invalid_tiers")
        seen.add((kind, minutes))
        tiers.append((kind, minutes, float(days)))
    return tiers


def _policies():
    return DeductionPolicy.objects.select_related("department").prefetch_related("tiers")


@api_view(["GET", "POST"])
@permission_classes([IsHRPlus])
def policies(request):
    if request.method == "GET":
        return Response([policy_data(p) for p in
                         _policies().order_by("-is_global", "department__name")])
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        if not body.get("department"):
            raise _Invalid("department is required")
        dept = _lookup(Department, body["department"], "department")
        fields = _policy_fields(body)
        if DeductionPolicy.objects.filter(department=dept).exists():
            return _bad("This department already has a policy", "duplicate")
        with transaction.atomic():
            p = DeductionPolicy.objects.create(department=dept, **fields)
    except _Invalid as e:
        return _bad(e.message, e.type)
    except IntegrityError:
        return _bad("This department already has a policy", "duplicate")
    return Response(policy_data(p), status=201)


@api_view(["PUT"])
@permission_classes([IsHRPlus])
def policy_detail(request, uuid):
    policy = DeductionPolicy.objects.filter(pk=uuid).first()
    if policy is None:
        return _not_found()
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        fields = _policy_fields(body)
        tiers = _validate_tiers(body["tiers"]) if "tiers" in body else None
    except _Invalid as e:
        return _bad(e.message, e.type)
    with transaction.atomic():
        for k, v in fields.items():
            setattr(policy, k, v)
        policy.save()
        if tiers is not None:
            policy.tiers.all().delete()
            DeductionTier.objects.bulk_create(
                [DeductionTier(policy=policy, kind=k, min_minutes=m, deduction_days=d) for k, m, d in tiers])
    return Response(policy_data(_policies().get(pk=policy.pk)))


@api_view(["GET"])
@permission_classes([IsHRPlus])
def web_punch_policies(request):
    by_dept = {p.department_id: p for p in WebPunchPolicy.objects.all()}
    return Response([web_punch_policy_data(d, by_dept.get(d.pk)) for d in Department.objects.order_by("name")])


def _validate_ips(raw) -> list:
    if not isinstance(raw, list):
        raise _Invalid("allowed_ips must be a list", "invalid_ips")
    for entry in raw:
        try:
            if not isinstance(entry, str):
                raise ValueError
            ipaddress.ip_network(entry.strip(), strict=False)
        except ValueError:
            raise _Invalid(f"Invalid IP or CIDR: {entry}", "invalid_ips")
    return [e.strip() for e in raw]


@api_view(["PUT"])
@permission_classes([IsHRPlus])
def web_punch_policy_detail(request, uuid):
    dept = Department.objects.filter(pk=uuid).first()
    if dept is None:
        return _bad("Unknown department", "invalid_department")
    body = _body(request)
    if body is None:
        return _invalid_body()
    values = {}
    try:
        for field in ("require_trusted_device", "require_office_ip"):
            if field in body:
                if not isinstance(body[field], bool):
                    raise _Invalid(f"{field} must be a boolean")
                values[field] = body[field]
        if "allowed_ips" in body:
            values["allowed_ips"] = _validate_ips(body["allowed_ips"])
    except _Invalid as e:
        return _bad(e.message, e.type)
    policy, _ = WebPunchPolicy.objects.update_or_create(department=dept, defaults=values)
    return Response(web_punch_policy_data(dept, policy))


@api_view(["GET", "PUT"])
@permission_classes([IsHRPlus])
def settings(request):
    current = AttendanceSettings.get()
    if request.method == "GET":
        return Response(settings_data(current))
    body = _body(request)
    if body is None:
        return _invalid_body()
    try:
        if "period_start_day" in body:
            current.period_start_day = _int_in(body["period_start_day"], 1, 28, "period_start_day")
        if "device_sync_minutes" in body:
            current.device_sync_minutes = _int_in(body["device_sync_minutes"], 5, 1440, "device_sync_minutes")
    except _Invalid as e:
        return _bad(e.message, e.type)
    current.save()
    return Response(settings_data(current))


@api_view(["GET"])
@permission_classes([IsHRPlus])
def devices(request):
    return Response([device_data(z) for z in ZKConfig.objects.order_by("name", "ip")])
