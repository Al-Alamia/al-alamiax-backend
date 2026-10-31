import uuid as uuid_lib
from datetime import date
from decimal import Decimal

from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.models import AttendanceSettings, PeriodClose
from apps.attendance.permissions import is_hr_plus
from apps.attendance.services.periods import period_key_for
from apps.attendance.views import error
from apps.monthly_basic.permissions import can_edit_basic, can_manage_basic, list_scope
from apps.monthly_basic.services import BasicError, included_users, month_of, period_bounds
from apps.users.models import User
from apps.users.types import UserTypes

from . import services
from .models import Salary
from .serializers import history_row, money, user_data, user_ref
from .services import SalaryError
from .types import SalaryStatus

ZERO = Decimal("0")


def _err(e: SalaryError):
    return error(e.message, e.type, e.status)


def _period(raw):
    """Validated (key, start, end); raises SalaryError for invalid/future."""
    key = raw or period_key_for(date.today(), AttendanceSettings.get().period_start_day)
    try:
        month_of(key)
        start, end = period_bounds(key)
    except BasicError as e:
        raise SalaryError(e.type, e.message)
    if start > date.today():
        raise SalaryError("future_period", "The period has not started yet.")
    return key, start, end


def _body(request):
    return request.data if isinstance(request.data, dict) else {}


def _is_uuid(raw):
    try:
        uuid_lib.UUID(str(raw))
        return True
    except ValueError:
        return False


def _load(uuid):
    return User.objects.filter(uuid=uuid).select_related("department").first()


def _not_found():
    return error("Not found", "not_found", 404)


def _closed(start, end):
    return PeriodClose.objects.filter(start__lte=end, end__gte=start).select_related("closed_by").first()


def _name(u):
    return (u.get_full_name() or u.username).lower()


def _given(user, key):
    return Salary.objects.filter(user=user, period=key, status=SalaryStatus.GIVEN).first()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def salary_list(request):
    viewer = request.user
    scope = list_scope(viewer)
    if scope is None:
        return error("You do not have permission to do that.", "forbidden", 403)
    try:
        key, start, end = _period(request.query_params.get("period"))
    except SalaryError as e:
        return _err(e)
    q = request.query_params
    status_filter = q.get("status")
    if status_filter and status_filter not in (SalaryStatus.DRAFT, SalaryStatus.GIVEN):
        return error("Invalid status.", "invalid", 400)
    dept = q.get("department")
    if dept and not _is_uuid(dept):
        return error("Invalid department.", "invalid", 400)
    search = (q.get("search") or "").strip()

    qs = included_users(key).filter(pk__in=scope.values("pk"))
    if dept:
        qs = qs.filter(department__uuid=dept)
    if search:
        qs = qs.filter(Q(username__icontains=search) | Q(first_name__icontains=search)
                       | Q(last_name__icontains=search))
    given_ids = set(Salary.objects.filter(period=key, status=SalaryStatus.GIVEN)
                    .values_list("user_id", flat=True))
    if status_filter == SalaryStatus.GIVEN:
        qs = qs.filter(pk__in=given_ids)
    elif status_filter == SalaryStatus.DRAFT:
        qs = qs.exclude(pk__in=given_ids)
    users = sorted(qs.select_related("department", "project"), key=_name)

    closed = _closed(start, end)
    ended = date.today() >= end
    can_role = bool(is_hr_plus(viewer) or viewer.role == UserTypes.MANAGER)
    overridden = set(Salary.objects.filter(period=key, overrides__isnull=False)
                     .values_list("user_id", flat=True))

    def new_sum():
        return {"count": 0, "basic_net": ZERO, "commission": ZERO, "total": ZERO}

    totals, groups, results = new_sum(), {}, []
    totals["given"] = 0
    for u in users:
        c = services.compute(u, key)
        is_given = u.pk in given_ids
        net = None if c["basic"]["net"] is None else Decimal(c["basic"]["net"])
        comm = Decimal(c["commission"])
        total = None if c["total"] is None else Decimal(c["total"])
        group = groups.setdefault(u.project_id, {"project": u.project, **new_sum()})
        for acc in (totals, group):
            acc["count"] += 1
            acc["commission"] += comm
            if net is not None:
                acc["basic_net"] += net
            if total is not None:
                acc["total"] += total
        totals["given"] += is_given
        results.append({
            "user": user_data(u), "status": SalaryStatus.GIVEN.value if is_given else SalaryStatus.DRAFT.value,
            "basic_net": None if net is None else money(net),
            "commission": money(comm),
            "total": None if total is None else money(total),
            "has_overrides": any(p.get("override") for p in c["parts"]) if not is_given
            else u.pk in overridden,
            "error_types": [e["type"] for e in c["errors"]],
            "can_edit": bool(can_edit_basic(viewer, u) and not closed and not is_given),
        })

    def pack(acc):
        return {"count": acc["count"], "basic_net": money(acc["basic_net"]),
                "commission": money(acc["commission"]), "total": money(acc["total"])}

    ordered = sorted(groups.values(), key=lambda g: (g["project"] is None,
                                                      g["project"].name.lower() if g["project"] else ""))
    projects = [{"project": {"uuid": str(g["project"].uuid), "name": g["project"].name}
                 if g["project"] else None, **pack(g)} for g in ordered]
    return Response({
        "period": key, "start": start.isoformat(), "end": end.isoformat(),
        "closed": {"closed_by": user_ref(closed.closed_by),
                   "closed_at": closed.closed_at.isoformat()} if closed else None,
        "can_give_all": bool(can_role and ended and not closed),
        "totals": {**pack(totals), "given": totals["given"]},
        "projects": projects, "results": results,
    })


