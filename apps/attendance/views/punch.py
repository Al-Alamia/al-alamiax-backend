import uuid as uuid_lib
from datetime import date, datetime, timedelta
from typing import Optional

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.attendance.models import AttendanceDay, Punch
from apps.attendance.permissions import IsManagerPlus, can_correct, can_view
from apps.attendance.serializers import AttendanceDaySerializer, PunchSerializer
from apps.attendance.services import web_policy
from apps.attendance.services.evaluate import evaluate_and_allow
from apps.attendance.services.locks import PeriodClosed, assert_open
from apps.attendance.services.shifts import day_for_punch, owner_day, resolve_shift, shift_window, windows_for
from apps.attendance.types import PunchSource
from apps.attendance.views import error
from apps.users.models import User

TOO_SOON = timedelta(seconds=60)
MAX_UNIQUE_ID = 100


def _now() -> datetime:
    return datetime.now()


def _body(request) -> Optional[dict]:
    data = request.data
    return data if isinstance(data, dict) or hasattr(data, "getlist") else None


def _day_punches(user, d: date):
    """Punches owned by day ``d`` (shift window rules), ordered by timestamp."""
    windows = windows_for(user, [d + timedelta(days=i) for i in (-2, -1, 0, 1)])
    lo = datetime.combine(d - timedelta(days=1), datetime.min.time())
    hi = datetime.combine(d + timedelta(days=2), datetime.min.time())
    qs = (Punch.objects.filter(user=user, timestamp__gte=lo, timestamp__lt=hi)
          .select_related("device", "created_by").order_by("timestamp"))
    return [p for p in qs if owner_day(p.timestamp, windows) == d]


def _today_payload(user, now: datetime, unique_id: Optional[str], ip: str) -> dict:
    d = day_for_punch(user, now)
    shift = resolve_shift(user, d)
    shift_data = None
    if shift is not None:
        shift_data = {"name": shift.name, "expected_start": shift.start_time.strftime("%H:%M"),
                      "expected_end": shift.end_time.strftime("%H:%M"),
                      "grace_minutes": shift.grace_minutes}
    day = AttendanceDay.objects.filter(user=user, date=d).select_related("user__department").first()
    reason = web_policy.check(user, unique_id, ip)
    return {
        "date": d.isoformat(),
        "shift": shift_data,
        "punches": PunchSerializer(_day_punches(user, d), many=True).data,
        "day": AttendanceDaySerializer(day).data if day else None,
        "can_punch": reason is None,
        "blocked_reason": reason,
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def web_punch(request):
    user = request.user
    body = _body(request) or {}
    unique_id = body.get("unique_id")
    if unique_id is not None and (not isinstance(unique_id, str) or len(unique_id) > MAX_UNIQUE_ID):
        return error("unique_id must be a string of at most 100 characters", "invalid_unique_id", 400)
    ip = web_policy.client_ip(request)
    reason = web_policy.check(user, unique_id, ip)
    if reason:
        return error("Punch not allowed from this device or network", reason, 403)
    now = _now().replace(microsecond=0)
    last = Punch.objects.filter(user=user).order_by("-timestamp").first()
    if last is not None and timedelta(0) <= now - last.timestamp < TOO_SOON:
        return error("You punched less than a minute ago", "too_soon", 409)
    Punch.objects.create(user=user, timestamp=now, source=PunchSource.WEB, ip=ip or None,
                         browser_id=unique_id or "")
    evaluate_and_allow(user, day_for_punch(user, now), now)
    return Response(_today_payload(user, now, unique_id, ip))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def today(request):
    return Response(_today_payload(request.user, _now(), request.query_params.get("unique_id"),
                                   web_policy.client_ip(request)))


def _get_user(value) -> Optional[User]:
    try:
        return User.objects.filter(uuid=uuid_lib.UUID(str(value))).select_related("department").first()
    except ValueError:
        return None


def _parse_timestamp(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo is None else None


def _list_punches(request):
    raw = request.query_params.get("user")
    target = request.user if not raw else _get_user(raw)
    if target is None:
        return error("Invalid user", "invalid_user", 400)
    if not can_view(request.user, target):
        return error("Not allowed to view this user", "forbidden", 403)
    raw_date = request.query_params.get("date")
    try:
        d = date.fromisoformat(raw_date) if raw_date else _now().date()
    except ValueError:
        return error("Invalid date", "invalid_date", 400)
    return Response(PunchSerializer(_day_punches(target, d), many=True).data)


def _create_punch(request):
    if not IsManagerPlus().has_permission(request, None):
        return error("Not allowed", "forbidden", 403)
    body = _body(request)
    if body is None:
        return error("Request body must be a JSON object", "invalid_body", 400)
    target = _get_user(body.get("user"))
    if target is None:
        return error("Invalid user", "invalid_user", 400)
    if not can_correct(request.user, target):
        return error("Not allowed to correct this user", "forbidden", 403)
    note = body.get("note")
    if not isinstance(note, str) or not note.strip():
        return error("A note is required", "note_required", 400)
    ts = _parse_timestamp(body.get("timestamp"))
    if ts is None:
        return error("timestamp must be YYYY-MM-DDTHH:MM[:SS]", "invalid_timestamp", 400)
    if ts > _now():
        return error("timestamp cannot be in the future", "future_timestamp", 400)
    try:
        assert_open(day_for_punch(target, ts))
    except PeriodClosed as e:
        return error(str(e), "period_closed", 400)
    punch = Punch.objects.create(user=target, timestamp=ts, source=PunchSource.MANUAL,
                                 created_by=request.user, note=note.strip()[:255])
    evaluate_and_allow(target, day_for_punch(target, ts))
    return Response(PunchSerializer(punch).data, status=201)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def punches(request):
    return _list_punches(request) if request.method == "GET" else _create_punch(request)


@api_view(["DELETE"])
@permission_classes([IsManagerPlus])
def delete_punch(request, uuid):
    punch = Punch.objects.filter(uuid=uuid).select_related("user").first()
    if punch is None:
        return error("Punch not found", "not_found", 404)
    if not can_correct(request.user, punch.user):
        return error("Not allowed to correct this user", "forbidden", 403)
    if punch.source != PunchSource.MANUAL:
        return error("Only manual punches can be deleted", "not_manual", 400)
    user, ts = punch.user, punch.timestamp
    try:
        assert_open(day_for_punch(user, ts))
    except PeriodClosed as e:
        return error(str(e), "period_closed", 400)
    punch.delete()
    evaluate_and_allow(user, day_for_punch(user, ts))
    return Response(status=204)
