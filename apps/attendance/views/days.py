import uuid as uuid_lib
from datetime import date, datetime, timedelta
from typing import Optional

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.models import AttendanceDay, AttendanceSettings
from apps.attendance.permissions import IsHRPlus, IsManagerPlus, can_view, is_hr_plus, scoped_users
from apps.attendance.serializers import AttendanceDaySerializer, UserRefSerializer
from apps.attendance.services.evaluate import recalculate
from apps.attendance.services.periods import period_key_for, period_range
from apps.attendance.types import DayStatus
from apps.attendance.views import error
from apps.users.models import Department, User

MAX_RECALC_DAYS = 62
NONE = "NONE"


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


def _sum_status(days, status) -> int:
    return sum(1 for d in days if d.status == status)


def _summary(days) -> dict:
    present, late = _sum_status(days, DayStatus.PRESENT), _sum_status(days, DayStatus.LATE)
    return {
        "present": present,
        "late": late,
        "absent": _sum_status(days, DayStatus.ABSENT),
        "incomplete": _sum_status(days, DayStatus.INCOMPLETE),
        "weekend": _sum_status(days, DayStatus.WEEKEND),
        "holiday": _sum_status(days, DayStatus.HOLIDAY),
        "no_shift": _sum_status(days, DayStatus.NO_SHIFT),
        "leave": _sum_status(days, DayStatus.LEAVE),
        "excused": _sum_status(days, DayStatus.EXCUSED),
        "late_minutes": sum(d.late_minutes for d in days),
        "early_leave_minutes": sum(d.early_leave_minutes for d in days),
        "deduction_days": round(sum(d.deduction_days for d in days), 2),
        "on_time_percent": round(100 * present / (present + late), 1) if present + late else 0,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def period_days(request):
    raw = request.query_params.get("user")
    if raw:
        uid = _uuid(raw)
        target = User.objects.filter(uuid=uid).select_related("department").first() if uid else None
    else:
        target = request.user
    if target is None:
        return error("Invalid user", "invalid_user", 400)
    if not can_view(request.user, target):
        return error("Not allowed to view this user", "forbidden", 403)
    start_day = AttendanceSettings.get().period_start_day
    key = request.query_params.get("period") or period_key_for(_now().date(), start_day)
    try:
        start, end = period_range(key, start_day)
    except ValueError:
        return error("period must be YYYY-MM", "invalid_period", 400)
    days = list(AttendanceDay.objects.filter(user=target, date__gte=start, date__lte=end)
                .select_related("user__department").order_by("date"))
    return Response({
        "user": UserRefSerializer(target).data,
        "period": {"key": key, "start": start.isoformat(), "end": end.isoformat()},
        "results": AttendanceDaySerializer(days, many=True).data,
        "summary": _summary(days),
    })


@api_view(["GET"])
@permission_classes([IsManagerPlus])
def daily(request):
    params = request.query_params
    raw_date = params.get("date")
    try:
        d = date.fromisoformat(raw_date) if raw_date else _now().date()
    except ValueError:
        return error("Invalid date", "invalid_date", 400)
    status = params.get("status")
    if status and status != NONE and status not in DayStatus.values:
        return error("Invalid status", "invalid_status", 400)
    users = scoped_users(request.user)
    raw_dept = params.get("department")
    if raw_dept:
        dept_id = _uuid(raw_dept)
        dept = Department.objects.filter(uuid=dept_id).first() if dept_id else None
        if dept is None:
            return error("Invalid department", "invalid_department", 400)
        if not is_hr_plus(request.user) and request.user.department_id != dept.pk:
            return error("Not allowed to view this department", "forbidden", 403)
        users = users.filter(department=dept)
    users = users.select_related("department").order_by("first_name", "username")
    day_by_user = {x.user_id: x for x in
                   AttendanceDay.objects.filter(date=d, user__in=users).select_related("user__department")}
    counts = {s: 0 for s in DayStatus.values}
    counts[NONE] = 0
    rows = []
    for u in users:
        day = day_by_user.get(u.pk)
        counts[day.status if day else NONE] += 1
        if status and (day.status if day else NONE) != status:
            continue
        rows.append({"user": UserRefSerializer(u).data,
                     "day": AttendanceDaySerializer(day).data if day else None})
    return Response({"date": d.isoformat(), "results": rows, "counts": counts})


@api_view(["POST"])
@permission_classes([IsHRPlus])
def recalculate_view(request):
    body = _body(request)
    if body is None:
        return error("Request body must be a JSON object", "invalid_body", 400)
    try:
        start, end = date.fromisoformat(body["from"]), date.fromisoformat(body["to"])
    except (KeyError, TypeError, ValueError):
        return error("from and to must be YYYY-MM-DD dates", "invalid_range", 400)
    if end < start or (end - start) + timedelta(days=1) > timedelta(days=MAX_RECALC_DAYS):
        return error(f"Range must be 1 to {MAX_RECALC_DAYS} days", "invalid_range", 400)
    users = scoped_users(request.user)
    if body.get("user"):
        uid = _uuid(body["user"])
        if uid is None or not User.objects.filter(uuid=uid).exists():
            return error("Invalid user", "invalid_user", 400)
        users = users.filter(uuid=uid)
    if body.get("department"):
        dept_id = _uuid(body["department"])
        if dept_id is None or not Department.objects.filter(uuid=dept_id).exists():
            return error("Invalid department", "invalid_department", 400)
        users = users.filter(department__uuid=dept_id)
    return Response({"updated": recalculate(start, end, users, _now())})
