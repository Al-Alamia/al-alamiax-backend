import uuid as uuid_lib
from datetime import date

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.models import AttendanceSettings, PeriodClose
from apps.attendance.permissions import is_hr_plus
from apps.attendance.services.periods import period_key_for
from apps.attendance.views import error
from apps.users.admin_permissions import is_top
from apps.users.models import User
from apps.users.types import UserTypes

from . import services
from .models import MonthlyBasic
from .permissions import can_edit_basic, can_view_basic, list_scope
from .serializers import breakdown_data, inputs_data, money, user_data, user_ref
from .services import BasicError
from .types import BasicStatus


def _err(e: BasicError):
    return error(e.message, e.type, e.status)


def _period(raw):
    """Validated period key; raises BasicError for invalid/future."""
    key = raw or period_key_for(date.today(), AttendanceSettings.get().period_start_day)
    services.month_of(key)
    start, end = services.period_bounds(key)
    if start > date.today():
        raise BasicError("future_period", "The period has not started yet.")
    return key, start, end


def _is_uuid(raw):
    try:
        uuid_lib.UUID(str(raw))
        return True
    except ValueError:
        return False


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _can_give_role(viewer):
    return bool(is_hr_plus(viewer) or viewer.role == UserTypes.MANAGER)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def basic_list(request):
    viewer = request.user
    scope = list_scope(viewer)
    if scope is None:
        return error("You do not have permission to do that.", "forbidden", 403)
    try:
        key, start, end = _period(request.query_params.get("period"))
    except BasicError as e:
        return _err(e)
    q = request.query_params
    status_filter = q.get("status")
    if status_filter and status_filter not in (BasicStatus.DRAFT, BasicStatus.GIVEN):
        return error("Invalid status.", "invalid", 400)
    dept = q.get("department")
    if dept and not _is_uuid(dept):
        return error("Invalid department.", "invalid", 400)
    search = (q.get("search") or "").strip()

    def narrow(qs):
        if dept:
            qs = qs.filter(department__uuid=dept)
        if search:
            qs = qs.filter(Q(username__icontains=search) | Q(first_name__icontains=search)
                           | Q(last_name__icontains=search))
        return qs

    ids = scope.values("pk")
    included = narrow(services.included_users(key).filter(pk__in=ids))
    missing = narrow(services.missing_salary_users(key).filter(pk__in=ids))
    records = {r.user_id: r for r in MonthlyBasic.objects.filter(period=key)}
    if status_filter:
        want = status_filter == BasicStatus.GIVEN
        given_ids = [uid for uid, r in records.items() if r.status == BasicStatus.GIVEN]
        included = included.filter(pk__in=given_ids) if want else included.exclude(pk__in=given_ids)
    users = sorted(included.select_related("department"),
                   key=lambda u: (u.get_full_name() or u.username).lower())
    values = services.compute_many(users, key)

    closed = PeriodClose.objects.filter(period=key).select_related("closed_by").first()
    ended = date.today() >= end
    hr = bool(is_hr_plus(viewer))
    results, total_basic, total_net, given = [], 0, 0, 0
    for u in users:
        v = values[u.pk]
        r = records.get(u.pk)
        is_given = r is not None and r.status == BasicStatus.GIVEN
        given += is_given
        total_basic += v["basic"]
        total_net += v["net"]
        results.append({
            "user": user_data(u), "status": r.status if r else BasicStatus.DRAFT,
            "basic": money(v["basic"]), "deduction_days": money(v["deduction_days"]),
            "net": money(v["net"]),
            "can_edit": bool(can_edit_basic(viewer, u) and not closed and not is_given),
        })
    return Response({
        "period": key, "start": start.isoformat(), "end": end.isoformat(),
        "closed": {"closed_by": user_ref(closed.closed_by),
                   "closed_at": closed.closed_at.isoformat()} if closed else None,
        "can_close": bool(hr and not closed and ended),
        "can_reopen": bool(is_top(viewer) and closed),
        "can_give": bool(_can_give_role(viewer) and ended and not closed),
        "totals": {"basic": money(total_basic), "net": money(total_net),
                   "given": given, "total": len(users)},
        "missing_salary": [user_ref(u) for u in sorted(
            missing, key=lambda u: (u.get_full_name() or u.username).lower())],
        "results": results,
    })


def _detail(viewer, target, key, start, end):
    record = MonthlyBasic.objects.filter(user=target, period=key).first()
    values = services.compute(target, key, record)
    closed = PeriodClose.objects.filter(period=key).exists()
    is_given = record is not None and record.status == BasicStatus.GIVEN
    can_edit = bool(can_edit_basic(viewer, target) and not closed and not is_given)
    return {
        "period": key, "start": start.isoformat(), "end": end.isoformat(),
        "period_closed": closed, "user": user_data(target),
        "status": record.status if record else BasicStatus.DRAFT,
        "given_by": user_ref(record.given_by) if record and record.given_by else None,
        "given_at": record.given_at.isoformat() if record and record.given_at else None,
        "inputs": inputs_data(record), "breakdown": breakdown_data(values),
        "can_edit": can_edit,
        "can_give": bool(can_edit and date.today() >= end),
    }


def _load(uuid):
    return User.objects.filter(uuid=uuid).select_related("department").first()


def _not_found():
    return error("Not found", "not_found", 404)


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def basic_detail(request, uuid):
    viewer = request.user
    target = _load(uuid)
    if target is None:
        return _not_found()
    try:
        key, start, end = _period(request.query_params.get("period"))
        record = MonthlyBasic.objects.filter(user=target, period=key).first()
        if not can_view_basic(viewer, target, record):
            return _not_found()
        if request.method == "PATCH":
            services.update_inputs(viewer, target, key, _body(request))
    except BasicError as e:
        return _err(e)
    return Response(_detail(viewer, target, key, start, end))


def _action(request, uuid, fn):
    target = _load(uuid)
    if target is None:
        return _not_found()
    try:
        key, start, end = _period(_body(request).get("period"))
        fn(request.user, target, key)
    except BasicError as e:
        return _err(e)
    return Response(_detail(request.user, target, key, start, end))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def give(request, uuid):
    return _action(request, uuid, services.give)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ungive(request, uuid):
    return _action(request, uuid, services.ungive)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def close(request):
    try:
        key, _, _ = _period(_body(request).get("period"))
        services.close_period(request.user, key)
    except BasicError as e:
        return _err(e)
    return Response({"period": key, "closed": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reopen(request):
    body = _body(request)
    try:
        key, _, _ = _period(body.get("period"))
        services.reopen_period(request.user, key, body.get("reason"))
    except BasicError as e:
        return _err(e)
    return Response({"period": key, "closed": False})