def _detail(viewer, target, key, start, end):
    c = services.compute(target, key)
    salary = Salary.objects.filter(user=target, period=key).select_related("given_by").first()
    is_given = salary is not None and salary.status == SalaryStatus.GIVEN
    closed = _closed(start, end) is not None
    included = included_users(key).filter(pk=target.pk).exists()
    editable = bool(can_edit_basic(viewer, target) and not closed)
    can_edit = bool(included and editable and not is_given)
    return {
        "period": key, "start": start.isoformat(), "end": end.isoformat(),
        "period_closed": closed, "user": user_data(target),
        "status": SalaryStatus.GIVEN.value if is_given else SalaryStatus.DRAFT.value,
        "given_by": user_ref(salary.given_by) if is_given and salary.given_by else None,
        "given_at": salary.given_at.isoformat() if is_given and salary.given_at else None,
        "basic": c["basic"], "parts": c["parts"], "commission": c["commission"],
        "total": c["total"], "errors": c["errors"],
        "can_edit": can_edit,
        "can_give": bool(can_edit and date.today() >= end and not c["errors"]),
        "can_ungive": bool(editable and is_given),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def salary_detail(request, uuid):
    viewer = request.user
    target = _load(uuid)
    if target is None:
        return _not_found()
    try:
        key, start, end = _period(request.query_params.get("period"))
    except SalaryError as e:
        return _err(e)
    if not (can_manage_basic(viewer, target)
            or (viewer.pk == target.pk and _given(target, key) is not None)):
        return _not_found()
    return Response(_detail(viewer, target, key, start, end))


def _action(request, uuid, fn, raw_period=None):
    target = _load(uuid)
    if target is None:
        return _not_found()
    try:
        key, start, end = _period(raw_period if raw_period is not None else _body(request).get("period"))
        fn(request.user, target, key)
    except SalaryError as e:
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


@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def override(request, uuid, part_key):
    if request.method == "DELETE":
        return _action(request, uuid,
                       lambda a, u, k: services.clear_override(a, u, k, part_key),
                       raw_period=request.query_params.get("period") or "")
    body = _body(request)
    return _action(request, uuid, lambda a, u, k: services.set_override(
        a, u, k, part_key, body.get("value"), body.get("reason")))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def give_all(request):
    try:
        key, _, _ = _period(_body(request).get("period"))
        result = services.give_all(request.user, key)
    except SalaryError as e:
        return _err(e)
    return Response(result)


def _history(user):
    qs = Salary.objects.filter(user=user, status=SalaryStatus.GIVEN).order_by("-period")
    return Response({"results": [history_row(s) for s in qs]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def mine(request):
    return _history(request.user)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def history(request, uuid):
    target = _load(uuid)
    if target is None or not (can_manage_basic(request.user, target) or request.user.pk == target.pk):
        return _not_found()
    return _history(target)
